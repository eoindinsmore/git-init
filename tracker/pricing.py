"""Price maths for marking calls — pure functions over a ``[date, value]`` frame.

Isolated from both the event log and the store so it is trivially testable and reused
by the marking engine and by discretionary close. The marking conventions that make
the track record honest live here and are stated on every output (spec §3):

- **Next-close entry.** Entry is the first close *strictly after* ``created_at`` — never
  the same-day close (the call may have been logged after it), never a decision-moment
  price. Conservative by construction.
- **Anti-backdating.** No price dated at or before ``created_at`` is ever used.
- **Stop precedence.** With close-only data we cannot know intra-period ordering, so if
  a period could be read as touching both levels, the stop wins. Close-only marking is a
  stated limitation, not a bug.
"""

from __future__ import annotations

import pandas as pd

from tracker.events import TradeDirection
from tracker.state import EXPIRED, STOPPED, TARGET_HIT


def to_naive_utc(ts) -> pd.Timestamp:
    """Coerce any datetime to tz-naive UTC, matching the store's date convention."""
    t = pd.Timestamp(ts)
    return t.tz_convert("UTC").tz_localize(None) if t.tz is not None else t


def r_multiple(entry: float, exit_: float, stop: float, direction: TradeDirection) -> float:
    """P&L in R-multiples: directional move divided by risk-per-unit ``|entry − stop|``.

    Honest across instruments of wildly different volatility and units (spec §3). A long
    that reaches its target for +1R of risk returns +1.0; a stop-out returns ≈ −1.0."""
    risk = abs(entry - stop)
    if risk == 0:
        raise ValueError("entry and stop coincide — risk-per-unit is zero")
    move = (exit_ - entry) if direction is TradeDirection.LONG else (entry - exit_)
    return move / risk


def entry_mark(series: pd.DataFrame, created_at) -> tuple[pd.Timestamp, float] | None:
    """First close strictly after ``created_at`` → ``(date, price)``; ``None`` if the
    call has not been entered yet (no close has printed since it was logged)."""
    if series.empty:
        return None
    cutoff = to_naive_utc(created_at)
    after = series[series["date"] > cutoff].sort_values("date")
    if after.empty:
        return None
    row = after.iloc[0]
    return pd.Timestamp(row["date"]), float(row["value"])


def resolve(
    series: pd.DataFrame,
    *,
    created_at,
    direction: TradeDirection,
    target: float,
    stop: float,
    horizon_days: int,
    as_of,
) -> dict | None:
    """Resolve a call against close-only marks, or ``None`` if still open.

    ``series`` is the marked ``[date, value]`` already retrieved point-in-time to
    ``as_of``. Returns ``{kind, mark_date, entry_price, exit_price, pnl_R}`` where
    ``kind`` is ``target_hit`` / ``stopped`` / ``expired``. Stop is checked before
    target (stop precedence). Expiry fires only once ``as_of`` has reached the horizon,
    marking to the last close within it."""
    entered = entry_mark(series, created_at)
    if entered is None:
        return None  # not yet entered → nothing to resolve
    entry_date, entry_price = entered

    cutoff = to_naive_utc(as_of)
    horizon_end = to_naive_utc(created_at) + pd.Timedelta(days=horizon_days)

    # Marks eligible to trigger: from entry, within the horizon, and already knowable.
    marks = series[
        (series["date"] >= entry_date)
        & (series["date"] <= horizon_end)
        & (series["date"] <= cutoff)
    ].sort_values("date")

    for _, row in marks.iterrows():
        v = float(row["value"])
        hit_stop = v <= stop if direction is TradeDirection.LONG else v >= stop
        hit_target = v >= target if direction is TradeDirection.LONG else v <= target
        if hit_stop:  # stop precedence (spec §3)
            return _resolution(STOPPED, row["date"], entry_price, v, stop, direction)
        if hit_target:
            return _resolution(TARGET_HIT, row["date"], entry_price, v, stop, direction)

    # No level touched. Expire only once the marking date has reached the horizon.
    if cutoff >= horizon_end and not marks.empty:
        last = marks.iloc[-1]
        return _resolution(
            EXPIRED, last["date"], entry_price, float(last["value"]), stop, direction
        )
    return None


def _resolution(kind, mark_date, entry_price, exit_price, stop, direction) -> dict:
    return {
        "kind": kind,
        "mark_date": pd.Timestamp(mark_date),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl_R": r_multiple(entry_price, exit_price, stop, direction),
    }
