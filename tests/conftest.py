"""Shared test fixtures. Adapter tests run offline against captured payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def _latest_fixture_dir() -> Path:
    dirs = sorted(p for p in FIXTURE_ROOT.iterdir() if p.is_dir() and p.name.isdigit())
    if not dirs:
        raise FileNotFoundError(
            "no harvested fixture dir under tests/fixtures/ — run harvest_fixtures.py"
        )
    return dirs[-1]


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return _latest_fixture_dir()


def _load(fixture_dir: Path, name: str) -> Any:
    return json.loads((fixture_dir / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def fred_raw(fixture_dir: Path) -> dict:
    """The real FRED observations + metadata payloads captured by the harvester."""
    obs = _load(fixture_dir, "fred_INDPRO_observations.json")
    meta = _load(fixture_dir, "fred_INDPRO_meta.json")
    return {"observations": obs, "meta": meta}


@pytest.fixture(scope="session")
def eurostat_raw(fixture_dir: Path) -> dict:
    return _load(fixture_dir, "eurostat_sts_inpr_m_DE.json")


@pytest.fixture(scope="session")
def statcan_raw(fixture_dir: Path) -> Any:
    return _load(fixture_dir, "statcan_v65201210.json")


@pytest.fixture(scope="session")
def estat_raw(fixture_dir: Path) -> dict:
    return _load(fixture_dir, "estat_statsdata_0004033012.json")
