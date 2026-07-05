"""e-Stat adapter tests — offline, against the captured getStatsData cube."""

from __future__ import annotations

import pandas as pd
import pytest

from adapters.base import AdapterError
from adapters.estat import EstatAdapter, _time_name_to_date
from registry.schema import Category, Frequency, SAStatus, SeriesSpec, Tags

# cat02 "2021010010" = 鉄鋼・非鉄金属工業_ダイカスト (die-casting, steel/non-ferrous)
SPEC = SeriesSpec(
    series_id="jp_iip_diecast",
    source="estat",
    source_code="0004033012",
    name="Japan IIP — die-casting (steel/non-ferrous)",
    unit="Index",
    frequency=Frequency.M,
    sa_status=SAStatus.NSA,
    tags=Tags(country="JP", metal="steel", category=Category.ACTIVITY),
    selector={"cat02": "2021010010"},
)
REGISTRY = {SPEC.series_id: SPEC}


def _a() -> EstatAdapter:
    return EstatAdapter(registry=REGISTRY, app_id="test")


def test_time_decoder():
    assert _time_name_to_date("202401") == pd.Timestamp(2024, 1, 1)
    assert _time_name_to_date("2024") == pd.Timestamp(2024, 1, 1)
    assert _time_name_to_date("bogus") is None


def test_parse_single_series(estat_raw):
    df = _a().parse(SPEC, estat_raw)
    assert list(df.columns) == ["date", "value", "as_of", "last_updated"]
    assert len(df) > 0
    assert df["date"].duplicated().sum() == 0  # selector isolates one series
    assert df["as_of"].notna().all()  # UPDATED_DATE fills as_of


def test_run_writes(tmp_path, estat_raw, monkeypatch):
    facts = tmp_path / "facts.parquet"
    a = _a()
    monkeypatch.setattr(a, "fetch_raw", lambda spec: estat_raw)
    n = a.run("jp_iip_diecast", path=facts)
    assert n > 0
    assert a.run("jp_iip_diecast", path=facts) == 0  # idempotent


def test_insufficient_selector_fails_loudly(estat_raw):
    # empty selector keeps every cat02 -> duplicate dates -> loud failure
    spec = SPEC.model_copy(update={"selector": {}})
    a = EstatAdapter(registry={spec.series_id: spec}, app_id="test")
    with pytest.raises(AdapterError, match="duplicate dates"):
        a.parse(spec, estat_raw)


def test_bad_selector_dimension_fails_loudly(estat_raw):
    spec = SPEC.model_copy(update={"selector": {"nonexistent": "x"}})
    a = EstatAdapter(registry={spec.series_id: spec}, app_id="test")
    with pytest.raises(AdapterError, match="not in payload"):
        a.parse(spec, estat_raw)


def test_api_error_status_fails_loudly():
    raw = {"GET_STATS_DATA": {"RESULT": {"STATUS": 100, "ERROR_MSG": "bad appId"}}}
    with pytest.raises(AdapterError, match="API status 100"):
        _a().parse(SPEC, raw)
