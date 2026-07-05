"""Analyst operations on the call log — new / amend / close / correct (spec §1–3).

These are the *only* sanctioned ways to author events. Each enforces the invariants
that a raw ``events.append`` cannot:

- ``created_at`` is stamped from the system clock here, never taken from the caller
  (anti-backdating, spec §1). Tests inject a controlled clock via the private ``_now``
  hook — that *is* the system clock from the code's point of view, not user input.
- Data-dependent validation the pydantic model can't do: the instrument must exist and
  have data; target/stop must sit on the correct side of the last mark; the expression
  must be one whose data exists today (spec §2, §3).
- amend/close are refused on a non-open call — resolved calls are frozen (spec §1).

The Streamlit page and the CLI both call these; there is no business logic elsewhere.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from quant import store
from registry.loader import RegistryError, get_spec
from tracker import events as ev
from tracker import pricing
from tracker.events import (
    LIVE_EXPRESSIONS,
    Amend,
    Close,
    Correction,
    Expression,
    NewCall,
    TradeDirection,
)
from tracker.state import OPEN, CallState, replay


class CallError(ValueError):
    """Raised when an operation violates a tracker invariant (rejected loudly)."""


def _stamp(clock: datetime | None) -> datetime:
    """The write-time clock (anti-backdating). ``clock`` is the injectable system clock
    used by tests; production passes ``None`` and gets :func:`datetime.now`."""
    return clock if clock is not None else ev._utcnow()


def latest_mark(instrument: str, *, store_path: Path = store.FACTS_PATH) -> float | None:
    """Last available value of the marked series (current-best view), or ``None``."""
    s = store.get_series(instrument, as_of=None, path=store_path)
    return None if s.empty else float(s["value"].iloc[-1])


def _validate_instrument(instrument: str, registry_dir: Path | None, store_path: Path) -> float:
    """Instrument must be declared and have data (spec §2). Returns the last mark."""
    try:
        get_spec(instrument, registry_dir=registry_dir)
    except RegistryError as e:
        raise CallError(f"instrument '{instrument}' is not in the registry — {e}") from None
    mark = latest_mark(instrument, store_path=store_path)
    if mark is None:
        raise CallError(
            f"instrument '{instrument}' has no data in the store; a call must be markable "
            "against a real series (spec §2)."
        )
    return mark


def _validate_levels(direction: TradeDirection, target: float, stop: float, mark: float) -> None:
    """target/stop must be on the correct side of the last mark for the direction (spec §2)."""
    if direction is TradeDirection.LONG:
        ok = stop < mark < target
        want = f"stop < {mark:g} < target"
    else:
        ok = target < mark < stop
        want = f"target < {mark:g} < stop"
    if not ok:
        raise CallError(
            f"{direction.value} call needs {want}; got target={target:g}, stop={stop:g}. "
            "Levels must bracket the last mark on the correct side."
        )


def _regime_at(as_of: datetime, registry_dir: Path | None, store_path: Path) -> str | None:
    """Best-effort regime stamp from the global-macro spec (spec §6). ``None`` when the
    regime's state series are not yet in the store — an honest blank, never a guess."""
    try:
        from quant.regimes import classify_from_store, load_named, regime_banner

        run = classify_from_store(
            load_named("global_macro"), as_of=pricing.to_naive_utc(as_of),
            registry_dir=registry_dir, path=store_path,
        )
        return regime_banner(run.regimes, as_of=as_of).get("regime")
    except Exception:  # noqa: BLE001 — regime stamping is advisory, never blocks a call
        return None


def new_call(
    *,
    instrument: str,
    expression: Expression | str,
    metal: str,
    direction: TradeDirection | str,
    target: float,
    stop: float,
    horizon_days: int,
    confidence: float,
    thesis: str,
    size_R: float = 1.0,
    catalysts: list[str] | None = None,
    source_scan_id: str | None = None,
    path: Path = ev.EVENTS_PATH,
    store_path: Path = store.FACTS_PATH,
    registry_dir: Path | None = None,
    _now: datetime | None = None,
) -> NewCall:
    """Log a new recommendation (``call.new``), validating hard (spec §2).

    ``created_at`` is stamped here from the system clock — never accepted from the
    caller — so a call can never be entered at yesterday's better level."""
    expression = Expression(expression)
    direction = TradeDirection(direction)

    if expression not in LIVE_EXPRESSIONS:
        raise CallError(
            f"expression '{expression.value}' needs curve/derived data not available yet; "
            "rejected at entry rather than failing silently at marking (spec §3). "
            f"Live expressions: {sorted(e.value for e in LIVE_EXPRESSIONS)}."
        )

    mark = _validate_instrument(instrument, registry_dir, store_path)
    _validate_levels(direction, target, stop, mark)

    created_at = _stamp(_now)
    event = NewCall(
        call_id=ev.uuid4().hex,
        created_at=created_at,
        instrument=instrument,
        expression=expression,
        metal=metal,
        direction=direction,
        target=target,
        stop=stop,
        horizon_days=horizon_days,
        confidence=confidence,
        size_R=size_R,
        thesis=thesis,
        catalysts=list(catalysts or []),
        source_scan_id=source_scan_id,
        regime_at_entry=_regime_at(created_at, registry_dir, store_path),
        prev_hash=ev.head_hash(path),
    )
    ev.append(event, path)
    return event


