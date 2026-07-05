"""Event-sourced trade-call log — the tamper-evident source of truth (spec §1).

The tracker is **an event log, not a table of editable rows.** State is derived by
replaying events (see :mod:`tracker.state`); nothing is ever updated or deleted. The
credibility of the whole track record rests on it being impossible to quietly rewrite
history, so every design choice here serves that:

- **Append-only.** :func:`append` opens the file in ``"a"`` mode and only ever adds a
  line. There is no update or delete path in this module, by construction.
- **Hash chain.** Every event carries ``prev_hash`` = SHA-256 of the *raw stored line*
  of the previous event. Retro-insertion, deletion or a single flipped digit anywhere
  in the file breaks the chain and :func:`verify` reports exactly where.
- **System clock.** ``created_at`` is stamped by the writer (never accepted from
  input); the anti-backdating invariants that depend on it live in
  :mod:`tracker.calls`.

Storage: ``tracker/events.jsonl`` (one JSON event per line) is **git-committed** — so
history is doubly auditable (hash chain *and* version control). A derived Parquet view
for analytics is rebuilt from it and is disposable.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

EVENTS_PATH = Path(__file__).resolve().parent / "events.jsonl"

# Chain root: the ``prev_hash`` of the very first event. 64 zero-nibbles so it is
# visibly a sentinel and never collides with a real SHA-256 digest.
GENESIS_HASH = "0" * 64


class EventType(StrEnum):
    """The seven event kinds (spec §1). Analyst-authored, except the last three which
    are emitted only by the marking engine (:mod:`tracker.marking`)."""

    NEW = "call.new"
    AMEND = "call.amend"
    CLOSE = "call.close"
    CORRECTION = "call.correction"
    TARGET_HIT = "call.target_hit"
    STOPPED = "call.stopped"
    EXPIRED = "call.expired"


class Expression(StrEnum):
    """How the call is expressed / marked (spec §2)."""

    OUTRIGHT = "outright"  # single proxy series
    TIME_SPREAD = "time_spread"  # near vs deferred (needs curve data)
    REGIONAL_PREMIUM = "regional_premium"  # AUP / EDP series
    CROSS_PRODUCT_RV = "cross_product_rv"  # ratio/spread of two series
    ARB_PROXY = "arb_proxy"  # e.g. SHFE/LME ratio where data permits


class TradeDirection(StrEnum):
    """A committed call is directional — no ``undecided`` (that is a scanner *draft*
    concept, see :class:`tracker.schema.Direction`)."""

    LONG = "long"
    SHORT = "short"


# Expressions whose marked series is available today. Others are rejected at
# ``call.new`` time (spec §3: data-unavailable expressions must not fail at marking).
LIVE_EXPRESSIONS = frozenset({Expression.OUTRIGHT, Expression.REGIONAL_PREMIUM})

# Terminal event types — a call in one of these states is frozen (spec §1).
TERMINAL_TYPES = frozenset(
    {EventType.CLOSE, EventType.TARGET_HIT, EventType.STOPPED, EventType.EXPIRED}
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _EventBase(BaseModel):
    """Common envelope on every event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    call_id: str  # the call this event pertains to (for ``call.new``, the new call's id)
    created_at: datetime = Field(default_factory=_utcnow)  # system-set, UTC
    prev_hash: str  # SHA-256 of the previous stored line, or GENESIS_HASH


class NewCall(_EventBase):
    """``call.new`` — a new recommendation. Full analyst payload (spec §2).

    Field-level validation (ranges, granularity, thesis length) lives here; the
    data-dependent rules (instrument exists, target/stop on the correct side of the
    last mark, expression is live) are enforced in :func:`tracker.calls.new_call`,
    which has the store and registry to hand.
    """

    event_type: Literal[EventType.NEW] = EventType.NEW

    instrument: str  # registry series_id it is marked against
    expression: Expression
    metal: str  # tag from the registry vocabulary
    direction: TradeDirection
    entry_basis: Literal["next_close"] = "next_close"  # only option v1; explicit in record
    target: float
    stop: float
    horizon_days: int
    confidence: float  # stated P(target before stop within horizon)
    size_R: float = 1.0
    thesis: str
    catalysts: list[str] = Field(default_factory=list)
    source_scan_id: str | None = None  # link back to a scanner draft, if promoted
    regime_at_entry: str | None = None  # stamped from the regime module

    @field_validator("horizon_days")
    @classmethod
    def _horizon_range(cls, v: int) -> int:
        if not 5 <= v <= 365:
            raise ValueError(f"horizon_days must be 5–365, got {v}")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_grid(cls, v: float) -> float:
        if not 0.05 <= v <= 0.95:
            raise ValueError(f"confidence must be 0.05–0.95, got {v}")
        # Forced granularity of 0.05 (spec §2) — reject false precision (tolerate float noise).
        steps = v / 0.05
        if abs(round(steps) - steps) > 1e-9:
            raise ValueError(f"confidence must be a multiple of 0.05, got {v}")
        return round(round(steps) * 0.05, 2)

    @field_validator("thesis")
    @classmethod
    def _thesis_len(cls, v: str) -> str:
        if len(v.strip()) < 20:
            raise ValueError("thesis is required and must be at least 20 characters")
        return v


class Amend(_EventBase):
    """``call.amend`` — analyst revises target/stop/thesis/horizon on an OPEN call.

    Carries only the changed fields plus a required reason. The original ``call.new``
    stands in the log; ``call.amend`` on a non-open call is rejected (spec §1)."""

    event_type: Literal[EventType.AMEND] = EventType.AMEND
    target: float | None = None
    stop: float | None = None
    thesis: str | None = None
    horizon_days: int | None = None
    reason: str = Field(min_length=1)


