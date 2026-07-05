"""Tests for models.forecast / models.evaluate — the short-term forecast platform.

Synthetic data with a known drift and known betas gives checkable answers. The honesty
properties (interval widens with √k; hold_last is drift-only; scenario needs paths) are
asserted directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import models.evaluate as evaluate
import models.forecast as forecast


def _levels_from_returns(rets, start=100.0, index=None):
    return pd.Series(start * np.exp(np.cumsum(rets)), index=index)


def _synthetic(n=300, seed=3, drift=0.0):
    idx = pd.date_range("2017-01-01", periods=n, freq="W")
    rng = np.random.default_rng(seed)
    d1 = pd.Series(rng.normal(scale=0.02, size=n), index=idx)
    d2 = pd.Series(rng.normal(scale=0.02, size=n), index=idx)
    noise = pd.Series(rng.normal(scale=0.004, size=n), index=idx)
    y = drift + 1.2 * d1 - 0.4 * d2 + noise
    target = _levels_from_returns(y.to_numpy(), index=idx)
    drivers = {"d1": _levels_from_returns(d1.to_numpy(), index=idx),
               "d2": _levels_from_returns(d2.to_numpy(), index=idx)}
    return target, drivers


def test_hold_last_is_flat_when_drift_is_zero():
    target, drivers = _synthetic(drift=0.0, seed=11)
    fc = forecast.forecast(target, drivers, order=["d1", "d2"], horizon_periods=8)
    # Near-zero drift → point path hugs the last level (within a small band).
    assert abs(fc.expected_period_return) < 5e-3
    assert fc.path["point"].iloc[0] == pytest.approx(fc.last_level, rel=0.05)
    assert fc.driver_assumption == forecast.HOLD_LAST


def test_positive_drift_trends_up():
    target, drivers = _synthetic(drift=0.01, seed=5)
    fc = forecast.forecast(target, drivers, order=["d1", "d2"], horizon_periods=12)
    assert fc.expected_period_return > 0
    assert fc.path["point"].iloc[-1] > fc.path["point"].iloc[0] > 0


def test_interval_widens_with_horizon():
    target, drivers = _synthetic(seed=7)
    fc = forecast.forecast(target, drivers, order=["d1", "d2"], horizon_periods=10, conf=0.8)
    half = (fc.path["hi"] - fc.path["lo"]) / 2.0
    # Strictly increasing band half-width.
    assert (half.diff().dropna() > 0).all()


def test_scenario_requires_paths():
    target, drivers = _synthetic()
    with pytest.raises(ValueError, match="scenario"):
        forecast.forecast(target, drivers, order=["d1", "d2"], horizon_periods=4,
                          driver_assumption="scenario")


def test_scenario_moves_with_assumed_driver_path():
    target, drivers = _synthetic(seed=9)
    up = forecast.forecast(target, drivers, order=["d1", "d2"], horizon_periods=6,
                           driver_assumption="scenario", driver_paths={"d1": 0.01, "d2": 0.0})
    flat = forecast.forecast(target, drivers, order=["d1", "d2"], horizon_periods=6,
                             driver_assumption="hold_last")
    # d1 has a positive beta, so a positive d1 path lifts the forecast above drift-only.
    assert up.path["point"].iloc[-1] > flat.path["point"].iloc[-1]


def test_rejects_bad_horizon():
    target, drivers = _synthetic()
    with pytest.raises(ValueError, match="horizon"):
        forecast.forecast(target, drivers, order=["d1", "d2"], horizon_periods=0)


def test_walk_forward_skill_runs_and_reports_n():
    target, drivers = _synthetic(seed=2)
    out = evaluate.walk_forward_skill(target, drivers, order=["d1", "d2"], min_train=150)
    assert out["n"] > 0
    assert np.isfinite(out["oos_r2_vs_rw"])
    # A pure-noise-drift target should not meaningfully beat the random walk.
    assert out["oos_r2_vs_rw"] < 0.5


def test_scenario_not_evaluable():
    target, drivers = _synthetic()
    with pytest.raises(ValueError, match="evaluable"):
        evaluate.walk_forward_skill(target, drivers, order=["d1"], driver_assumption="scenario")
