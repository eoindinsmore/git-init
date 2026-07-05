"""Scanner universe spec (spec §6).

Declares what the daily dislocation screen looks at: raw registry series plus
*derived* pairs (ratios / spreads / curve slopes), and which items form the vector
for the multivariate (Mahalanobis) check. Derived items are declared here, never
hard-coded in the engine.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

UNIVERSE_DIR = Path(__file__).resolve().parent / "universe"


class DerivedItem(BaseModel):
    """A constructed series: ``ratio`` = a/b, ``spread`` = a−b (also curve slopes)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: str  # "ratio" | "spread"
    legs: list[str] = Field(min_length=2, max_length=2)
    label: str | None = None


class UniverseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    series: list[str] = Field(default_factory=list)  # raw registry series_ids
    derived: list[DerivedItem] = Field(default_factory=list)
    mahalanobis_set: list[str] = Field(default_factory=list)  # item ids for the joint vector
    windows: list[int] = Field(default_factory=lambda: [20, 60, 250])
    z_threshold: float = 2.0

    @property
    def all_item_ids(self) -> list[str]:
        return list(self.series) + [d.id for d in self.derived]


def load_universe(path: str | Path) -> UniverseSpec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return UniverseSpec.model_validate(raw)


def load_named(name: str, universe_dir: Path | None = None) -> UniverseSpec:
    directory = universe_dir or UNIVERSE_DIR
    return load_universe(directory / f"{name}.yaml")