class Close(_EventBase):
    """``call.close`` — discretionary exit at market (spec §1). Reason required.

    Carries only the reason and its own ``created_at``. The exit is the next available
    close *after* this event — which has not printed yet at write time — so P&L is
    derived live by :mod:`tracker.analytics` under the same next-close convention as the
    marking engine, never frozen here against a price that does not exist."""

    event_type: Literal[EventType.CLOSE] = EventType.CLOSE
    reason: str = Field(min_length=1)


class Correction(_EventBase):
    """``call.correction`` — fixes a data-entry error (spec §1).

    References the erroneous event, states what was wrong, carries the corrected
    field values. Corrections are counted and reported — their frequency is itself a
    published statistic."""

    event_type: Literal[EventType.CORRECTION] = EventType.CORRECTION
    corrects_event_id: str
    what_was_wrong: str = Field(min_length=1)
    fields: dict[str, float | int | str] = Field(default_factory=dict)


class _Resolution(_EventBase):
    """Shared shape for the three marking-engine terminal events. Prices are frozen at
    emission for audit."""

    mark_date: datetime
    entry_price: float
    exit_price: float
    pnl_R: float


class TargetHit(_Resolution):
    event_type: Literal[EventType.TARGET_HIT] = EventType.TARGET_HIT


class Stopped(_Resolution):
    event_type: Literal[EventType.STOPPED] = EventType.STOPPED


class Expired(_Resolution):
    event_type: Literal[EventType.EXPIRED] = EventType.EXPIRED


Event = Annotated[
    NewCall | Amend | Close | Correction | TargetHit | Stopped | Expired,
    Field(discriminator="event_type"),
]
_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


# --- Hash chain + append-only I/O -------------------------------------------------

class ChainError(RuntimeError):
    """Raised when the hash chain is broken or an append would break it."""


def _hash_line(line: str) -> str:
    """SHA-256 of one stored JSON line (the exact text, no trailing newline)."""
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def read_raw_lines(path: Path = EVENTS_PATH) -> list[str]:
    """Every stored line, verbatim (no trailing newlines). Empty if the log is absent."""
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def head_hash(path: Path = EVENTS_PATH) -> str:
    """Hash of the last stored line — the value the next event's ``prev_hash`` must be.
    ``GENESIS_HASH`` for an empty/absent log."""
    lines = read_raw_lines(path)
    return _hash_line(lines[-1]) if lines else GENESIS_HASH


def read_events(path: Path = EVENTS_PATH) -> list[Event]:
    """Parse every line into a validated, typed event, in append order."""
    return [_ADAPTER.validate_json(ln) for ln in read_raw_lines(path)]


def append(event: Event, path: Path = EVENTS_PATH) -> Event:
    """Append one event, enforcing chain continuity.

    The event's ``prev_hash`` must equal the current :func:`head_hash`; otherwise the
    caller built it against a stale head (or is trying to splice history) and we refuse.
    Writes in ``"a"`` mode — existing lines are never touched."""
    head = head_hash(path)
    if event.prev_hash != head:
        raise ChainError(
            f"prev_hash mismatch: event carries {event.prev_hash[:12]}… but the log "
            f"head is {head[:12]}…. Rebuild the event against the current head."
        )
    line = event.model_dump_json()
    if "\n" in line:  # defensive: a newline in the payload would corrupt the JSONL
        raise ValueError("serialized event contains a newline")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return event


def new_event_kwargs(path: Path = EVENTS_PATH) -> dict:
    """Envelope defaults for building the next event: current head as ``prev_hash``."""
    return {"prev_hash": head_hash(path)}


# --- Verification (spec §1: the result is printed on the track-record PDF) ---------

class VerifyResult(BaseModel):
    ok: bool
    n_events: int
    head_hash: str
    broken_at: int | None = None  # line index (0-based) of the first break
    error: str | None = None

    def summary(self) -> str:
        if self.ok:
            return (
                f"hash chain OK — {self.n_events} events, "
                f"head {self.head_hash[:12]}…"
            )
        return f"HASH CHAIN BROKEN at line {self.broken_at}: {self.error}"


def verify(path: Path = EVENTS_PATH) -> VerifyResult:
    """Replay the raw file and confirm chain integrity (spec §1).

    Checks, in order, that each event parses, that the first event roots at
    ``GENESIS_HASH``, and that every subsequent ``prev_hash`` equals the SHA-256 of the
    literal previous line. Any edit, deletion or insertion anywhere in the file trips
    exactly one of these and is reported with its line index."""
    lines = read_raw_lines(path)
    if not lines:
        return VerifyResult(ok=True, n_events=0, head_hash=GENESIS_HASH)

    expected_prev = GENESIS_HASH
    for i, line in enumerate(lines):
        try:
            ev = _ADAPTER.validate_json(line)
        except Exception as e:  # noqa: BLE001 — report any parse failure as a break
            return VerifyResult(
                ok=False, n_events=len(lines), head_hash=head_hash(path),
                broken_at=i, error=f"line does not parse as an event: {e}",
            )
        if ev.prev_hash != expected_prev:
            return VerifyResult(
                ok=False, n_events=len(lines), head_hash=head_hash(path), broken_at=i,
                error=(
                    f"prev_hash {ev.prev_hash[:12]}… does not match the hash of the "
                    f"preceding line {expected_prev[:12]}… (insertion, deletion or edit)"
                ),
            )
        expected_prev = _hash_line(line)

    return VerifyResult(ok=True, n_events=len(lines), head_hash=expected_prev)
