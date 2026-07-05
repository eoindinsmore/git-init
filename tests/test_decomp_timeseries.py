"""Tests for quant.decomp.contribution_timeseries — the stacked-area companion.

Two invariants make it trustworthy: (1) with log returns the cumulative bands offset by
`level_start` reconstruct the log-price path exactly; (2) summed over the window the
per-period contributions equal the single-window `decompose()` contributions — the two
views of the same fit cannot disagree.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.decomp import core


def _levels_from_returns(rets: np.ndarray, start=100.0, index=None) -> pd.Series:
    levels = start * np.exp(np.cumsum(rets))
    return pd.Series(levels, index=index)


def _synthetic(n=260, seed=7):
    idx = pd.date_range("2018-01-07", periods=n, freq="W")
    rng = np.random.default_rng(seed)
    d1 = pd.Series(rng.normal(scale=0.02, size=n), index=idx)
    d2 = pd.Series(rng.normal(scale=0.02, size=n), index=idx)
    noise = pd.Series(rng.normal(scale=0.005, size=n), index=idx)
    y_ret = 1.5 * d1 + (-0.5) * d2 + noise
    target = _levels_from_returns(y_ret.to_numpy(), index=idx)
    drivers = {
        "d1": _levels_from_returns(d1.to_numpy(), index=idx),
        "d2": _levels_from_returns(d2.to_numpy(), index=idx),
    }
    return target, drivers


def test_log_reconstruction_is_exact():
    target, drivers = _synthetic()
    cs = core.contribution_timeseries(
        target, drivers, order=["d1", "d2"], frequency="W", est_window=200
    )
    assert cs.additive_exact is True
    # Cumulative bands offset by level_start sit exactly on the actual log-price path.
    diff = (cs.reconstructed - cs.actual).abs().max()
    assert diff == pytest.approx(0.0, abs=1e-9)
    # Every period's columns sum to the target return (residual closes the identity).
    row_sum = cs.increments.sum(axis=1)
    y = np.log(target.resample("W").last()).diff().reindex(cs.increments.index)
    assert (row_sum - y).abs().max() == pytest.approx(0.0, abs=1e-9)


def test_reconciles_with_single_window_decompose():
    target, drivers = _synthetic()
    kw = dict(order=["d1", "d2"], frequency="W", est_window=200)
    res = core.decompose(target, drivers, **kw)
    cs = core.contribution_timeseries(target, drivers, **kw)
    # Summed increments equal the single-window contributions, column for column.
    summed = cs.increments.sum(axis=0)
    for col in [core.DRIFT, "d1", "d2", core.RESIDUAL]:
        assert summed[col] == pytest.approx(res.contributions[col], abs=1e-9)
    # And the reconstructed total change matches decompose()'s `actual`.
    total = float(cs.reconstructed.iloc[-1] - cs.level_start)
    assert total == pytest.approx(res.actual, abs=1e-9)


def test_pct_is_flagged_approximate():
    target, drivers = _synthetic()
    cs = core.contribution_timeseries(
        target, drivers, order=["d1", "d2"], frequency="W", est_window=200, return_kind="pct"
    )
    assert cs.additive_exact is False


def test_rejects_too_few_observations():
    idx = pd.date_range("2020-01-05", periods=3, freq="W")
    target = pd.Series(np.linspace(100, 105, 3), index=idx)
    drivers = {"d1": pd.Series(np.linspace(10, 12, 3), index=idx)}
    with pytest.raises(ValueError, match="not enough overlapping"):
        core.contribution_timeseries(target, drivers, order=["d1"], frequency="W", est_window=200)


def test_rejects_empty_window():
    target, drivers = _synthetic()
    with pytest.raises(ValueError, match="no observations"):
        core.contribution_timeseries(
            target, drivers, order=["d1", "d2"], frequency="W", est_window=200,
            window=("1990-01-01", "1990-02-01"),
        )


def test_rolling_betas_not_yet_supported():
    target, drivers = _synthetic()
    with pytest.raises(ValueError, match="rolling"):
        core.contribution_timeseries(
            target, drivers, order=["d1", "d2"], frequency="W", est_window=200, betas="rolling"
        )
