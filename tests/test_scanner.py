"""Tests for quant.scanner — z-scores, derived items, Mahalanobis, tracker hook."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from quant.scanner import build_derived, load_named, promote_flag, scan, zscore_series
from quant.scanner.spec import DerivedItem
from tracker import store as tracker_store


def _daily(vals, start="2020-01-01"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="D"))


def test_zscore_spike_is_large():
    rng = np.random.default_rng(0)
    base = list(rng.normal(scale=1.0, size=100))
    base[-1] = 10.0  # a big outlier at the end
    z = zscore_series(_daily(base), window=60)
    assert z.iloc[-1] > 5


def test_scan_ranks_outlier_first():
    rng = np.random.default_rng(1)
    calm = _daily(list(rng.normal(scale=1.0, size=120)))
    spiky = _daily(list(rng.normal(scale=1.0, size=119)) + [12.0])
    res = scan({"calm": calm, "spiky": spiky}, windows=[20, 60], z_threshold=2.0)
    assert res.table.iloc[0]["item"] == "spiky"
    assert bool(res.table.iloc[0]["flag"])


def test_build_derived_ratio_and_spread():
    a = _daily([2.0, 4.0, 6.0])
    b = _daily([1.0, 2.0, 3.0])
    derived = [
        DerivedItem(id="r", kind="ratio", legs=["a", "b"]),
        DerivedItem(id="s", kind="spread", legs=["a", "b"]),
    ]
    out = build_derived({"a": a, "b": b}, derived)
    assert out["r"].iloc[-1] == 2.0
    assert out["s"].iloc[-1] == 3.0


def test_mahalanobis_flags_joint_move():
    rng = np.random.default_rng(2)
    n = 200
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    # Returns that co-move tightly (corr ~1); the LAST step breaks the relationship:
    # a moves +10% while b stays flat -> off the historical correlation line.
    ra = rng.normal(scale=0.01, size=n)
    rb = ra + rng.normal(scale=0.0005, size=n)
    ra[-1], rb[-1] = 0.10, 0.0
    a = pd.Series(100 * np.exp(np.cumsum(ra)), index=idx)
    b = pd.Series(100 * np.exp(np.cumsum(rb)), index=idx)
    res = scan({"a": a, "b": b}, windows=[20, 60], mahalanobis_set=["a", "b"])
    assert res.mahalanobis is not None
    assert res.mahalanobis > 5  # a large joint dislocation
    assert res.mahalanobis_pvalue < 0.01


def test_promote_flag_creates_draft(tmp_path):
    rng = np.random.default_rng(3)
    spiky = _daily(list(rng.normal(scale=1.0, size=119)) + [12.0])
    res = scan({"spiky": spiky}, windows=[20, 60], z_threshold=2.0)
    p = tmp_path / "hyp.jsonl"
    h = promote_flag(res, "spiky", created_as_of=datetime(2026, 7, 5), path=p)
    assert h.source == "scanner"
    assert h.instrument == "spiky"
    assert h.status.value == "draft"
    assert h.direction.value == "undecided"  # analyst decides
    assert tracker_store.read_all(p)[0].hypothesis_id == h.hypothesis_id


def test_shipped_universe_loads():
    spec = load_named("base")
    assert spec.name == "base"
    assert "copper_cot_mm_net" in [d.id for d in spec.derived]
    assert spec.mahalanobis_set


def test_mahalanobis_timeseries_flags_a_joint_spike():
    import numpy as np
    import pandas as pd

    from quant.scanner.core import mahalanobis_timeseries

    idx = pd.date_range("2018-01-01", periods=160, freq="W")
    rng = np.random.default_rng(0)
    a = pd.Series(100 + np.cumsum(rng.normal(scale=1.0, size=160)), index=idx)
    b = pd.Series(100 + np.cumsum(rng.normal(scale=1.0, size=160)), index=idx)
    # Inject a large joint move at the last observation.
    a.iloc[-1] += 25
    b.iloc[-1] -= 25
    ts = mahalanobis_timeseries({"a": a, "b": b}, ["a", "b"], window=104)
    assert not ts.empty
    assert (ts >= 0).all()
    # The injected spike should be the largest distance in the series.
    assert ts.idxmax() == idx[-1]


def test_mahalanobis_timeseries_empty_when_too_few_series():
    import pandas as pd

    from quant.scanner.core import mahalanobis_timeseries

    idx = pd.date_range("2020-01-01", periods=120, freq="W")
    s = pd.Series(range(120), index=idx)
    assert mahalanobis_timeseries({"a": s}, ["a"], window=104).empty
