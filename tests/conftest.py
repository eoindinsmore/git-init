"""Shared test fixtures. Adapter tests run offline against captured payloads."""

from __future__ import annotations

import json
from pathlib import Path

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


@pytest.fixture(scope="session")
def fred_raw(fixture_dir: Path) -> dict:
    """The real FRED observations + metadata payloads captured by the harvester."""
    obs = json.loads((fixture_dir / "fred_INDPRO_observations.json").read_text(encoding="utf-8"))
    meta = json.loads((fixture_dir / "fred_INDPRO_meta.json").read_text(encoding="utf-8"))
    return {"observations": obs, "meta": meta}
