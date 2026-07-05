"""Eurostat adapter tests — offline, against the captured JSON-stat payload."""

from __future__ import annotations

import pandas as pd
import pytest

from adapters.base import AdapterError
from adapters.eurostat import EurostatAdapter
from registry.schema import Category, Frequency, SAStatus, SeriesSpec, Tags

SPEC = SeriesSpec(
    series_id="de_industrial_production",
    source="eurostat",
    source_code="sts_inpr_m",
    name="Germany Industrial Production (B-D, SCA)",
    unit="Index 2021=100",
    frequency=Frequency.M,
    sa_status=SAStatus.SA,
    tags=Tags(country="DE", category=Category.ACTIVITY),
    source_params={"geo": "DE", "nace_r2": "B-D", "s_adj": "SCA", "unit": "I21"},
)
REGISTRY = {SPEC.series_id: SPEC}


def _a() -> EurostatAdapter:
    return EurostatAdapter(registry=REGISTRY)


def test_parse_shape_and_dates(eurostat_raw):
    df = _a().parse(SPEC, eurostat_raw)
    assert list(df.columns) == ["date", "value", "as_of", "last_updated"]
    assert len(df) > 0
    assert df["as_of"].notna().all()  # dataset 'updated' fills as_of
    df["date"] = pd.to_datetime(df["date"])
    first = df.sort_values("date").iloc[0]
    assert str(first["date"].date()) == "2022-01-01"


def test_run_writes(tmp_path, eurostat_raw, monkeypatch):
    facts = tmp_path / "facts.parquet"
    a = _a()
    monkeypatch.setattr(a, "fetch_raw", lambda spec: eurostat_raw)
    n = a.run("de_industrial_production", path=facts)
    assert n > 0
    from quant import store
    s = store.get_series("de_industrial_production", path=facts)
    assert len(s) == n
    assert a.run("de_industrial_production", path=facts) == 0  # idempotent


def test_multi_category_fails_loudly(eurostat_raw):
    # tamper: pretend the geo dimension has 2 categories -> must fail, not collapse
    raw = dict(eurostat_raw)
    raw["size"] = list(raw["size"])
    geo_pos = raw["id"].index("geo")
    raw["size"][geo_pos] = 2
    with pytest.raises(AdapterError, match="single series"):
        _a().parse(SPEC, raw)


def test_layout_change_fails_loudly():
    with pytest.raises(AdapterError, match="missing JSON-stat key"):
        _a().parse(SPEC, {"not": "jsonstat"})
