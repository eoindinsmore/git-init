"""Regime specs — declare the state variables and their rules (spec §7)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from quant.regimes import core

SPECS_DIR = Path(__file__).resolve().parent / "specs"

KINDS = ("band", "ma_trend", "level_delta")


class StateVarSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    series_id: str
    kind: str  # "band" | "ma_trend" | "level_delta"
    params: dict = Field(default_factory=dict)

    def model_post_init(self, __context) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {self.kind!r}")


class RegimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    states: list[StateVarSpec] = Field(min_length=1)
    sizing_multipliers: dict[str, float] = Field(default_factory=dict)


def apply_state(spec: StateVarSpec, series: pd.Series) -> pd.Series:
    """Run the categorizer named by ``spec.kind`` with its params."""
    if spec.kind == "band":
        return core.band(series, **spec.params)
    if spec.kind == "ma_trend":
        return core.ma_trend(series, **spec.params)
    if spec.kind == "level_delta":
        return core.level_delta(series, **spec.params)
    raise ValueError(f"unknown kind {spec.kind!r}")


def load_spec(path: str | Path) -> RegimeSpec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return RegimeSpec.model_validate(raw)


def load_named(name: str, specs_dir: Path | None = None) -> RegimeSpec:
    directory = specs_dir or SPECS_DIR
    return load_spec(directory / f"{name}.yaml")
