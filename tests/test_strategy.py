"""Tests for models.strategy — the regression backtest + regime filter (Workbench step 5).

Synthetic data with a genuinely predictable component lets the sign-following strategy
show positive expectancy; the regime filter is checked to actually flatten the book.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from models import strategy


def _levels_from_returns(rets, start=100.0, index=None):
    return pd.Series(start * np.exp(np.cumsum(rets)), index=index)


def _predictable(n=360, seed=1):
    """A target whose return is a persistent function of a lagged driver (learnable)."""
    idx = pd.date_range("2015-01-01", periods=n, freq="W")
    rng = np.random.default_rng(seed)
    x = pd.Series(rng.normal(scale=0.02, size=n), index=idx)
    noise = pd.Series(rng.normal(scale=0.003, size=n), index=idx)
    y = 0.8 * x + noise  # contemporaneous, strong relationship
    target = _levels_from_returns(y.to_numpy(), index=idx)
    drivers = {"x": _levels_from_returns(x.to_numpy(), index=idx)}
    return target, drivers, idx


def test_backtest_runs_and_reports_stats():
    target, drivers, _ = _predictable()
    res = strategy.backtest_regression(
        target, drivers, order=["x"], min_train=150, driver_assumption="momentum"
    )
    assert res.n > 0
    assert 0.0 <= res.hit_rate <= 1.0
    assert len(res.equity) == res.n
    assert not res.regime_filtered


def test_regime_filter_flattens_the_book():
    target, drivers, idx = _predictable()
    # A regime series that is "risk_on" for the first half, "risk_off" for the second.
    regime = pd.Series(["risk_on"] * (len(idx) // 2) + ["risk_off"] * (len(idx) - len(idx) // 2),
                       index=idx)
    unfiltered = strategy.backtest_regression(target, drivers, order=["x"], min_train=150)
    filtered = strategy.backtest_regression(
        target, drivers, order=["x"], min_train=150,
        regimes=regime, allowed_regimes=["risk_on"],
    )
    assert filtered.regime_filtered is True
    # Filtering to one regime must not increase time in the market.
    assert filtered.periods_in_market <= unfiltered.periods_in_market
    # And it should genuinely sit out some periods here.
    assert filtered.periods_in_market < unfiltered.periods_in_market


def test_costs_reduce_return():
    target, drivers, _ = _predictable()
    cheap = strategy.backtest_regression(target, drivers, order=["x"], min_train=150, cost_bps=0.0)
    dear = strategy.backtest_regression(target, drivers, order=["x"], min_train=150, cost_bps=100.0)
    assert dear.cumulative_return < cheap.cumulative_return
