"""Trade recommendation tracker — the buy-side track-record page (spec §5).

Open calls with live marks, the resolved-call log, the calibration diagram (the single
most important exhibit), the R equity curve, and the deliberately-reported process
stats — plus the hash-chain verification line. The page does no maths of its own: every
number comes from ``tracker`` (the domain layer), keeping the app's zero-analytics rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import theme  # noqa: E402
from app import toolkit_ui as ui  # noqa: E402
from tracker import analytics, calls, marking, report  # noqa: E402
from tracker import events as ev  # noqa: E402
from tracker.calls import CallError  # noqa: E402
from tracker.events import LIVE_EXPRESSIONS  # noqa: E402

theme.configure_page("Trade Tracker")

ui.page_header(
    "Evidence package",
    "Trade recommendation tracker",
    "Append-only, hash-chained call log marked against the free proxy layer with "
    "point-in-time discipline. Entry is the next close after a call is logged; stops "
    "take precedence; marking is close-only. Calibration is the headline exhibit.",
)

# --- Hash-chain verification line (spec §1, §5) -----------------------------------
res = ev.verify()
(st.success if res.ok else st.error)(f"🔗 {res.summary()}")

# --- New call ---------------------------------------------------------------------
with st.expander("＋ Log a new call", expanded=False):
    series = ui.series_with_data()
    with st.form("new_call", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        instrument = c1.selectbox("Instrument (marked series)", series)
        expression = c2.selectbox("Expression", sorted(e.value for e in LIVE_EXPRESSIONS))
        metal = c3.text_input("Metal", value="copper")
        c4, c5, c6 = st.columns(3)
        direction = c4.radio("Direction", ["long", "short"], horizontal=True)
        horizon = c5.number_input("Horizon (days)", min_value=5, max_value=365, value=60)
        confidence = c6.select_slider(
            "Confidence", options=[round(0.05 * i, 2) for i in range(1, 20)], value=0.55
        )
        c7, c8 = st.columns(2)
        target = c7.number_input("Target", value=0.0, format="%.4f")
        stop = c8.number_input("Stop", value=0.0, format="%.4f")
        thesis = st.text_area("Thesis (≥20 chars — the reasoning)", height=80)
        submitted = st.form_submit_button("Log call →")
    if submitted:
        try:
            call = calls.new_call(
                instrument=instrument, expression=expression, metal=metal,
                direction=direction, target=float(target), stop=float(stop),
                horizon_days=int(horizon), confidence=float(confidence), thesis=thesis,
            )
            st.success(f"Logged `{call.call_id[:8]}` — regime at entry: "
                       f"{call.regime_at_entry or '—'}.")
        except (CallError, ValueError) as e:
            st.error(f"Rejected: {e}")

# --- Run marking ------------------------------------------------------------------
mark_col, _ = st.columns([1, 4])
if mark_col.button("Run marking now", use_container_width=True):
    emitted = marking.mark_open_calls()
    st.success(f"Marked — {len(emitted)} call(s) resolved.") if emitted \
        else st.info("Marking ran — no calls resolved.")

view = analytics.build_view()
if view.empty:
    st.info("No calls logged yet. Use **Log a new call** above to start the track record.")
    st.stop()

# --- Open calls with live marks ---------------------------------------------------
st.markdown("---")
theme.title_block("Open calls", "Live unrealized marks (next-close entry, latest close)")
open_calls = view[view["status"] == "open"]
if open_calls.empty:
    st.caption("No open calls.")
else:
    cols = ["call_id", "instrument", "direction", "confidence", "entry_price",
            "mark_price", "unrealized_pnl_R", "target", "stop", "horizon_days",
            "regime_at_entry", "created_at"]
    disp = open_calls[cols].copy()
    disp["call_id"] = disp["call_id"].str[:8]
    st.dataframe(
        disp, use_container_width=True, hide_index=True,
        column_config={
            "unrealized_pnl_R": st.column_config.NumberColumn("unrealized R", format="%+.2f"),
            "confidence": st.column_config.NumberColumn("conf", format="%.2f"),
            "entry_price": st.column_config.NumberColumn("entry", format="%.4g"),
            "mark_price": st.column_config.NumberColumn("mark", format="%.4g"),
            "created_at": st.column_config.DatetimeColumn("logged", format="YYYY-MM-DD"),
        },
    )

# --- Resolved calls ---------------------------------------------------------------
st.markdown("---")
theme.title_block("Resolved calls", "Closed, target-hit, stopped and expired")
resolved = view[view["status"] != "open"]
if resolved.empty:
    st.caption("No resolved calls yet.")
else:
    f1, f2 = st.columns(2)
    statuses = f1.multiselect("Status", sorted(resolved["status"].unique()),
                              default=sorted(resolved["status"].unique()))
    metals = f2.multiselect("Metal", sorted(resolved["metal"].unique()),
                            default=sorted(resolved["metal"].unique()))
    sub = resolved[resolved["status"].isin(statuses) & resolved["metal"].isin(metals)]
    cols = ["call_id", "instrument", "direction", "status", "confidence", "entry_price",
            "exit_price", "realized_pnl_R", "resolved_at"]
    disp = sub[cols].copy()
    disp["call_id"] = disp["call_id"].str[:8]
    st.dataframe(
        disp, use_container_width=True, hide_index=True,
        column_config={
            "realized_pnl_R": st.column_config.NumberColumn("R", format="%+.2f"),
            "confidence": st.column_config.NumberColumn("conf", format="%.2f"),
            "entry_price": st.column_config.NumberColumn("entry", format="%.4g"),
            "exit_price": st.column_config.NumberColumn("exit", format="%.4g"),
            "resolved_at": st.column_config.DatetimeColumn("resolved", format="YYYY-MM-DD"),
        },
    )

# --- Calibration + equity ---------------------------------------------------------
st.markdown("---")
cal = analytics.calibration(view)
pnl = analytics.pnl_summary(view)

left, right = st.columns(2)
with left:
    theme.title_block("Calibration", "Stated confidence vs. realized hit frequency")
    if cal.n == 0:
        st.caption("No market-resolved calls yet.")
    else:
        st.metric("Brier score", f"{cal.brier:.3f}",
                  help="Mean squared (confidence − outcome); lower is better. "
                  + (f"n={cal.n}" if not cal.sparse else f"n={cal.n} — small sample"))
        diagonal = alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(
            strokeDash=[4, 4], color=theme.INK_3).encode(x="x:Q", y="y:Q")
        pts = alt.Chart(cal.reliability).mark_circle(color=theme.SERIES_1, opacity=0.85).encode(
            x=alt.X("mean_confidence:Q", title="stated confidence",
                    scale=alt.Scale(domain=[0, 1])),
            y=alt.Y("realized_freq:Q", title="realized frequency",
                    scale=alt.Scale(domain=[0, 1])),
            size=alt.Size("n:Q", legend=None),
            tooltip=["confidence_bucket", "n", "mean_confidence", "realized_freq"],
        )
        st.altair_chart((diagonal + pts).properties(height=300, background=theme.SURFACE)
                        .configure_view(stroke=None), use_container_width=True)
        theme.source_line("Perfect calibration = the dashed 45° line. Point size ∝ n.")

with right:
    theme.title_block("Equity curve", "Cumulative realized R across resolved calls")
    if pnl.n_resolved == 0:
        st.caption("No resolved calls yet.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Total R", f"{pnl.total_R:+.2f}")
        m2.metric("Expectancy R", f"{pnl.expectancy_R:+.2f}")
        m3.metric("Max DD (R)", f"{pnl.max_drawdown_R:+.2f}")
        st.altair_chart(ui.area_chart(pnl.equity_curve, y_unit="cumulative R"),
                        use_container_width=True)

# --- Process stats (spec §4) ------------------------------------------------------
st.markdown("---")
theme.title_block("Process statistics", "Reported deliberately — discipline is evidence")
stats = analytics.process_stats(view)
p = st.columns(5)
p[0].metric("Calls", stats["n_calls"])
p[1].metric("Open / resolved", f"{stats['n_open']} / {stats['n_resolved']}")
p[2].metric("Amends", stats["n_amends"])
p[3].metric("Corrections", stats["n_corrections"])
p[4].metric("From scanner", f"{stats['pct_from_scanner']:.0%}")

cf = stats.get("close_counterfactual", {})
if cf.get("n_with_counterfactual"):
    theme.caveat_block(
        f"Honesty exhibit — {cf['n']} discretionary close(s): mean realized "
        f"{cf['mean_actual_R']:+.2f}R vs. {cf['mean_held_to_plan_R']:+.2f}R if held to "
        f"plan (edge from closing {cf['edge_from_closing_R']:+.2f}R)."
    )

# --- Export the one-page track record ---------------------------------------------
st.download_button(
    "⬇ Download one-page track record (HTML)",
    data=report.render_html(view),
    file_name="track_record.html",
    mime="text/html",
    help="Self-contained, self-caveating one-pager with the hash-chain verification line. "
    "PDF via `python -m tracker.cli report --out track_record.pdf` (needs the [report] extra).",
)

theme.caveat_block(
    "Marking conventions: entry = next close after the call is logged (never same-day); "
    "stops take precedence when both levels are in range; marking is close-only; all "
    "prices are free public proxies, not licensed marks. Small-sample groups (n<20) "
    "show counts, not percentages."
)
theme.source_line("Source: tracker/ event log (hash-chained, git-committed) + point-in-time store.")
