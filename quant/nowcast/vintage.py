"""The vintage record — the key nowcasting artifact (spec §2).

Every nowcast revision is stored append-only as ``(target_period, as_of, value, se)``,
mirroring the fact table's point-in-time discipline: you can always answer "what did
the nowcast say, and when?". Nothing is overwritten.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
VINTAGE_PATH = DATA_DIR / "nowcast_vintages.jsonl"


class NowcastVintage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str
    target_period: date  # the period-end being nowcast
    as_of: date  # when this estimate was made
    value: float
    se: float
    n_inputs: int  # indicators available at this as_of


def record(v: NowcastVintage, path: Path = VINTAGE_PATH) -> None:
    """Append one vintage. Never rewrites prior lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(v.model_dump_json() + "\n")


def read_all(path: Path = VINTAGE_PATH) -> pd.DataFrame:
    """All recorded vintages as a frame (empty if none)."""
    if not path.exists():
        return pd.DataFrame(
            columns=["target_id", "target_period", "as_of", "value", "se", "n_inputs"]
        )
    rows = [
        NowcastVintage.model_validate_json(line).model_dump()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return pd.DataFrame(rows)
