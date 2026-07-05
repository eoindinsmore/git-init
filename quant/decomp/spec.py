"""Decomposition specs — one YAML per target declares its driver set and the
economic orthogonalization order (spec §4).

The order is a *modelling choice with consequences* (correlated regressors), so it
is declared explicitly and rendered on the output, never hidden. Example
(aluminium): broad USD → real rates → China activity → energy → positioning.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

SPECS_DIR = Path(__file__).resolve().parent / "specs"


class DriverSpec(BaseModel):
    """One driver in a decomposition. ``order`` sets the orthogonalization rank
    (lower first); ``label`` is the human name shown on the chart."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    series_id: str
    label: str
    order: int = Field(ge=0)


class DecompSpec(BaseModel):
    """A target and the drivers its returns are attributed to."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: str  # registry series_id of the thing being explained
    target_label: str
    drivers: list[DriverSpec]
    frequency: str = "W"  # resample frequency for returns (pandas offset alias)
    est_window: int = 104  # rolling estimation window (default ~2y weekly)
    return_kind: str = "log"  # "log" (additive over windows) or "pct"

    @property
    def ordered_driver_ids(self) -> list[str]:
        """Driver series_ids sorted by their declared orthogonalization order."""
        return [d.series_id for d in sorted(self.drivers, key=lambda d: d.order)]

    def label_of(self, series_id: str) -> str:
        for d in self.drivers:
            if d.series_id == series_id:
                return d.label
        return series_id


def load_spec(path: str | Path) -> DecompSpec:
    """Load a single decomposition spec YAML."""
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return DecompSpec.model_validate(raw)


def load_named(name: str, specs_dir: Path | None = None) -> DecompSpec:
    """Load ``<specs_dir>/<name>.yaml`` (e.g. ``load_named("aluminium")``)."""
    directory = specs_dir or SPECS_DIR
    return load_spec(directory / f"{name}.yaml")
