"""Trade-tracker schema — the minimal, append-only hypothesis record (spec §6).

This is a *seed* of the full trade tracker (project step 6), built now only so the
scanner's screen→thesis hook has somewhere to land. Charter constraint #6: records
are **immutable**; a correction is a NEW record whose ``supersedes`` points at the
original. Nothing is ever edited in place.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Direction(StrEnum):
    """Expression direction. ``undecided`` is deliberate: the scanner flags a
    dislocation but leaves mean-revert-vs-momentum to the analyst (spec §6)."""

    LONG = "long"
    SHORT = "short"
    UNDECIDED = "undecided"


class Status(StrEnum):
    DRAFT = "draft"  # auto-created from a scan flag, not yet sized
    OPEN = "open"
    CLOSED = "closed"
    DISCARDED = "discarded"


class Hypothesis(BaseModel):
    """An immutable trade-hypothesis record.

    Created either by hand or auto-promoted from an outlier scan. Corrections append
    a new record with ``supersedes`` set — the log is the audit trail.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    hypothesis_id: str
    created_as_of: datetime
    instrument: str  # registry series_id (or a declared derived pair id)
    direction: Direction = Direction.UNDECIDED
    thesis: str = ""  # short free-text rationale
    source: str = "manual"  # "manual" | "scanner" | ...
    scan_ref: str | None = None  # link back to the scan record that spawned it
    status: Status = Status.DRAFT
    supersedes: str | None = None  # hypothesis_id this record corrects, if any
    tags: dict[str, str] = Field(default_factory=dict)
