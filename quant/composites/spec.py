"""Composite specs — declare a composite's components, method, and reference.

A composite is a `Signal`, so it carries provenance (its components) and a worst-case
publication lag. The ``reference`` component fixes the PCA sign so the composite has a
stable, interpretable orientation across vintages.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

SPECS_DIR = Path(__file__).resolve().parent / "specs"

METHODS = ("diffusion", "zscore", "pca")


class CompositeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    composite_id: str
    label: str
    components: list[str] = Field(min_length=1)  # registry series_ids
    method: str = "zscore"  # "diffusion" | "zscore" | "pca"
    target: str = ""  # what the composite is meant to lead/explain (for the Signal)
    direction_convention: str = ""
    reference: str | None = None  # PCA sign reference (defaults to first component)
    window: int | None = None  # rolling window for zscore/pca; None = expanding/full
    min_window: int = 36  # PCA minimum history before the first point-in-time score
    expanding: bool = True

    def model_post_init(self, __context) -> None:
        if self.method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}, got {self.method!r}")


def load_spec(path: str | Path) -> CompositeSpec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return CompositeSpec.model_validate(raw)


def load_named(name: str, specs_dir: Path | None = None) -> CompositeSpec:
    directory = specs_dir or SPECS_DIR
    return load_spec(directory / f"{name}.yaml")
