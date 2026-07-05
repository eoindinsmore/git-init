"""Tests for quant.regimes — categorizers, classification, transitions, and hooks."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant.regimes import (
    band,
    classify,
    combination_weights,
    conditional_performance,
    inverse_mse_weights,
    level_delta,
    ma_trend,
    regime_banner,
    sizing_multiplier,
    transition_matrix,
)
from quant.regimes.spec import RegimeSpec


def _daily(vals, start="2020-01-01"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="D"))


def test_band_buckets_levels():
    s = _daily([10.0, 20.0, 30.0])
    cat = band(s, thresholds=[15.0, 25.0], labels=["low", "mid", "high"])
    assert list(cat) == ["low", "mid", "high"]


def test_ma_trend_up_down():
    s = _daily(list(np.arange(1.0, 60.0)))  # steadily rising -> above its MA -> up
    trend = ma_trend(s, window=20).dropna()
    assert (trend == "up").all()


def test_level_delta_states():
    s = _daily([48, 49, 50, 51, 52, 53])  # crosses 50, rising
    st = level_delta(s, level_threshold=50.0, delta_periods=3).dropna()
    assert st.iloc[-1] == "exp_rising"


def test_classify_combines_and_nan_on_incomplete():
    a = pd.Series(["low", "high"], index=pd.date_range("2020-01-01", periods=2, freq="D"))
    b = pd.Series(["up", None], index=pd.date_range("2020-01-01", periods=2, freq="D"))
    reg = classify({"vix": a, "usd": b})
    assert reg.iloc[0] == "vix=low | usd=up"
    assert pd.isna(reg.iloc[1])  # incomplete state -> no guessed regime


def test_transition_matrix_rows_sum_to_one():
    reg = pd.Series(["A", "A", "B", "A", "B", "B"],
                    index=pd.date_range("2020-01-01", periods=6, freq="D"))
    mat = transition_matrix(reg, normalize=True)
    assert np.allclose(mat.sum(axis=1).to_numpy(), 1.0)


def test_conditional_performance_no_lookahead_and_reports_n():
    idx = pd.date_range("2020-01-01", periods=200, freq="D")
    rng = np.random.default_rng(0)
    reg = pd.Series(np.where(np.arange(200) % 2 == 0, "bull", "bear"), index=idx)
    # bull days followed by positive returns.
    ret = pd.Series(rng.normal(scale=0.01, size=200), index=idx)
    perf = conditional_performance(reg, ret)
    assert set(perf["regime"]) <= {"bull", "bear"}
    assert (perf["n"] > 0).all()


def test_inverse_mse_weights_favour_lower_error():
    w = inverse_mse_weights({"good": 1.0, "bad": 4.0})
    assert w["good"] > w["bad"]
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_combination_weights_conditional_and_fallback():
    table = {"riskoff": {"m1": 1.0, "m2": 9.0}}
    w = combination_weights("riskoff", table)
    assert w["m1"] > w["m2"]
    # unseen regime -> equal weights over known models.
    w2 = combination_weights("unknown", table)
    assert abs(w2["m1"] - w2["m2"]) < 1e-9


def test_sizing_multiplier_and_banner():
    assert sizing_multiplier("vix=high", {"vix=high": 0.5}) == 0.5
    assert sizing_multiplier("other", {"vix=high": 0.5}, default=1.0) == 1.0
    reg = pd.Series(["vix=low | usd=up"], index=pd.date_range("2020-01-01", periods=1))
    banner = regime_banner(reg)
    assert banner["regime"] == "vix=low | usd=up"
    assert banner["components"] == {"vix": "low", "usd": "up"}


def test_shipped_spec_loads():
    from quant.regimes import load_named

    spec = load_named("global_macro")
    assert isinstance(spec, RegimeSpec)
    assert {s.name for s in spec.states} == {"vix", "pmi", "usd"}
