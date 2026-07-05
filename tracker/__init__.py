"""Trade recommendation tracker (project step 6, spec ``docs/specs/trade_tracker_spec.md``).

An append-only, tamper-evident, event-sourced log of trade calls, marked against the
free proxy price layer with point-in-time discipline. Two layers coexist:

- **The scanner draft seed** (:mod:`tracker.schema` / :mod:`tracker.store`) — the
  immutable ``Hypothesis`` a dislocation scan promotes. A draft is *not* a call; it
  lands in ``data/hypotheses.jsonl`` and stays there until an analyst commits it.
- **The committed call log** (this package's newer modules) — event-sourced in
  ``tracker/events.jsonl`` with a SHA-256 hash chain, replayed to derive state, marked
  by :mod:`tracker.marking`, and analysed by :mod:`tracker.analytics`.
"""

from __future__ import annotations

from tracker.calls import amend, calls_frame, close, correct, current_calls, new_call
from tracker.events import (
    Expression,
    TradeDirection,
    read_events,
    verify,
)
from tracker.state import CallState, replay

__all__ = [
    "CallState",
    "Expression",
    "TradeDirection",
    "amend",
    "calls_frame",
    "close",
    "correct",
    "current_calls",
    "new_call",
    "read_events",
    "replay",
    "verify",
]
