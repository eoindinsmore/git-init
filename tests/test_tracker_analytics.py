"""Tests for track-record analytics (spec §4, §8).

Calibration/hit-rate/P&L maths are unit-tested on hand-built view frames (spec §8:
"calibration math verified against a hand-computed fixture"); a wiring test runs the
full new_call → mark → build_view path.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from quant import store
from tracker import analytics, calls, marking
from tracker.analytics import _CONF_EDGES, _CONF_LABELS
from tracker.events import Expression, TradeDirection


def _view(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal view frame with the derived bucket columns analytics expects."""
    df = pd.DataFrame(rows)
    df["confidence_bucket"] = pd.cut(
        df["confidence"], bins=_CONF_EDGES, labels=_CONF_LABELS, include_lowest=True
    )
    return df


# --- Calibration ------------------------------------------------------------------

def test_calibration_brier_hand_computed():
    view = _view([
        {"is_market_resolution": True, "confidence": 0.6, "hit": 1.0},
        {"is_market_resolution": True, "confidence": 0.6, "hit": 0.0},
        {"is_market_resolution": True, "confidence": 0.8, "hit": 1.0},
    ])
    cal = analytics.calibration(view)
    # mean((0.6-1)^2, (0.6-0)^2, (0.8-1)^2) = mean(0.16, 0.36, 0.04)
    assert cal.brier == pytest.approx((0.16 + 0.36 + 0.04) / 3)
    assert cal.n == 3 and cal.sparse  # n < 20


def test_calibration_excludes_discretionary_closes():
    view = _view([
        {"is_market_resolution": True, "confidence": 0.6, "hit": 1.0},
        {"is_market_resolution": False, "confidence": 0.6, "hit": np.nan},  # a close
    ])
    cal = analytics.calibration(view)
    assert cal.n == 1  # the close does not count toward calibration


# --- Hit rate ---------------------------------------------------------------------

def test_hit_rate_overall_and_grouped():
    view = _view([
        {"is_market_resolution": True, "confidence": 0.6, "hit": 1.0, "metal": "copper"},
        {"is_market_resolution": True, "confidence": 0.6, "hit": 0.0, "metal": "copper"},
        {"is_market_resolution": True, "confidence": 0.8, "hit": 1.0, "metal": "aluminium"},
    ])
    overall = analytics.hit_rate(view)
    assert overall.iloc[0]["n"] == 3 and overall.iloc[0]["hit_rate"] == pytest.approx(2 / 3)
    assert bool(overall.iloc[0]["sparse"]) is True

    by_metal = analytics.hit_rate(view, by="metal").set_index("group")
    assert by_metal.loc["copper", "hit_rate"] == pytest.approx(0.5)
    assert by_metal.loc["aluminium", "hit_rate"] == pytest.approx(1.0)


# --- P&L --------------------------------------------------------------------------

def test_pnl_summary_math():
    view = pd.DataFrame([
        {"status": "target_hit", "realized_pnl_R": 1.0, "resolved_at": pd.Timestamp("2026-03-01")},
        {"status": "stopped", "realized_pnl_R": -0.5, "resolved_at": pd.Timestamp("2026-03-02")},
        {"status": "target_hit", "realized_pnl_R": 2.0, "resolved_at": pd.Timestamp("2026-03-03")},
    ])
    s = analytics.pnl_summary(view)
    assert s.total_R == pytest.approx(2.5)
    assert s.expectancy_R == pytest.approx(0.8333, abs=1e-3)
    assert s.avg_win_R == pytest.approx(1.5)
    assert s.avg_loss_R == pytest.approx(-0.5)
    assert s.win_rate == pytest.approx(2 / 3)
    assert s.max_drawdown_R == pytest.approx(-0.5)
    assert s.time_under_water_days == 1


# --- Integration: log → mark → view ----------------------------------------------

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
def env(tmp_path):
    reg = tmp_path / "registry"
    reg.mkdir()
    (reg / "cu.yaml").write_text(_REG_YAML, encoding="utf-8")
    dates = pd.bdate_range("2026-02-02", periods=21)
    values = [100.0] * len(dates)
    values[5] = 111.0  # spike through target
    df = pd.DataFrame({
        "series_id": "cu_proxy", "date": dates, "value": values, "as_of": dates,
        "source": "test", "frequency": "D", "unit": "USD/t", "last_updated": dates,
    })
    store_path = tmp_path / "facts.parquet"
    store.write_observations(df, path=store_path)
    return tmp_path / "events.jsonl", store_path, reg


def test_build_view_end_to_end(env):
    events_path, store_path, reg = env
    calls.new_call(
        instrument="cu_proxy", expression=Expression.OUTRIGHT, metal="copper",
        direction=TradeDirection.LONG, target=110.0, stop=90.0, horizon_days=30,
        confidence=0.6, thesis="End-to-end copper proxy call for the analytics view.",
        path=events_path, store_path=store_path, registry_dir=reg,
        _now=datetime(2026, 2, 2, 12, 0, tzinfo=UTC),
    )
    marking.mark_open_calls("2026-03-30", path=events_path, store_path=store_path)

    view = analytics.build_view(as_of="2026-03-30", path=events_path, store_path=store_path)
    assert len(view) == 1
    row = view.iloc[0]
    assert row["status"] == "target_hit" and row["realized_pnl_R"] == pytest.approx(1.1)

    cal = analytics.calibration(view)
    assert cal.n == 1
    stats = analytics.process_stats(
        view, path=events_path, store_path=store_path, as_of="2026-03-30"
    )
    assert stats["n_calls"] == 1 and stats["n_resolved"] == 1


def test_open_call_shows_unrealized(env):
    events_path, store_path, reg = env
    calls.new_call(
        instrument="cu_proxy", expression=Expression.OUTRIGHT, metal="copper",
        direction=TradeDirection.LONG, target=200.0, stop=90.0, horizon_days=300,
        confidence=0.5, thesis="Open copper proxy call, far target, stays open here.",
        path=events_path, store_path=store_path, registry_dir=reg,
        _now=datetime(2026, 2, 2, 12, 0, tzinfo=UTC),
    )
    # Not resolved by the marking date → open, with a running unrealized mark.
    view = analytics.build_view(as_of="2026-02-20", path=events_path, store_path=store_path)
    row = view.iloc[0]
    assert row["status"] == "open"
    assert pd.notna(row["unrealized_pnl_R"]) and pd.isna(row["realized_pnl_R"])
