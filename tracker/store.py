"""Append-only JSONL store for trade hypotheses (spec §6, charter constraint #6).

One JSON object per line. Appends never rewrite prior lines; there is no update or
delete. A correction is a new ``Hypothesis`` whose ``supersedes`` references the
original. ``current_view`` folds the log to the latest record per hypothesis chain
for display, without ever mutating the file.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from tracker.schema import Hypothesis

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TRACKER_PATH = DATA_DIR / "hypotheses.jsonl"


def append(h: Hypothesis, path: Path = TRACKER_PATH) -> None:
    """Append one hypothesis as a JSON line. Never rewrites existing lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(h.model_dump_json() + "\n")


def read_all(path: Path = TRACKER_PATH) -> list[Hypothesis]:
    """Read every record in append order (full audit trail)."""
    if not path.exists():
        return []
    out: list[Hypothesis] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(Hypothesis.model_validate_json(line))
    return out


def current_view(path: Path = TRACKER_PATH) -> pd.DataFrame:
    """Latest record per hypothesis chain, as a frame for display.

    A record with ``supersedes=X`` replaces X in the view; the underlying file is
    untouched. Returns columns from the schema, most recent first.
    """
    records = read_all(path)
    if not records:
        return pd.DataFrame()
    superseded = {r.supersedes for r in records if r.supersedes}
    latest = [r for r in records if r.hypothesis_id not in superseded]
    df = pd.DataFrame([r.model_dump() for r in latest])
    return df.sort_values("created_as_of", ascending=False).reset_index(drop=True)
