"""StatCan adapter tests — offline, against the captured WDS payload."""

from __future__ import annotations

import pandas as pd
import pytest

from adapters.base import AdapterError
from adapters.statcan import StatCanAdapter
from registry.schema import Category, Frequency, SAStatus, SeriesSpec, Tags

SPEC = SeriesSpec(
    series_id="ca_placeholder_vector",
    source="statcan",
    source_code="65201210",
    name="StatCan placeholder vector",
    unit="units",
    frequency=Frequency.M,
    sa_status=SAStatus.NSA,
    tags=Tags(country="CA", category=Category.ACTIVITY),
)
REGISTRY = {SPEC.series_id: SPEC}


def _a() -> StatCanAdapter:
    return StatCanAdapter(registry=REGISTRY)


def test_parse_shape_and_pit(statcan_raw):
    df = _a().parse(SPEC, statcan_raw)
    assert list(df.columns) == ["date", "value", "as_of", "last_updated"]
    assert len(df) > 0
    # StatCan gives a genuine per-observation vintage
    assert df["as_of"].notna().all()
    df["date"] = pd.to_datetime(df["date"])
    assert df["date"].notna().all()


def test_run_writes(tmp_path, statcan_raw, monkeypatch):
    facts = tmp_path / "facts.parquet"
    a = _a()
    monkeypatch.setattr(a, "fetch_raw", lambda spec: statcan_raw)
    n = a.run("ca_placeholder_vector", path=facts)
    assert n > 0
    assert a.run("ca_placeholder_vector", path=facts) == 0  # idempotent


def test_non_success_status_fails_loudly():
    with pytest.raises(AdapterError, match="not SUCCESS"):
        _a().parse(SPEC, [{"status": "MATCH_NOT_FOUND", "object": {}}])


def test_bad_shape_fails_loudly():
    with pytest.raises(AdapterError, match="non-empty list"):
        _a().parse(SPEC, {})
