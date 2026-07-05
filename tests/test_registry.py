"""Registry loader + schema tests."""

from __future__ import annotations

import pytest

from registry.loader import RegistryError, load_registry
from registry.schema import Category, Frequency, SAStatus, SeriesSpec, Tags


def test_real_registry_loads():
    reg = load_registry()
    assert "us_industrial_production" in reg
    assert reg["us_industrial_production"].source_code == "INDPRO"


def test_price_proxy_requires_caveats():
    with pytest.raises(ValueError, match="price_proxy"):
        SeriesSpec(
            series_id="p", source="fred", source_code="X", name="n", unit="u",
            frequency=Frequency.M, sa_status=SAStatus.NSA,
            tags=Tags(metal="copper", category=Category.PRICE_PROXY),
        )


def test_price_proxy_with_caveats_ok():
    s = SeriesSpec(
        series_id="p", source="fred", source_code="X", name="n", unit="u",
        frequency=Frequency.M, sa_status=SAStatus.NSA,
        tags=Tags(metal="copper", category=Category.PRICE_PROXY),
        caveats="reference average, not an exchange price",
    )
    assert s.caveats


def test_duplicate_series_id_fails(tmp_path):
    (tmp_path / "a.yaml").write_text(
        "- {series_id: dup, source: fred, source_code: A, name: n, unit: u,"
        " frequency: M, sa_status: SA, tags: {category: activity}}\n"
    )
    (tmp_path / "b.yaml").write_text(
        "- {series_id: dup, source: fred, source_code: B, name: n, unit: u,"
        " frequency: M, sa_status: SA, tags: {category: activity}}\n"
    )
    with pytest.raises(RegistryError, match="duplicate series_id 'dup'"):
        load_registry(tmp_path)


def test_unknown_field_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text(
        "- {series_id: x, source: fred, source_code: A, name: n, unit: u,"
        " frequency: M, sa_status: SA, bogus: 1, tags: {category: activity}}\n"
    )
    with pytest.raises(RegistryError):
        load_registry(tmp_path)
