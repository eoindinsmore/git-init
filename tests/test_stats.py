"""Tests for quant.stats — the shared statistics core.

Where possible we check against a construction with a known answer (e.g. an exact
linear relationship gives beta ~1, R^2 ~1) rather than hard-coding library output.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant import stats


def _idx(n, start="2015-01-01", freq="W"):
    return pd.date_range(start, periods=n, freq=freq)


def test_ols_hac_recovers_known_slope():
    n = 200
    idx = _idx(n)
    x = pd.Series(np.linspace(0, 10, n), index=idx, name="x")
    y = 2.0 + 3.0 * x + pd.Series(np.zeros(n), index=idx)  # exact
    res = stats.ols_hac(y, x)
    assert res.params["const"] == pytest.approx(2.0, abs=1e-6)
    assert res.params["x"] == pytest.approx(3.0, abs=1e-6)
    assert res.rsquared == pytest.approx(1.0, abs=1e-9)
    assert res.nobs == n


def test_ols_hac_needs_enough_obs():
    x = pd.Series([1.0, 2.0], index=_idx(2))
    y = pd.Series([1.0, 2.0], index=_idx(2))
    with pytest.raises(ValueError, match="more observations"):
        stats.ols_hac(y, x)


def test_rolling_ols_tracks_beta_shift():
    n = 120
    idx = _idx(n)
    x = pd.Series(np.random.default_rng(0).normal(size=n), index=idx)
    # beta 1 for first half, beta 5 for second half.
    y = x.copy()
    y.iloc[60:] = 5.0 * x.iloc[60:]
    betas = stats.rolling_ols(y, x, window=30)
    col = [c for c in betas.columns if c != "const"][0]
    assert betas[col].iloc[40] == pytest.approx(1.0, abs=1e-6)
    assert betas[col].iloc[-1] == pytest.approx(5.0, abs=1e-6)


def test_benjamini_hochberg_monotone_and_rejects():
    # A mix of tiny and large p-values.
    p = pd.Series({"a": 0.001, "b": 0.002, "c": 0.2, "d": 0.9, "e": 0.04})
    out = stats.benjamini_hochberg(p, q=0.10)
    # q-values are >= raw p and clipped to 1.
    assert (out["qvalue"] >= out["pvalue"] - 1e-12).all()
    assert out.loc["a", "reject"]
    assert not out.loc["d", "reject"]


def test_bh_empty_and_all_null():
    out = stats.benjamini_hochberg(pd.Series([np.nan, np.nan]), q=0.1)
    assert not out["reject"].any()


def test_campbell_thompson_sign():
    a = pd.Series([1.0, 2.0, 3.0, 4.0], index=_idx(4))
    good = a + 0.1  # close to actual
    bench = pd.Series([2.5, 2.5, 2.5, 2.5], index=_idx(4))  # flat mean
    assert stats.campbell_thompson_oos_r2(a, good, bench) > 0
    bad = a + 5.0
    assert stats.campbell_thompson_oos_r2(a, bad, bench) < 0


def test_diebold_mariano_prefers_better_forecast():
    rng = np.random.default_rng(1)
    n = 120
    idx = _idx(n)
    a = pd.Series(rng.normal(size=n), index=idx)
    f_good = a + rng.normal(scale=0.1, size=n)
    f_bad = a + rng.normal(scale=1.0, size=n)
    dm, pval = stats.diebold_mariano(a, f_good, f_bad)
    assert dm < 0  # f1 (good) has lower loss
    assert 0.0 <= pval <= 1.0


def test_block_bootstrap_pvalue_bounds():
    rng = np.random.default_rng(2)
    strong = pd.Series(rng.normal(loc=0.5, scale=0.1, size=200))
    weak = pd.Series(rng.normal(loc=-0.5, scale=0.1, size=200))
    p_strong = stats.block_bootstrap_pvalue(strong, block=10, n_boot=500, seed=3)
    assert p_strong < 0.05  # clearly positive mean
    assert stats.block_bootstrap_pvalue(weak, block=10, n_boot=500, seed=3) == 1.0


def test_deflated_sharpe_falls_with_more_trials():
    ds_few = stats.deflated_sharpe(0.15, n_obs=250, n_trials=1)
    ds_many = stats.deflated_sharpe(0.15, n_obs=250, n_trials=500)
    assert ds_few > ds_many  # more variants tried -> harder to believe
    assert 0.0 <= ds_many <= 1.0


def test_mahalanobis_zero_at_mean():
    cov = np.array([[1.0, 0.0], [0.0, 1.0]])
    mean = np.array([0.0, 0.0])
    assert stats.mahalanobis([0.0, 0.0], mean, cov) == pytest.approx(0.0)
    # 2 sigma on an independent axis -> distance 2.
    assert stats.mahalanobis([2.0, 0.0], mean, cov) == pytest.approx(2.0)


def test_walk_forward_splits_no_lookahead():
    idx = _idx(10)
    splits = list(stats.walk_forward_splits(idx, min_train=4, test_size=2, expanding=True))
    assert splits
    for train, test in splits:
        assert train.max() < test.min()  # test strictly after train
    # expanding: training set grows.
    assert len(splits[1][0]) > len(splits[0][0])


def test_walk_forward_rolling_fixed_window():
    idx = _idx(10)
    splits = list(stats.walk_forward_splits(idx, min_train=4, test_size=2, expanding=False))
    assert all(len(train) == 4 for train, _ in splits)
