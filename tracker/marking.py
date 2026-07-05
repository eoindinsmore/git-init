"""Marking engine — resolves OPEN calls against the price store (spec §3).

Runs daily (or on demand). For every open call it retrieves the marked series
**point-in-time to the marking date** and checks it against the call's levels, emitting
exactly one system event — ``call.target_hit`` / ``call.stopped`` / ``call.expired`` —
when the call resolves. These are the only events the engine ever writes; analysts never
emit them by hand.

Point-in-time discipline (spec §8): the mark uses ``store.get_series(as_of=...)`` — the
*vintage* that existed on the marking date — so a later data revision cannot retroactively
change whether a stop was hit. Anti-backdating and the next-close / stop-precedence /
close-only conventions live in :mod:`tracker.pricing` and are documented on every output.

Only ``outright`` and ``regional_premium`` are markable today — both are a single
registry series (the ``instrument``). Other expressions were rejected at ``call.new``
time, so an open call is always one of these two; anything else is skipped loudly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quant import store
from tracker import events as ev
from tracker import pricing
from tracker.events import LIVE_EXPRESSIONS, Event, Expired, Stopped, TargetHit
from tracker.state import EXPIRED, STOPPED, TARGET_HIT, CallState, replay

_TERMINAL_CLS = {TARGET_HIT: TargetHit, STOPPED: Stopped, EXPIRED: Expired}


def _mark_series(state: CallState, as_of: pd.Timestamp, store_path: Path) -> pd.DataFrame:
    """The marked ``[date, value]`` for a call, vintage-strict to the marking date.

    For ``outright`` / ``regional_premium`` this is simply the instrument series as it
    stood on ``as_of`` (spec §3)."""
    return store.get_series(state.instrument, as_of=as_of, path=store_path)


def mark_open_calls(
    as_of: str | pd.Timestamp | datetime | None = None,
    *,
    path: Path = ev.EVENTS_PATH,
    store_path: Path = store.FACTS_PATH,
) -> list[Event]:
    """Mark every OPEN call as of ``as_of`` (default: now); append + return any
    resolution events. Idempotent across runs: a call that has already resolved is no
    longer open on the next replay, so it is never marked twice."""
    as_of_ts = pricing.to_naive_utc(as_of if as_of is not None else datetime.now(UTC))
    emitted: list[Event] = []

    for state in replay(ev.read_events(path)).values():
        if not state.is_open:
            continue
        if state.expression not in LIVE_EXPRESSIONS:
            # Should be unreachable (rejected at entry) — flag rather than silently skip.
            raise ValueError(
                f"open call '{state.call_id}' has non-markable expression "
                f"'{state.expression.value}' — should have been rejected at call.new"
            )
        series = _mark_series(state, as_of_ts, store_path)
        if series.empty:
            continue
        res = pricing.resolve(
            series,
            created_at=state.created_at,
            direction=state.direction,
            target=state.target,
            stop=state.stop,
            horizon_days=state.horizon_days,
            as_of=as_of_ts,
        )
        if res is None:
            continue
        cls = _TERMINAL_CLS[res["kind"]]
        event = cls(
            call_id=state.call_id,
            created_at=datetime.now(UTC),  # wall-clock of the marking run (audit)
            mark_date=res["mark_date"].to_pydatetime(),
            entry_price=res["entry_price"],
            exit_price=res["exit_price"],
            pnl_R=res["pnl_R"],
            prev_hash=ev.head_hash(path),
        )
        ev.append(event, path)
        emitted.append(event)

    return emitted
