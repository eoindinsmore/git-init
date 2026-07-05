"""Tests for the event-sourced trade-call log (spec §1, §2, §8).

Covers the credibility-critical invariants: append-only storage, hash-chain tamper
detection, and the hard validation on ``call.new`` / ``call.amend``. Marking-time
invariants (next-close entry, anti-backdating against price data, stop precedence) are
in ``test_tracker_marking.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from tracker import calls
from tracker import events as ev
from tracker.calls import CallError
from tracker.events import Expression, TradeDirection
from tracker.state import CLOSED, OPEN, replay

# --- Fixtures: a tiny self-contained store + registry ------------------------------

_REG_YAML = """\
- series_id: cu_proxy
  source: test
  source_code: CU
  name: Copper proxy
  unit: USD/t
  frequency: D
  sa_status: NSA
  tags:
    metal: copper
    category: price_proxy
  caveats: Free proxy — not a licensed price.
"""


@pytest.fixture
def env(tmp_path):
    """Return (events_path, store_path, registry_dir) wired to throwaway files."""
    reg = tmp_path / "registry"
    reg.mkdir()
    (reg / "cu.yaml").write_text(_REG_YAML, encoding="utf-8")

    store_path = tmp_path / "facts.parquet"
    from quant import store

    dates = pd.bdate_range("2026-01-01", periods=60)
    df = pd.DataFrame({
        "series_id": "cu_proxy",
        "date": dates,
        "value": [9000 + i * 10 for i in range(len(dates))],  # gently rising
        # A daily proxy is captured the day it prints → as_of == date (lag 0). This is
        # what makes vintage-strict marking honest (spec §8).
        "as_of": dates,
        "source": "test",
        "frequency": "D",
        "unit": "USD/t",
        "last_updated": dates,
    })
    store.write_observations(df, path=store_path)

    return tmp_path / "events.jsonl", store_path, reg


def _new(env, **over):
    events_path, store_path, reg = env
    kw = dict(
        instrument="cu_proxy",
        expression=Expression.OUTRIGHT,
        metal="copper",
        direction=TradeDirection.LONG,
        target=10_000.0,
        stop=8_800.0,
        horizon_days=30,
        confidence=0.6,
        thesis="Copper proxy dislocation vs trend; expect mean reversion higher.",
        path=events_path,
        store_path=store_path,
        registry_dir=reg,
        _now=datetime(2026, 3, 2, 12, 0, tzinfo=UTC),
    )
    kw.update(over)
    return calls.new_call(**kw)


# --- call.new validation ----------------------------------------------------------

def test_new_call_appends_and_opens(env):
    events_path, *_ = env
    call = _new(env)
    states = replay(ev.read_events(events_path))
    assert states[call.call_id].status == OPEN
    assert states[call.call_id].regime_at_entry is None  # state series not in the store


def test_wrong_side_levels_rejected(env):
    # Long with target below the last mark → nonsense, must be refused.
    with pytest.raises(CallError, match="correct side|bracket"):
        _new(env, target=8_000.0)


def test_unknown_instrument_rejected(env):
    with pytest.raises(CallError, match="registry"):
        _new(env, instrument="not_a_series")


def test_non_live_expression_rejected(env):
    with pytest.raises(CallError, match="not available yet|Live expressions"):
        _new(env, expression=Expression.TIME_SPREAD)


def test_confidence_granularity_enforced(env):
    with pytest.raises(Exception, match="multiple of 0.05"):
        _new(env, confidence=0.63)


def test_thesis_minimum_length(env):
    with pytest.raises(Exception, match="20 characters"):
        _new(env, thesis="too short")


def test_horizon_range(env):
    with pytest.raises(Exception, match="5.*365|horizon"):
        _new(env, horizon_days=2)


# --- Append-only + hash chain -----------------------------------------------------

def test_append_only_never_rewrites_prior_lines(env):
    events_path, *_ = env
    _new(env)
    before = events_path.read_bytes()
    _new(env, target=11_000.0)
    after = events_path.read_bytes()
    # The first line's bytes are a strict prefix of the file after the second append.
    assert after.startswith(before)


def test_verify_ok_on_clean_log(env):
    events_path, *_ = env
    _new(env)
    _new(env, target=11_000.0)
    res = ev.verify(events_path)
    assert res.ok and res.n_events == 2


def test_verify_detects_edited_line(env):
    events_path, *_ = env
    _new(env)
    _new(env, target=11_000.0)
    lines = events_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("10000", "9999")  # tamper with the first call's target
    events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = ev.verify(events_path)
    assert not res.ok and res.broken_at == 1  # break shows up at the *next* line's prev_hash


def test_verify_detects_deleted_line(env):
    events_path, *_ = env
    _new(env)
    _new(env, target=11_000.0)
    _new(env, target=12_000.0)
    lines = events_path.read_text(encoding="utf-8").splitlines()
    del lines[1]  # excise the middle event
    events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = ev.verify(events_path)
    assert not res.ok and res.broken_at == 1


def test_verify_detects_inserted_line(env):
    events_path, *_ = env
    a = _new(env)
    lines = events_path.read_text(encoding="utf-8").splitlines()
    forged = ev.read_events(events_path)[0].model_copy(update={"target": 99_999.0})
    lines.insert(1, forged.model_dump_json())
    events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = ev.verify(events_path)
    assert not res.ok
    assert a  # silence unused


def test_append_refuses_stale_prev_hash(env):
    events_path, *_ = env
    _new(env)
    # Build an event whose prev_hash points at genesis, not the current head.
    from tracker.events import Amend

    stale = Amend(call_id="x", prev_hash=ev.GENESIS_HASH, reason="stale")
    with pytest.raises(ev.ChainError):
        ev.append(stale, events_path)


# --- amend / close / correct fold + freezing --------------------------------------

def test_amend_applies_and_counts(env):
    events_path, *_ = env
    call = _new(env)
    calls.amend(call.call_id, reason="tighten stop", stop=9_100.0, path=events_path)
    st = replay(ev.read_events(events_path))[call.call_id]
    assert st.stop == 9_100.0 and st.n_amends == 1


def test_amend_on_closed_call_rejected(env):
    events_path, store_path, _ = env
    call = _new(env)
    calls.close(call.call_id, reason="discretionary", path=events_path,
                _now=datetime(2026, 3, 10, 12, 0, tzinfo=UTC))
    with pytest.raises(CallError, match="frozen|closed"):
        calls.amend(call.call_id, reason="late", stop=9_200.0, path=events_path)


def test_close_freezes(env):
    events_path, *_ = env
    call = _new(env)
    calls.close(call.call_id, reason="took profit", path=events_path,
                _now=datetime(2026, 3, 10, 12, 0, tzinfo=UTC))
    st = replay(ev.read_events(events_path))[call.call_id]
    assert st.status == CLOSED and st.close_reason == "took profit"


def test_correction_counts_and_records(env):
    events_path, *_ = env
    call = _new(env)
    first_event_id = ev.read_events(events_path)[0].event_id
    calls.correct(call.call_id, corrects_event_id=first_event_id,
                  what_was_wrong="fat-fingered metal", fields={"metal": "aluminium"},
                  path=events_path)
    st = replay(ev.read_events(events_path))[call.call_id]
    assert st.n_corrections == 1 and st.metal == "aluminium"
