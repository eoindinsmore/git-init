"""CFTC COT adapter tests — offline, against the captured Socrata payload."""

from __future__ import annotations

import pandas as pd
import pytest

from adapters.base import AdapterError
from adapters.cftc import CftcAdapter
from registry.schema import Category, Frequency, SAStatus, SeriesSpec, Tags

SPEC = SeriesSpec(
    series_id="copper_cot_mm_long",
    source="cftc",
    source_code="m_money_positions_long_all",
    name="COMEX Copper COT — managed money long",
    unit="contracts",
    frequency=Frequency.W,
    sa_status=SAStatus.NSA,
    tags=Tags(metal="copper", country="US", category=Category.POSITIONING),
    source_params={"market": "COPPER%"},
)
REGISTRY = {SPEC.series_id: SPEC}


def _a() -> CftcAdapter:
    return CftcAdapter(registry=REGISTRY)


def test_parse_publication_lag(cftc_raw):
    df = _a().parse(SPEC, cftc_raw)
    assert list(df.columns) == ["date", "value", "as_of", "last_updated"]
    assert len(df) > 0
    # as_of is the Friday publication date = Tuesday report + 3 days (no lookahead)
    assert (pd.to_datetime(df["as_of"]) - pd.to_datetime(df["date"]) == pd.Timedelta(days=3)).all()
    assert df["value"].notna().all()


def test_run_writes_and_pit(tmp_path, cftc_raw, monkeypatch):
    facts = tmp_path / "facts.parquet"
    a = _a()
    monkeypatch.setattr(a, "fetch_raw", lambda spec: cftc_raw)
    n = a.run("copper_cot_mm_long", path=facts)
    assert n > 0

    from quant import store
    # a backtest on the Tuesday report date must NOT yet see the value (published Fri)
    df = _a().parse(SPEC, cftc_raw)
    a_report_date = pd.to_datetime(df["date"]).max()
    seen_on_report_day = store.get_series("copper_cot_mm_long", as_of=a_report_date, path=facts)
    seen_3d_later = store.get_series(
        "copper_cot_mm_long", as_of=a_report_date + pd.Timedelta(days=3), path=facts
    )
    # latest report only becomes visible after its publication date
    assert len(seen_3d_later) > len(seen_on_report_day)

    assert a.run("copper_cot_mm_long", path=facts) == 0  # idempotent


def test_missing_field_fails_loudly(cftc_raw):
    spec = SPEC.model_copy(update={"source_code": "no_such_field"})
    a = CftcAdapter(registry={spec.series_id: spec})
    with pytest.raises(AdapterError, match="not present in any row"):
        a.parse(spec, cftc_raw)


def test_non_list_fails_loudly():
    with pytest.raises(AdapterError, match="expected a JSON list"):
        _a().parse(SPEC, {"error": "bad query"})


def test_fetch_requires_market():
    spec = SPEC.model_copy(update={"source_params": {}})
    a = CftcAdapter(registry={spec.series_id: spec})
    with pytest.raises(AdapterError, match="needs a 'market'"):
        a.fetch_raw(spec)
