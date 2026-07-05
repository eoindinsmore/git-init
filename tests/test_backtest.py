"""Tests for quant.backtest — forecast capping, vol targeting, no look-ahead, stats."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant.backtest import backtest, capped_forecast, vol_target_position
from quant.indicators import run_lab
from quant.indicators.lab import LabConfig


def _daily(n, seed=0):
    idx = pd.date_range("2015-01-01", periods=n, freq="D")
    return idx, np.random.default_rng(seed)


def test_capped_forecast_respects_cap():
    idx, rng = _daily(300)
    s = pd.Series(rng.normal(size=300), index=idx)
    s.iloc[-1] = 100.0  # extreme
    fc = capped_forecast(s, window=60, cap=2.0)
    assert fc.dropna().abs().max() <= 2.0 + 1e-9


def test_vol_target_scales_inversely_with_vol():
    idx, rng = _daily(400)
    calm = pd.Series(rng.normal(scale=0.005, size=400), index=idx)
    wild = pd.Series(rng.normal(scale=0.05, size=400), index=idx)
    fc = pd.Series(1.0, index=idx)
    pos_calm = vol_target_position(fc, calm, target_vol=0.01, vol_window=60).dropna()
    pos_wild = vol_target_position(fc, wild, target_vol=0.01, vol_window=60).dropna()
    # Lower-vol instrument gets a larger position for the same forecast.
    assert pos_calm.abs().mean() > pos_wild.abs().mean()


def test_profitable_signal_has_positive_sharpe():
    idx, rng = _daily(600, seed=1)
    ret = pd.Series(rng.normal(scale=0.01, size=600), index=idx)
    # A signal that is tomorrow's return direction (persisted) -> should make money.
    signal = ret.shift(-1).rolling(5).mean().fillna(0.0)
    res = backtest(signal, ret, forecast_window=60, vol_window=60, cost_bps=1.0)
    assert res.metrics["sharpe_ann"] > 0
    assert res.metrics["n_obs"] > 400


def test_no_lookahead_future_returns_dont_change_past_pnl():
    idx, rng = _daily(500, seed=2)
    ret = pd.Series(rng.normal(scale=0.01, size=500), index=idx)
    signal = pd.Series(rng.normal(size=500), index=idx)
    full = backtest(signal, ret, forecast_window=60, vol_window=60, cost_bps=5.0)
    # Truncate the future; P&L on shared dates must be unchanged.
    trunc = backtest(signal.iloc[:400], ret.iloc[:400], forecast_window=60,
                     vol_window=60, cost_bps=5.0)
    common = full.net.index.intersection(trunc.net.index)
    assert len(common) > 100
    assert np.allclose(full.net.loc[common].to_numpy(), trunc.net.loc[common].to_numpy())


def test_costs_reduce_pnl():
    idx, rng = _daily(500, seed=3)
    ret = pd.Series(rng.normal(scale=0.01, size=500), index=idx)
    signal = pd.Series(rng.normal(size=500), index=idx)
    cheap = backtest(signal, ret, forecast_window=60, vol_window=60, cost_bps=0.0)
    dear = backtest(signal, ret, forecast_window=60, vol_window=60, cost_bps=100.0)
    assert dear.net.sum() < cheap.net.sum()


def test_deflated_sharpe_in_metrics_and_falls_with_variants():
    idx, rng = _daily(600, seed=4)
    ret = pd.Series(rng.normal(scale=0.01, size=600), index=idx)
    signal = ret.shift(-1).rolling(5).mean().fillna(0.0)
    few = backtest(signal, ret, forecast_window=60, vol_window=60, n_variants_tried=1)
    many = backtest(signal, ret, forecast_window=60, vol_window=60, n_variants_tried=500)
    assert "deflated_sharpe" in few.metrics
    assert few.metrics["deflated_sharpe"] >= many.metrics["deflated_sharpe"]


def test_indicator_lab_backtester_retrofit_runs():
    # Gate 4 via the real backtester still promotes a genuine leader.
    rng = np.random.default_rng(5)
    idx = pd.date_range("2000-01-31", periods=300, freq="ME")
    cand = pd.Series(rng.normal(size=300), index=idx)
    target = 0.9 * cand.shift(2) + pd.Series(rng.normal(scale=0.25, size=300), index=idx)
    cfg = LabConfig(max_lag=4, min_train=40, stability_window=40, use_backtester=True,
                    min_sharpe=-99)  # threshold loose: we only assert it runs + promotes
    evals = run_lab("target", target, {"leader": cand}, config=cfg)
    ev = evals[0]
    assert ev.gates["economic"].detail.get("engine") == "backtester"
    assert ev.promoted
