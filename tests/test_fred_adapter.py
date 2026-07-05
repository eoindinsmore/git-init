"""FRED adapter tests — offline, against the real captured payload.

No network: fetch_raw is stubbed to return the harvested fixture, so these
exercise parse → validate → store exactly as a live run would.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from adapters.base import AdapterError
from adapters.fred import FredAdapter
from quant import store
from registry.schema import Category, Frequency, SAStatus, SeriesSpec, Tags

SPEC = SeriesSpec(
    series_id="us_industrial_production",
    source="fred",
    source_code="INDPRO",
    name="US Industrial Production: Total Index",
    unit="Index 2017=100",
    frequency=Frequency.M,
    sa_status=SAStatus.SA,
    tags=Tags(country="US", category=Category.ACTIVITY),
)
REGISTRY = {SPEC.series_id: SPEC}


def _adapter() -> FredAdapter:
    # api_key set so fetch_raw wouldn't error if called; we stub it anyway.
    return FredAdapter(registry=REGISTRY, api_key="test-key")


def test_parse_shape_and_pit(fred_raw):
    df = _adapter().parse(SPEC, fred_raw)
    assert list(df.columns) == ["date", "value", "as_of", "last_updated"]
    assert len(df) > 0
    # every observation carries an as_of vintage (point-in-time discipline)
    assert df["as_of"].notna().all()
    # first row matches the known fixture head
    df["date"] = pd.to_datetime(df["date"])
    first = df.sort_values("date").iloc[0]
    assert str(first["date"].date()) == "2015-01-01"
    assert float(first["value"]) == pytest.approx(102.8905)


def test_run_writes_to_store(tmp_path, fred_raw, monkeypatch):
    facts = tmp_path / "facts.parquet"
    a = _adapter()
    monkeypatch.setattr(a, "fetch_raw", lambda spec: fred_raw)

    written = a.run("us_industrial_production", path=facts)
    assert written > 0

    # enriched identity columns come from the registry spec
    all_facts = store.read_facts(facts)
    assert set(all_facts["series_id"]) == {"us_industrial_production"}
    assert set(all_facts["unit"]) == {"Index 2017=100"}
    assert set(all_facts["frequency"]) == {"M"}

    # re-run is idempotent (append-only, no duplicate vintages)
    assert a.run("us_industrial_production", path=facts) == 0

    # point-in-time retrieval returns the series
    s = store.get_series("us_industrial_production", path=facts)
    assert len(s) == written
    assert s["date"].is_monotonic_increasing


def test_missing_value_dot_dropped(fred_raw):
    # inject a FRED "." missing value; it must not become a stored observation
    raw = {"observations": dict(fred_raw["observations"]), "meta": fred_raw["meta"]}
    obs = list(raw["observations"]["observations"])
    obs.append({"realtime_start": "2026-06-15", "realtime_end": "2026-06-15",
                "date": "2026-06-01", "value": "."})
    raw["observations"] = {**raw["observations"], "observations": obs}
    df = _adapter().parse(SPEC, raw)
    enriched = _adapter()._validate_and_enrich(SPEC, df)
    assert "2026-06-01" not in set(enriched["date"].astype(str).str[:10])


def test_layout_change_fails_loudly():
    # payload without 'observations' key -> loud failure, never silent
    with pytest.raises(AdapterError, match="no 'observations'"):
        _adapter().parse(SPEC, {"observations": {"unexpected": "shape"}})


def test_empty_after_parse_fails_loudly():
    raw = {"observations": {"observations": [
        {"realtime_start": "2026-06-15", "date": "2026-06-01", "value": "."},
    ]}}
    with pytest.raises(AdapterError, match="zero usable observations"):
        a = _adapter()
        a._validate_and_enrich(SPEC, a.parse(SPEC, raw))


def test_unknown_series_fails_loudly():
    with pytest.raises(AdapterError, match="not declared in the registry"):
        _adapter().run("nonexistent_series", path=Path("unused.parquet"))
