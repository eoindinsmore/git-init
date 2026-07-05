"""Tests for the marking engine + pricing conventions (spec §3, §8).

The credibility-critical marking behaviours: next-close entry (never the same-day
close), stop precedence / first-touch, horizon expiry, R-multiple maths, and — the
headline §8 requirement — that a mark uses the price *vintage* that existed on the
marking date, so a later revision cannot rewrite whether a level was hit.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from quant import store
from tracker import calls, marking
from tracker import events as ev
from tracker.events import Expression, Stopped, TargetHit, TradeDirection
from tracker.pricing import entry_mark, r_multiple
from tracker.state import replay

_REG_YAML = """\
- series_id: cu_proxy
  source: test
  source_code: CU
  name: Copper proxy
  unit: USD/t
  frequency: D
  sa_status: NSA
  tags: {metal: copper, category: price_proxy}
  caveats: Free proxy — not a licensed price.
"""


@pytest.fixture
def reg(tmp_path):
    d = tmp_path / "registry"
    d.mkdir()
    (d / "cu.yaml").write_text(_REG_YAML, encoding="utf-8")
    return d


def _store(tmp_path, obs, series_id="cu_proxy"):
    """obs: list of (date, value, as_of). Writes a throwaway facts parquet, returns path."""
    path = tmp_path / "facts.parquet"
    df = pd.DataFrame({
        "series_id": series_id,
        "date": [pd.Timestamp(d) for d, _, _ in obs],
        "value": [v for _, v, _ in obs],
        "as_of": [pd.Timestamp(a) for _, _, a in obs],
        "source": "test", "frequency": "D", "unit": "USD/t",
        "last_updated": [pd.Timestamp(a) for _, _, a in obs],
    })
    store.write_observations(df, path=path)
    return path


def _flat(dates, value, revisions=None):
    """(date, value, as_of=date) for each date, with optional {date: (value, as_of)} overrides
    appended as extra revision rows."""
    obs = [(d, value, d) for d in dates]
    for d, (v, a) in (revisions or {}).items():
        obs.append((d, v, a))
    return obs


def _mk_call(reg, store_path, events_path, **over):
    kw = dict(
        instrument="cu_proxy", expression=Expression.OUTRIGHT, metal="copper",
        direction=TradeDirection.LONG, target=110.0, stop=90.0, horizon_days=30,
        confidence=0.6, thesis="Directional copper proxy call for marking tests here.",
        path=events_path, store_path=store_path, registry_dir=reg,
        _now=datetime(2026, 2, 2, 12, 0, tzinfo=UTC),
    )
    kw.update(over)
    return calls.new_call(**kw)


# --- Pure pricing --------------------------------------------------------------

def test_r_multiple_long_and_short():
    assert r_multiple(100, 110, 90, TradeDirection.LONG) == pytest.approx(1.0)
    assert r_multiple(100, 89, 90, TradeDirection.LONG) == pytest.approx(-1.1)
    assert r_multiple(100, 90, 110, TradeDirection.SHORT) == pytest.approx(1.0)


def test_entry_is_next_close_not_same_day():
    # A close prints at d2 00:00; a call logged d2 12:00 must enter at d3, not d2.
    series = pd.DataFrame({
        "date": pd.to_datetime(["2026-02-02", "2026-02-03", "2026-02-04"]),
        "value": [105.0, 100.0, 101.0],
    })
    date, price = entry_mark(series, datetime(2026, 2, 2, 12, 0, tzinfo=UTC))
    assert date == pd.Timestamp("2026-02-03") and price == 100.0


# --- Marking resolutions -------------------------------------------------------

def test_target_hit(reg, tmp_path):
    events_path = tmp_path / "events.jsonl"
    dates = pd.bdate_range("2026-02-02", periods=21)
    obs = _flat(dates, 100.0)
    obs[5] = (dates[5], 111.0, dates[5])  # spike through the target on d5
    store_path = _store(tmp_path, obs)
    call = _mk_call(reg, store_path, events_path)

    emitted = marking.mark_open_calls("2026-03-30", path=events_path, store_path=store_path)
    assert len(emitted) == 1 and isinstance(emitted[0], TargetHit)
    assert emitted[0].exit_price == 111.0
    assert emitted[0].pnl_R == pytest.approx(1.1)
    assert replay(ev.read_events(events_path))[call.call_id].status == "target_hit"


def test_stop_precedence_first_touch(reg, tmp_path):
    # Price dips to the stop on d3, then rallies through the target on d6.
    # First touch is the stop → the call is stopped (worst-case convention, spec §3).
    events_path = tmp_path / "events.jsonl"
    dates = pd.bdate_range("2026-02-02", periods=21)
    obs = _flat(dates, 100.0)
    obs[3] = (dates[3], 89.0, dates[3])
    obs[6] = (dates[6], 111.0, dates[6])
    store_path = _store(tmp_path, obs)
    _mk_call(reg, store_path, events_path)

    emitted = marking.mark_open_calls("2026-03-30", path=events_path, store_path=store_path)
    assert len(emitted) == 1 and isinstance(emitted[0], Stopped)
    assert emitted[0].exit_price == 89.0


def test_expiry_at_horizon(reg, tmp_path):
    events_path = tmp_path / "events.jsonl"
    dates = pd.bdate_range("2026-02-02", periods=21)
    store_path = _store(tmp_path, _flat(dates, 100.0))  # never touches a level
    _mk_call(reg, store_path, events_path, horizon_days=5)

    # Before the horizon: still open, nothing emitted.
    assert marking.mark_open_calls("2026-02-04", path=events_path, store_path=store_path) == []
    # After the horizon: expires at the last in-horizon close, flat → 0R.
    emitted = marking.mark_open_calls("2026-03-30", path=events_path, store_path=store_path)
    assert len(emitted) == 1 and emitted[0].event_type == ev.EventType.EXPIRED
    assert emitted[0].pnl_R == pytest.approx(0.0)


def test_marking_is_idempotent(reg, tmp_path):
    events_path = tmp_path / "events.jsonl"
    dates = pd.bdate_range("2026-02-02", periods=21)
    obs = _flat(dates, 100.0)
    obs[5] = (dates[5], 111.0, dates[5])
    store_path = _store(tmp_path, obs)
    _mk_call(reg, store_path, events_path)

    marking.mark_open_calls("2026-03-30", path=events_path, store_path=store_path)
    # Second run: the call is already resolved → no new events.
    again = marking.mark_open_calls("2026-03-30", path=events_path, store_path=store_path)
    assert again == []
    assert ev.verify(events_path).ok


def test_marking_respects_vintage_not_revision(reg, tmp_path):
    """Spec §8: a revision must not rewrite history — the mark uses the vintage."""
    events_path = tmp_path / "events.jsonl"
    dates = pd.bdate_range("2026-02-02", periods=21)
    # d2 originally printed 111 (as_of d2, hits target); later revised down to 101
    # (as_of d10, no hit).
    obs = _flat(dates, 100.0)
    obs[2] = (dates[2], 111.0, dates[2])
    obs.append((dates[2], 101.0, dates[10]))  # the revision
    store_path = _store(tmp_path, obs)

    # Marking as of d3 sees only the original vintage → target hit at 111.
    _mk_call(reg, store_path, events_path)
    emitted = marking.mark_open_calls(dates[3], path=events_path, store_path=store_path)
    assert len(emitted) == 1 and isinstance(emitted[0], TargetHit)
    assert emitted[0].exit_price == 111.0

    # A fresh call marked after the revision sees 101 → no hit, still inside horizon.
    events2 = tmp_path / "events2.jsonl"
    _mk_call(reg, store_path, events2)
    assert marking.mark_open_calls(dates[20], path=events2, store_path=store_path) == []
