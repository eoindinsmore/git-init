"""Track-record analytics (spec §4) — hit rates, calibration, P&L, process stats.

All statistics are computed from a single derived *view*: one row per call, built by
replaying the log and marking each call against the point-in-time store. Everything
downstream (the Streamlit page, the PDF) reads this view, so the numbers are defined in
exactly one place.

Two honesty rules are baked in:

- **Calibration and hit rate use only market resolutions** (target_hit / stopped /
  expired). A discretionary close truncates the bet, so it does not count for or against
  a stated probability — but the *counterfactual* of those closes (what holding to plan
  would have done) is reported separately as its own exhibit.
- **Small samples are never dressed up.** Every table carries its ``n``; a ``sparse``
  flag marks groups with ``n < 20`` so the presentation layer can suppress a bare
  percentage instead of implying precision that is not there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from quant import store
from tracker import events as ev
from tracker import pricing
from tracker.state import (
    CLOSED,
    MARKET_RESOLUTIONS,
    OPEN,
    TERMINAL_STATUSES,
    CallState,
    replay,
)

SPARSE_N = 20  # below this, suppress percentage-only displays (spec §4)

_CONF_EDGES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
_CONF_LABELS = ["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"]
_HORIZON_EDGES = [0, 14, 45, 90, 180, 10_000]
_HORIZON_LABELS = ["≤2w", "2–6w", "6–13w", "13–26w", ">26w"]


# --- Derived view -----------------------------------------------------------------

def _series_cache(states: dict[str, CallState], as_of, store_path) -> dict[str, pd.DataFrame]:
    """One point-in-time ``[date, value]`` per distinct instrument, as of the view date."""
    out: dict[str, pd.DataFrame] = {}
    for st in states.values():
        if st.instrument not in out:
            out[st.instrument] = store.get_series(st.instrument, as_of=as_of, path=store_path)
    return out


def _live_marks(st: CallState, series: pd.DataFrame, as_of) -> dict:
    """Entry / exit / P&L for a call, computed live where the log does not freeze them.

    - market resolutions carry frozen entry/exit/pnl from their event;
    - a discretionary close is marked to the next close after the close event;
    - an open call is marked to the latest available close (running, unrealized).
    """
    row = {
        "entry_price": st.entry_price, "exit_price": st.exit_price,
        "mark_price": st.exit_price, "realized_pnl_R": None, "unrealized_pnl_R": None,
    }
    if st.status in MARKET_RESOLUTIONS:
        row["realized_pnl_R"] = st.pnl_R
        return row

    entry = pricing.entry_mark(series, st.created_at) if not series.empty else None
    if entry is None:
        return row  # not entered yet
    row["entry_price"] = entry[1]

    if st.status == CLOSED:
        exit_ = pricing.entry_mark(series, st.resolved_at)  # next close after the close event
        if exit_ is not None:
            row["exit_price"] = row["mark_price"] = exit_[1]
            row["realized_pnl_R"] = pricing.r_multiple(entry[1], exit_[1], st.stop, st.direction)
    elif st.status == OPEN and not series.empty:
        mark = float(series.iloc[-1]["value"])
        row["mark_price"] = mark
        row["unrealized_pnl_R"] = pricing.r_multiple(entry[1], mark, st.stop, st.direction)
    return row


def build_view(
    *,
    as_of: str | pd.Timestamp | datetime | None = None,
    path: Path = ev.EVENTS_PATH,
    store_path: Path = store.FACTS_PATH,
) -> pd.DataFrame:
    """One row per call: immutable facts + resolution + live marks + bucket columns."""
    as_of_ts = pricing.to_naive_utc(as_of if as_of is not None else datetime.now(UTC))
    states = replay(ev.read_events(path))
    if not states:
        return pd.DataFrame()

    series_by_instr = _series_cache(states, as_of_ts, store_path)
    rows = []
    for st in states.values():
        marks = _live_marks(st, series_by_instr.get(st.instrument, pd.DataFrame()), as_of_ts)
        is_market = st.status in MARKET_RESOLUTIONS
        rows.append({
            "call_id": st.call_id,
            "created_at": pricing.to_naive_utc(st.created_at),
            "instrument": st.instrument,
            "expression": st.expression.value,
            "metal": st.metal,
            "direction": st.direction.value,
            "target": st.target, "stop": st.stop,
            "horizon_days": st.horizon_days,
            "confidence": st.confidence,
            "size_R": st.size_R,
            "status": st.status,
            "regime_at_entry": st.regime_at_entry or "—",
            "from_scanner": st.from_scanner,
            "n_amends": st.n_amends,
            "n_corrections": st.n_corrections,
            "thesis_len": len(st.thesis),
            "resolved_at": pricing.to_naive_utc(st.resolved_at)
            if st.resolved_at is not None else pd.NaT,
            "is_market_resolution": is_market,
            "hit": (1.0 if st.status == "target_hit" else 0.0) if is_market else np.nan,
            **marks,
        })
    view = pd.DataFrame(rows)
    view["confidence_bucket"] = pd.cut(
        view["confidence"], bins=_CONF_EDGES, labels=_CONF_LABELS, include_lowest=True
    )
    view["horizon_bucket"] = pd.cut(
        view["horizon_days"], bins=_HORIZON_EDGES, labels=_HORIZON_LABELS
    )
    return view.sort_values("created_at").reset_index(drop=True)


# --- Hit rate ---------------------------------------------------------------------

def hit_rate(view: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Hit rate = P(target before stop within horizon), over market resolutions only.

    Grouped by ``by`` (expression / metal / direction / regime_at_entry /
    horizon_bucket / confidence_bucket) or overall. Each row carries ``n`` and a
    ``sparse`` flag; the ``hit_rate`` is reported but presentation suppresses it when
    sparse (spec §4)."""
    resolved = view[view["is_market_resolution"]] if not view.empty else view
    if resolved.empty:
        return pd.DataFrame(columns=["group", "n", "n_hit", "hit_rate", "sparse"])

    groups = (
        [("all", resolved)] if by is None
        else list(resolved.groupby(by, observed=True))
    )

    out = []
    for name, g in groups:
        n = len(g)
        n_hit = int(g["hit"].sum())
        out.append({
            "group": str(name), "n": n, "n_hit": n_hit,
            "hit_rate": n_hit / n if n else np.nan, "sparse": n < SPARSE_N,
        })
    return pd.DataFrame(out).sort_values("n", ascending=False).reset_index(drop=True)


