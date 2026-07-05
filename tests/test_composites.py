"""Tests for quant.composites — diffusion, z-score, and point-in-time PCA.

The headline invariant: the PIT PCA composite has **no look-ahead** — the score on a
date is identical whether or not later data exists in the panel (loadings at t use
only history up to t).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from quant.composites import (
    build_composite,
    diffusion_index,
    pit_pca_first_component,
    zscore_composite,
)
from quant.composites.spec import CompositeSpec


def _factor_panel(n=160, k=3, seed=0):
    """A panel of k series sharing a common factor plus idiosyncratic noise."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2005-01-31", periods=n, freq="ME")
    factor = np.cumsum(rng.normal(size=n))
    cols = {f"c{j}": factor + rng.normal(scale=0.5, size=n) for j in range(k)}
    return pd.DataFrame(cols, index=idx), pd.Series(factor, index=idx)


def test_diffusion_index_bounds_and_value():
    idx = pd.date_range("2020-01-31", periods=3, freq="ME")
    panel = pd.DataFrame({"a": [1.0, 2.0, 1.5], "b": [5.0, 4.0, 6.0]}, index=idx)
    di = diffusion_index(panel)
    # period 2: a up, b down -> 50%; period 3: a down, b up -> 50%.
    assert di.iloc[1] == 50.0
    assert (di.dropna() >= 0).all() and (di.dropna() <= 100).all()


def test_zscore_composite_ragged_edges():
    idx = pd.date_range("2020-01-31", periods=5, freq="ME")
    panel = pd.DataFrame(
        {"a": [1.0, 2.0, 3.0, 4.0, 5.0], "b": [10.0, 20.0, 30.0, np.nan, 50.0]}, index=idx
    )
    comp = zscore_composite(panel)  # averages available components per date
    assert comp.notna().all()
    assert len(comp) == 5  # the NaN in b doesn't drop the date (a still present)


def test_pit_pca_has_no_lookahead():
    panel, _ = _factor_panel()
    full = pit_pca_first_component(panel, reference="c0", min_window=40)
    trunc = pit_pca_first_component(panel.iloc[:90], reference="c0", min_window=40)
    common = full.index.intersection(trunc.index)
    assert len(common) > 20
    # Scores on shared dates are identical — future data cannot change a past score.
    assert np.allclose(full.loc[common].to_numpy(), trunc.loc[common].to_numpy())


def test_pit_pca_sign_fixed_to_reference():
    panel, factor = _factor_panel(seed=2)
    comp = pit_pca_first_component(panel, reference="c0", min_window=40)
    # Sign-fixed to c0 -> composite moves with the common factor (positive corr).
    aligned = pd.concat([comp.rename("comp"), factor.rename("f")], axis=1, sort=False).dropna()
    assert aligned["comp"].corr(aligned["f"]) > 0.5


def test_build_composite_makes_signal(tmp_path):
    from quant import store

    p = tmp_path / "facts.parquet"
    panel, _ = _factor_panel(seed=3)

    def _rows(sid, s):
        return pd.DataFrame([
            dict(series_id=sid, date=d, value=float(v), as_of="2026-01-01",
                 source="x", frequency="M", unit="u", last_updated="2026-01-01")
            for d, v in zip(s.index, s.to_numpy(), strict=True)
        ])

    for c in panel.columns:
        store.write_observations(_rows(c, panel[c]), p)

    spec = CompositeSpec(
        composite_id="test_comp", label="Test", method="pca", reference="c0",
        min_window=40, components=list(panel.columns), target="thing",
    )
    build = build_composite(spec, as_of=None, path=p, created_as_of=date(2026, 7, 5))
    assert build.signal.provenance == list(panel.columns)
    assert build.signal.signal_id == "test_comp"
    assert not build.missing
    assert len(build.signal.values) > 20


def test_build_composite_flags_missing(tmp_path):
    from quant import store

    p = tmp_path / "facts.parquet"
    idx = pd.date_range("2010-01-31", periods=60, freq="ME")
    s = pd.Series(np.arange(60.0), index=idx)
    store.write_observations(pd.DataFrame([
        dict(series_id="present", date=d, value=float(v), as_of="2026-01-01",
             source="x", frequency="M", unit="u", last_updated="2026-01-01")
        for d, v in zip(idx, s.to_numpy(), strict=True)
    ]), p)
    spec = CompositeSpec(composite_id="c", label="C", method="zscore",
                         components=["present", "absent"], window=24)
    build = build_composite(spec, as_of=None, path=p)
    assert build.used == ["present"]
    assert build.missing == ["absent"]
