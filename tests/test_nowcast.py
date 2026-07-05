"""Tests for quant.nowcast — bridge equations, ragged edge, vintages, benchmarks."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from quant.nowcast import (
    BridgeModel,
    NowcastVintage,
    accuracy_vs_information,
    aggregate_over,
    benchmark_comparison,
    period_bounds,
    read_all,
    record,
)


def _monthly_indicator(n=192, seed=0, within_q_trend=0.0):
    idx = pd.date_range("2000-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(seed)
    base = np.linspace(100, 160, n) + rng.normal(scale=1.0, size=n)
    if within_q_trend:
        base = base + within_q_trend * (np.arange(n) % 3)  # rises within each quarter
    return pd.Series(base, index=idx)


def _quarterly_target(indicator, beta=2.0, const=5.0, seed=1):
    spans = period_bounds(pd.date_range("2000-03-31", periods=64, freq="QE"))
    rng = np.random.default_rng(seed)
    vals = {}
    for end, (start, stop) in spans.items():
        q_mean = aggregate_over(indicator, start, stop, how="mean")
        if not np.isnan(q_mean):
            vals[end] = const + beta * q_mean + rng.normal(scale=0.5)
    return pd.Series(vals)


def test_period_bounds_are_contiguous():
    idx = pd.date_range("2020-03-31", periods=4, freq="QE")
    spans = period_bounds(idx)
    ends = sorted(spans)
    # Each period starts the day after the previous end.
    for prev, cur in zip(ends[:-1], ends[1:], strict=True):
        assert spans[cur][0] == prev + pd.Timedelta(days=1)


def test_aggregate_over_modes():
    idx = pd.date_range("2020-01-31", periods=3, freq="ME")
    s = pd.Series([1.0, 2.0, 3.0], index=idx)
    start, end = pd.Timestamp("2020-01-01"), pd.Timestamp("2020-03-31")
    assert aggregate_over(s, start, end, how="mean") == 2.0
    assert aggregate_over(s, start, end, how="sum") == 6.0
    assert aggregate_over(s, start, end, how="last") == 3.0


def test_bridge_recovers_relationship():
    ind = _monthly_indicator()
    target = _quarterly_target(ind, beta=2.0, const=5.0)
    model = BridgeModel(indicators=["ind"]).fit(target, {"ind": ind})
    assert model.params["ind"] == pytest.approx(2.0, abs=0.2)
    assert model.nobs > 30


def test_ragged_edge_partial_period_predicts():
    ind = _monthly_indicator()
    target = _quarterly_target(ind)
    model = BridgeModel(indicators=["ind"]).fit(target, {"ind": ind})
    # Predict a quarter using only its first month (ragged edge) -> still returns a value.
    start = pd.Timestamp("2010-01-01")
    partial = {"ind": ind[ind.index <= pd.Timestamp("2010-01-31")]}
    value, se, n = model.predict_period(partial, start, pd.Timestamp("2010-03-31"))
    assert n == 1
    assert np.isfinite(value)


def test_accuracy_improves_with_information():
    ind = _monthly_indicator(within_q_trend=8.0)  # strong within-quarter drift
    target = _quarterly_target(ind)
    model = BridgeModel(indicators=["ind"]).fit(target, {"ind": ind})
    acc = accuracy_vs_information(model, target, {"ind": ind}, step_days=15, max_days=100)
    acc = acc.dropna(subset=["mae"])
    early = acc[acc["days_into_period"] <= 30]["mae"].mean()
    late = acc[acc["days_into_period"] >= 90]["mae"].mean()
    assert late <= early  # more of the period observed -> at least as accurate


def test_beats_naive_benchmark():
    ind = _monthly_indicator()
    target = _quarterly_target(ind)
    model = BridgeModel(indicators=["ind"]).fit(target, {"ind": ind})
    cmp = benchmark_comparison(model, target, {"ind": ind}, days_into_period=95)
    # With the full quarter's indicator, the bridge should beat last-value RW.
    assert cmp["nowcast"].iloc[0] < cmp["last_value"].iloc[0]


def test_vintage_record_roundtrip(tmp_path):
    p = tmp_path / "v.jsonl"
    record(NowcastVintage(target_id="t", target_period=date(2020, 3, 31),
                          as_of=date(2020, 2, 15), value=1.0, se=0.1, n_inputs=1), p)
    record(NowcastVintage(target_id="t", target_period=date(2020, 3, 31),
                          as_of=date(2020, 3, 15), value=1.2, se=0.08, n_inputs=2), p)
    df = read_all(p)
    assert len(df) == 2  # append-only: both revisions kept
    assert set(df["as_of"]) == {date(2020, 2, 15), date(2020, 3, 15)}
