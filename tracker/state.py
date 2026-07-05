"""Derived state by replaying the event log (spec §1).

The event log is the source of truth; a call's *current* state is a fold over its
events. Nothing here mutates the log — :func:`replay` is a pure reducer. Live prices
(entry level, running mark, open-call P&L) are **not** derived here: they are computed
against the point-in-time store by :mod:`tracker.marking` / :mod:`tracker.analytics`,
because they depend on data outside the log. What lives here is everything the log
alone determines: the (possibly amended/corrected) call facts and the resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from tracker.events import (
    Amend,
    Close,
    Correction,
    Event,
    Expired,
    Expression,
    NewCall,
    Stopped,
    TargetHit,
    TradeDirection,
)

# Derived lifecycle status of a call.
OPEN = "open"
CLOSED = "closed"  # discretionary exit
TARGET_HIT = "target_hit"
STOPPED = "stopped"
EXPIRED = "expired"

TERMINAL_STATUSES = frozenset({CLOSED, TARGET_HIT, STOPPED, EXPIRED})
# A "market resolution" is one where the outcome vs the stated hypothesis is
# unambiguous — the input to calibration (discretionary closes truncate the bet).
MARKET_RESOLUTIONS = frozenset({TARGET_HIT, STOPPED, EXPIRED})


@dataclass
class CallState:
    """The folded state of one call. Immutable facts from ``call.new``, overlaid with
    any amendments/corrections, plus the terminal resolution if any."""

    call_id: str
    created_at: datetime
    instrument: str
    expression: Expression
    metal: str
    direction: TradeDirection
    entry_basis: str
    target: float
    stop: float
    horizon_days: int
    confidence: float
    size_R: float
    thesis: str
    catalysts: list[str]
    source_scan_id: str | None
    regime_at_entry: str | None

    status: str = OPEN
    # Terminal detail (frozen on the resolving event); None while open.
    resolved_at: datetime | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    pnl_R: float | None = None
    close_reason: str | None = None

    # Process stats (spec §4).
    n_amends: int = 0
    n_corrections: int = 0
    amend_reasons: list[str] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.status == OPEN

    @property
    def from_scanner(self) -> bool:
        return self.source_scan_id is not None


_AMENDABLE = ("target", "stop", "thesis", "horizon_days")
_CORRECTABLE = (*_AMENDABLE, "confidence", "size_R", "direction", "metal", "instrument")


def _apply_new(ev: NewCall) -> CallState:
    return CallState(
        call_id=ev.call_id,
        created_at=ev.created_at,
        instrument=ev.instrument,
        expression=ev.expression,
        metal=ev.metal,
        direction=ev.direction,
        entry_basis=ev.entry_basis,
        target=ev.target,
        stop=ev.stop,
        horizon_days=ev.horizon_days,
        confidence=ev.confidence,
        size_R=ev.size_R,
        thesis=ev.thesis,
        catalysts=list(ev.catalysts),
        source_scan_id=ev.source_scan_id,
        regime_at_entry=ev.regime_at_entry,
    )


def _fold(state: CallState, ev: Event) -> CallState:
    if isinstance(ev, Amend):
        for f in _AMENDABLE:
            v = getattr(ev, f)
            if v is not None:
                setattr(state, f, v)
        state.n_amends += 1
        state.amend_reasons.append(ev.reason)
    elif isinstance(ev, Correction):
        for k, v in ev.fields.items():
            if k in _CORRECTABLE:
                setattr(state, k, v)
        state.n_corrections += 1
    elif isinstance(ev, Close):
        # Discretionary exit. Prices/P&L are derived live by analytics (the exit close
        # prints only after this event), so only the reason + timestamp are frozen here.
        state.status = CLOSED
        state.resolved_at = ev.created_at
        state.close_reason = ev.reason
    elif isinstance(ev, TargetHit | Stopped | Expired):
        state.status = {TargetHit: TARGET_HIT, Stopped: STOPPED, Expired: EXPIRED}[type(ev)]
        state.resolved_at = ev.mark_date
        state.entry_price = ev.entry_price
        state.exit_price = ev.exit_price
        state.pnl_R = ev.pnl_R
    return state


def replay(events: list[Event]) -> dict[str, CallState]:
    """Fold the whole log into ``call_id -> CallState``, in append order.

    ``call.new`` opens a call; amend/correction overlay fields; the terminal events
    freeze the resolution. Events referencing an unknown call are ignored defensively
    (a well-formed log never produces them)."""
    calls: dict[str, CallState] = {}
    for ev in events:
        if isinstance(ev, NewCall):
            calls[ev.call_id] = _apply_new(ev)
        elif ev.call_id in calls:
            _fold(calls[ev.call_id], ev)
    return calls


def get_state(events: list[Event], call_id: str) -> CallState | None:
    return replay(events).get(call_id)