# --- Calibration ------------------------------------------------------------------

@dataclass
class Calibration:
    reliability: pd.DataFrame  # per confidence bucket: n, mean_confidence, realized_freq
    brier: float | None  # overall Brier score (lower is better)
    n: int  # market resolutions scored

    @property
    def sparse(self) -> bool:
        return self.n < SPARSE_N


def calibration(view: pd.DataFrame) -> Calibration:
    """Stated confidence vs. realized target-hit frequency — the single most important
    exhibit (spec §4). Brier score over market resolutions; a reliability table per
    confidence bucket for the diagram."""
    resolved = view[view["is_market_resolution"]] if not view.empty else view
    if resolved.empty:
        return Calibration(reliability=pd.DataFrame(
            columns=["confidence_bucket", "n", "mean_confidence", "realized_freq", "brier"]
        ), brier=None, n=0)

    brier = float(((resolved["confidence"] - resolved["hit"]) ** 2).mean())
    rows = []
    for bucket, g in resolved.groupby("confidence_bucket", observed=True):
        n = len(g)
        rows.append({
            "confidence_bucket": str(bucket),
            "n": n,
            "mean_confidence": float(g["confidence"].mean()),
            "realized_freq": float(g["hit"].mean()),
            "brier": float(((g["confidence"] - g["hit"]) ** 2).mean()),
        })
    return Calibration(reliability=pd.DataFrame(rows), brier=brier, n=len(resolved))


# --- P&L --------------------------------------------------------------------------

@dataclass
class PnLSummary:
    equity_curve: pd.DataFrame  # [date, value] cumulative realized R
    n_resolved: int
    expectancy_R: float | None  # mean realized R per resolved call
    avg_win_R: float | None
    avg_loss_R: float | None
    win_rate: float | None  # fraction of resolved calls with R > 0
    max_drawdown_R: float | None
    time_under_water_days: int | None

    @property
    def total_R(self) -> float:
        return 0.0 if self.equity_curve.empty else float(self.equity_curve["value"].iloc[-1])