def _require_open(call_id: str, path: Path) -> CallState:
    state = replay(ev.read_events(path)).get(call_id)
    if state is None:
        raise CallError(f"unknown call_id '{call_id}'")
    if state.status != OPEN:
        raise CallError(
            f"call '{call_id}' is {state.status} — resolved calls are frozen (spec §1)."
        )
    return state


def amend(
    call_id: str,
    *,
    reason: str,
    target: float | None = None,
    stop: float | None = None,
    thesis: str | None = None,
    horizon_days: int | None = None,
    path: Path = ev.EVENTS_PATH,
    _now: datetime | None = None,
) -> Amend:
    """Revise target/stop/thesis/horizon on an OPEN call (``call.amend``, spec §1)."""
    _require_open(call_id, path)
    if all(v is None for v in (target, stop, thesis, horizon_days)):
        raise CallError("amend must change at least one field")
    event = Amend(
        call_id=call_id, created_at=_stamp(_now), reason=reason,
        target=target, stop=stop, thesis=thesis, horizon_days=horizon_days,
        prev_hash=ev.head_hash(path),
    )
    ev.append(event, path)
    return event


def close(
    call_id: str,
    *,
    reason: str,
    path: Path = ev.EVENTS_PATH,
    _now: datetime | None = None,
) -> Close:
    """Discretionary close at market (``call.close``, spec §1).

    Records the decision and its timestamp only. The exit is the first close *after*
    this event — not yet printed at write time — so P&L is derived live by
    :mod:`tracker.analytics`, under the same next-close convention as the marking
    engine, rather than frozen here against a non-existent price."""
    _require_open(call_id, path)
    event = Close(
        call_id=call_id, created_at=_stamp(_now), reason=reason, prev_hash=ev.head_hash(path)
    )
    ev.append(event, path)
    return event


def correct(
    call_id: str,
    *,
    corrects_event_id: str,
    what_was_wrong: str,
    fields: dict,
    path: Path = ev.EVENTS_PATH,
    _now: datetime | None = None,
) -> Correction:
    """Fix a data-entry error (``call.correction``, spec §1). Counted and reported."""
    events = ev.read_events(path)
    if call_id not in replay(events):
        raise CallError(f"unknown call_id '{call_id}'")
    if not any(e.event_id == corrects_event_id for e in events):
        raise CallError(f"corrects_event_id '{corrects_event_id}' is not in the log")
    event = Correction(
        call_id=call_id, created_at=_stamp(_now),
        corrects_event_id=corrects_event_id, what_was_wrong=what_was_wrong,
        fields=fields, prev_hash=ev.head_hash(path),
    )
    ev.append(event, path)
    return event


def current_calls(path: Path = ev.EVENTS_PATH) -> dict[str, CallState]:
    """Replay the log to the current derived state of every call."""
    return replay(ev.read_events(path))


# Re-export for convenience so callers can build a frame without importing pandas here.
def calls_frame(path: Path = ev.EVENTS_PATH) -> pd.DataFrame:
    """Flat frame of derived call states (facts + resolution), newest first."""
    states = current_calls(path)
    if not states:
        return pd.DataFrame()
    rows = [
        {
            "call_id": s.call_id,
            "created_at": s.created_at,
            "instrument": s.instrument,
            "expression": s.expression.value,
            "metal": s.metal,
            "direction": s.direction.value,
            "target": s.target,
            "stop": s.stop,
            "horizon_days": s.horizon_days,
            "confidence": s.confidence,
            "size_R": s.size_R,
            "status": s.status,
            "entry_price": s.entry_price,
            "exit_price": s.exit_price,
            "pnl_R": s.pnl_R,
            "resolved_at": s.resolved_at,
            "regime_at_entry": s.regime_at_entry,
            "n_amends": s.n_amends,
            "n_corrections": s.n_corrections,
            "from_scanner": s.from_scanner,
            "thesis": s.thesis,
        }
        for s in states.values()
    ]
    return pd.DataFrame(rows).sort_values("created_at", ascending=False).reset_index(drop=True)
