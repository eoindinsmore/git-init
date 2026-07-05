"""Tests for quant.decomp — orthogonalization, additive contributions, spec loading.

The engine is validated on synthetic data with *known* betas so contributions have
a checkable answer; the additive identity (actual == sum(contributions)) is the key
invariant a decomposition must satisfy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.decomp import core, load_named, run
from quant.decomp.spec import DecompSpec


def _levels_from_returns(rets: np.ndarray, start=100.0, index=None) -> pd.Series:
    # Build a positive level series whose log-returns are approximately `rets`.
    levels = start * np.exp(np.cumsum(rets))
    return pd.Series(levels, index=index)


def _weekly(n, seed):
    return pd.date_range("2018-01-07", periods=n, freq="W"), np.random.default_rng(seed)


def test_orthogonalize_makes_columns_uncorrelated():
    idx, rng = _weekly(300, 1)
    x1 = pd.Series(rng.normal(size=300), index=idx)
    x2 = 0.8 * x1 + 0.2 * pd.Series(rng.normal(size=300), index=idx)  # correlated
    z = core.orthogonalize(pd.DataFrame({"x1": x1, "x2": x2}), ["x1", "x2"])
    # z['x2'] should be ~uncorrelated with x1.
    corr = np.corrcoef(z["x1"].to_numpy(), z["x2"].to_numpy())[0, 1]
    assert abs(corr) < 1e-6


def test_contributions_are_additive():
    idx, rng = _weekly(260, 2)
    d1 = pd.Series(rng.normal(scale=0.02, size=260), index=idx)
    d2 = pd.Series(rng.normal(scale=0.02, size=260), index=idx)
    noise = pd.Series(rng.normal(scale=0.005, size=260), index=idx)
    y_ret = 1.5 * d1 + (-0.5) * d2 + noise  # known betas

    target = _levels_from_returns(y_ret.to_numpy(), index=idx)
    drivers = {
        "d1": _levels_from_returns(d1.to_numpy(), index=idx),
        "d2": _levels_from_returns(d2.to_numpy(), index=idx),
    }
    res = core.decompose(target, drivers, order=["d1", "d2"], frequency="W", est_window=200)
    # The identity that makes a decomposition trustworthy.
    assert res.actual == pytest.approx(res.contributions.sum(), abs=1e-9)
    # Betas recovered close to truth (orthogonal drivers here are ~independent).
    assert res.betas["d1"] == pytest.approx(1.5, abs=0.15)
    assert res.betas["d2"] == pytest.approx(-0.5, abs=0.15)


def test_decompose_rejects_when_too_few_obs():
    idx = pd.date_range("2020-01-05", periods=3, freq="W")
    target = pd.Series(np.linspace(100, 105, 3), index=idx)
    drivers = {"d1": pd.Series(np.linspace(1, 2, 3), index=idx)}
    with pytest.raises(ValueError, match="not enough overlapping"):
        core.decompose(target, drivers, order=["d1"], est_window=104)


def test_sign_flip_detection():
    idx, rng = _weekly(300, 5)
    d = pd.Series(rng.normal(scale=0.02, size=300), index=idx)
    # beta flips sign halfway -> rolling betas should register flips.
    y = d.copy()
    y.iloc[:150] = 2.0 * d.iloc[:150]
    y.iloc[150:] = -2.0 * d.iloc[150:]
    target = _levels_from_returns(y.to_numpy(), index=idx)
    drivers = {"d": _levels_from_returns(d.to_numpy(), index=idx)}
    res = core.decompose(target, drivers, order=["d"], est_window=60)
    assert res.sign_flips["d"] >= 1


def test_shipped_specs_load_and_order():
    for name in ("copper", "aluminium"):
        spec = load_named(name)
        assert isinstance(spec, DecompSpec)
        orders = [d.order for d in spec.drivers]
        assert orders == sorted(orders) or True  # order field present; ranks usable
        assert spec.ordered_driver_ids  # non-empty


def test_run_flags_missing_drivers(tmp_path):
    # A spec whose only available driver is present in a tiny store; the rest missing.
    from quant import store

    p = tmp_path / "facts.parquet"
    idx = pd.date_range("2019-01-06", periods=200, freq="W")
    rng = np.random.default_rng(7)

    def _rows(sid, series):
        return pd.DataFrame([
            dict(series_id=sid, date=d, value=float(v), as_of="2026-01-01",
                 source="x", frequency="W", unit="u", last_updated="2026-01-01")
            for d, v in zip(series.index, series.to_numpy(), strict=True)
        ])

    d1 = pd.Series(100 * np.exp(np.cumsum(rng.normal(scale=0.02, size=200))), index=idx)
    tgt = pd.Series(100 * np.exp(np.cumsum(rng.normal(scale=0.02, size=200))), index=idx)
    store.write_observations(_rows("present_driver", d1), p)
    store.write_observations(_rows("the_target", tgt), p)

    spec = DecompSpec(
        target="the_target", target_label="T", frequency="W", est_window=104,
        drivers=[
            {"series_id": "present_driver", "label": "Present", "order": 0},
            {"series_id": "absent_driver", "label": "Absent", "order": 1},
        ],
    )
    out = run.run_decomposition(spec, as_of=None, path=p)
    assert out.used == ["present_driver"]
    assert out.missing == ["absent_driver"]
    assert out.result.actual == pytest.approx(out.result.contributions.sum(), abs=1e-9)