def pnl_summary(view: pd.DataFrame) -> PnLSummary:
    """Realized-R P&L over all resolved calls (market resolutions + discretionary closes).

    Cumulative-R equity curve, expectancy, avg win/loss, max drawdown in R and time
    under water. Proxy-notional / vol-targeted P&L is a later pass (spec §9 step 6)."""
    if view.empty:
        return PnLSummary(pd.DataFrame(columns=["date", "value"]), 0, None, None, None,
                          None, None, None)
    resolved = view[view["status"].isin(TERMINAL_STATUSES) & view["realized_pnl_R"].notna()]
    resolved = resolved.sort_values("resolved_at")
    if resolved.empty:
        return PnLSummary(pd.DataFrame(columns=["date", "value"]), 0, None, None, None,
                          None, None, None)

    r = resolved["realized_pnl_R"].astype(float)
    wins, losses = r[r > 0], r[r < 0]
    equity = pd.DataFrame({
        "date": pd.to_datetime(resolved["resolved_at"].values),
        "value": r.cumsum().to_numpy(),
    })
    cummax = equity["value"].cummax()
    drawdown = equity["value"] - cummax
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0

    # Time under water: span from the peak preceding the deepest trough to recovery
    # (or to the last resolution if never recovered).
    tuw = _time_under_water(equity)

    return PnLSummary(
        equity_curve=equity,
        n_resolved=len(resolved),
        expectancy_R=float(r.mean()),
        avg_win_R=float(wins.mean()) if not wins.empty else None,
        avg_loss_R=float(losses.mean()) if not losses.empty else None,
        win_rate=float((r > 0).mean()),
        max_drawdown_R=max_dd,
        time_under_water_days=tuw,
    )


def _time_under_water(equity: pd.DataFrame) -> int | None:
    """Longest stretch (in days) the equity curve spent below a prior peak."""
    if len(equity) < 2:
        return 0
    peak = -np.inf
    peak_date = equity["date"].iloc[0]
    longest = pd.Timedelta(0)
    for _, row in equity.iterrows():
        if row["value"] >= peak:
            peak, peak_date = row["value"], row["date"]
        else:
            longest = max(longest, row["date"] - peak_date)
    return int(longest.days)


# --- Process stats (spec §4) ------------------------------------------------------

def process_stats(
    view: pd.DataFrame,
    *,
    path: Path = ev.EVENTS_PATH,
    store_path: Path = store.FACTS_PATH,
    as_of: str | pd.Timestamp | datetime | None = None,
) -> dict:
    """Deliberately-reported process metrics: amends, corrections, thesis length, share
    of calls from the scanner, and — the honesty exhibit — the counterfactual of
    discretionary closes (what holding to plan would have returned)."""
    if view.empty:
        return {"n_calls": 0}

    n = len(view)
    closed = view[view["status"] == CLOSED]
    cf = _close_counterfactuals(closed, path=path, store_path=store_path, as_of=as_of)
    return {
        "n_calls": n,
        "n_open": int((view["status"] == OPEN).sum()),
        "n_resolved": int(view["status"].isin(TERMINAL_STATUSES).sum()),
        "n_amends": int(view["n_amends"].sum()),
        "n_corrections": int(view["n_corrections"].sum()),
        "avg_thesis_len": float(view["thesis_len"].mean()),
        "pct_from_scanner": float(view["from_scanner"].mean()),
        "n_discretionary_closes": len(closed),
        "discretionary_close_rate": len(closed) / n,
        "close_counterfactual": cf,
    }


def _close_counterfactuals(
    closed: pd.DataFrame, *, path: Path, store_path: Path, as_of,
) -> dict:
    """For each discretionary close, resolve the call *as if it had been held to plan*
    and compare. Answers 'did discretionary exits help or hurt?' honestly."""
    if closed.empty:
        return {"n": 0}
    as_of_ts = pricing.to_naive_utc(as_of if as_of is not None else datetime.now(UTC))
    states = replay(ev.read_events(path))
    actual, counter = [], []
    for call_id, actual_R in zip(closed["call_id"], closed["realized_pnl_R"], strict=False):
        st = states[call_id]
        series = store.get_series(st.instrument, as_of=as_of_ts, path=store_path)
        res = pricing.resolve(
            series, created_at=st.created_at, direction=st.direction,
            target=st.target, stop=st.stop, horizon_days=st.horizon_days, as_of=as_of_ts,
        )
        if res is not None and pd.notna(actual_R):
            actual.append(float(actual_R))
            counter.append(float(res["pnl_R"]))
    if not actual:
        return {"n": len(closed), "n_with_counterfactual": 0}
    return {
        "n": len(closed),
        "n_with_counterfactual": len(actual),
        "mean_actual_R": float(np.mean(actual)),
        "mean_held_to_plan_R": float(np.mean(counter)),
        "edge_from_closing_R": float(np.mean(actual) - np.mean(counter)),
    }
