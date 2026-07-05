"""Tests for quant.pit — lag-aware point-in-time retrieval.

The headline case is the *backfilled single as_of leak*: when history is loaded
in one pass every row shares one as_of (today), so the vintage filter alone would
leak a value before it was really released. The publication-lag filter fixes it.
"""

from __future__ import annotations

import pandas as pd

from quant import pit, store


def _row(sid, date, value, as_of, freq="M"):
    return dict(series_id=sid, date=date, value=value, as_of=as_of,
                source="fred", frequency=freq, unit="u", last_updated="2026-01-01")


def test_lag_filter_hides_unreleased_period(tmp_path):
    p = tmp_path / "facts.parquet"
    # All rows backfilled today (single as_of) — vintage filter can't protect us.
    store.write_observations(pd.DataFrame([
        _row("s", "2020-01-01", 100.0, "2026-01-01"),
        _row("s", "2020-02-01", 101.0, "2026-01-01"),
        _row("s", "2020-03-01", 102.0, "2026-01-01"),
    ]), p)

    # 45-day lag: on 1 April 2020, March (period-end 1 Mar) is NOT yet released
    # (released ~15 Apr), but Feb and Jan are.
    got = pit.get_series_asof("s", "2020-04-01", publication_lag_days=45, path=p)
    assert got["date"].max() == pd.Timestamp("2020-02-01")
    assert 102.0 not in got["value"].tolist()

    # Later, once March has cleared its lag, it appears.
    later = pit.get_series_asof("s", "2020-05-01", publication_lag_days=45, path=p)
    assert later["date"].max() == pd.Timestamp("2020-03-01")


def test_lag_zero_same_day_known(tmp_path):
    p = tmp_path / "facts.parquet"
    store.write_observations(pd.DataFrame([
        _row("d", "2020-01-01", 5.0, "2020-01-01", freq="D"),
        _row("d", "2020-01-02", 6.0, "2020-01-02", freq="D"),
    ]), p)
    got = pit.get_series_asof("d", "2020-01-02", publication_lag_days=0, path=p)
    assert got["date"].max() == pd.Timestamp("2020-01-02")  # same-day known


def test_uses_latest_vintage_value(tmp_path):
    p = tmp_path / "facts.parquet"
    # Documented behaviour: get_series_asof reconstructs *availability* from lag but
    # uses the latest (revised) value of each date. Strict revision-vintage PIT is
    # store.get_series(as_of=...)'s job — the two tools are complementary.
    store.write_observations(pd.DataFrame([
        _row("s", "2020-01-01", 100.0, "2020-02-10"),
        _row("s", "2020-01-01", 99.0, "2020-03-15"),  # later revision, folded in
    ]), p)
    got = pit.get_series_asof("s", "2020-04-01", publication_lag_days=10, path=p)
    assert float(got["value"].iloc[0]) == 99.0


def test_empty_series_returns_empty(tmp_path):
    p = tmp_path / "facts.parquet"
    got = pit.get_series_asof("nope", "2020-04-01", publication_lag_days=0, path=p)
    assert got.empty
    assert list(got.columns) == ["date", "value"]


def _write_registry(reg_dir):
    (reg_dir / "t.yaml").write_text(
        """
- series_id: fast
  source: fred
  source_code: F
  name: Fast daily
  unit: u
  frequency: D
  sa_status: NSA
  publication_lag_days: 0
  tags: {category: activity}
- series_id: slow
  source: fred
  source_code: S
  name: Slow monthly
  unit: u
  frequency: M
  sa_status: NSA
  publication_lag_days: 40
  tags: {category: activity}
""",
        encoding="utf-8",
    )


def test_panel_asof_ragged_edges(tmp_path):
    p = tmp_path / "facts.parquet"
    reg = tmp_path / "registry"
    reg.mkdir()
    _write_registry(reg)
    store.write_observations(pd.DataFrame([
        _row("fast", "2020-03-01", 1.0, "2026-01-01", freq="D"),
        _row("slow", "2020-02-01", 9.0, "2026-01-01"),
        _row("slow", "2020-03-01", 9.5, "2026-01-01"),
    ]), p)
    # fast lag 0 (Mar visible); slow lag 40 (Mar hidden on 1 Apr) -> ragged edges,
    # panel leaves the missing slow-March cell as NaN.
    panel = pit.get_panel_asof(["fast", "slow"], "2020-04-01", registry_dir=reg, path=p)
    assert list(panel.columns) == ["fast", "slow"]
    assert panel.loc[pd.Timestamp("2020-03-01"), "fast"] == 1.0
    assert pd.isna(panel.loc[pd.Timestamp("2020-03-01"), "slow"])
    assert panel.loc[pd.Timestamp("2020-02-01"), "slow"] == 9.0
