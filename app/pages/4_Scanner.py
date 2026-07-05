"""Dislocation scanner — a *visual* daily idea-generation screen, with promote-to-tracker.

Calls quant.scanner (analytics) and renders the dislocation as a map, a time series and
per-item cards — the app itself does no maths. One click promotes a flagged item to a
draft hypothesis in the append-only tracker.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import data_access as da  # noqa: E402
from app import theme  # noqa: E402
from app import toolkit_ui as ui  # noqa: E402
from quant.scanner import (  # noqa: E402
    load_named,
    promote_flag,
    run_mahalanobis_timeseries,
    run_scan,
)
from tracker import store as tracker_store  # noqa: E402

theme.configure_page("Scanner")

ui.page_header(
    "Idea generation",
    "Dislocation scanner",
    "Where is the universe stretched? Every series is placed by how far its level and its "
    "recent move sit from normal; the joint screen flags unusual combinations. Flagged "
    "items promote to the trade tracker in one click.",
)


@st.cache_data(show_spinner="Scanning the universe…")
def _scan():
    return run_scan(load_named("base"))


@st.cache_data(show_spinner=False)
def _mahal_ts():
    return run_mahalanobis_timeseries(load_named("base"), window=104)


res = _scan()

c1, c2, c3 = st.columns(3)
c1.metric("As of", str(res.as_of.date()) if res.as_of is not None else "—")
c2.metric("Items scanned", len(res.table))
c3.metric(
    "Joint Mahalanobis",
    "—" if res.mahalanobis is None else f"{res.mahalanobis:.2f}",
    help="Distance of the latest joint move vs history; "
    + ("" if res.mahalanobis_pvalue is None else f"chi-square p = {res.mahalanobis_pvalue:.3f}"),
)

if res.table.empty:
    st.info("No items had enough history to scan.")
    st.stop()

# --- The dislocation map (headline) -----------------------------------------------
st.markdown("---")
theme.title_block("The dislocation map",
                  "Return z-score (x) vs level z-score (y) · size = |z| · brick = flagged")
st.altair_chart(ui.universe_scatter(res.table), use_container_width=True)
theme.source_line("Source: quant.scanner over the 'base' universe. Dashed guides at ±2σ; "
                  "series in the corners are stretched on both axes.")

# --- Joint dislocation over time --------------------------------------------------
mts = _mahal_ts()
if not mts.empty:
    st.markdown("---")
    theme.title_block("Joint dislocation over time",
                      "Rolling Mahalanobis distance of the universe's core move")
    df_m = pd.DataFrame({"date": pd.DatetimeIndex(mts.index), "value": mts.to_numpy()})
    st.altair_chart(theme.line_chart(df_m, y_unit="Mahalanobis distance", x_format="%b-%y"),
                    use_container_width=True)
    p95 = float(mts.quantile(0.95))
    latest = float(mts.iloc[-1])
    st.caption(f"Latest {latest:.2f} vs its own 95th percentile {p95:.2f} — "
               + ("**elevated**." if latest >= p95 else "within normal range."))

# --- Per-item detail --------------------------------------------------------------
st.markdown("---")
theme.title_block("Inspect a series", "Price, and how stretched each measure is")
items = res.table["item"].tolist()
flagged = res.table[res.table["flag"]]["item"].tolist()
default_ix = items.index(flagged[0]) if flagged else 0
item = st.selectbox("Series", items, index=default_ix, key="scan_item")
row = res.table[res.table["item"] == item].iloc[0]

left, right = st.columns([3, 2])
with left:
    lv = da.get_series(item) if item in da.series_ids_in_store() else pd.DataFrame()
    if not lv.empty:
        theme.title_block(item, "Level · point-in-time", compact=True)
        st.altair_chart(theme.line_chart(lv[["date", "value"]].tail(260),
                                         y_unit="level", x_format="%b-%y", height=240),
                        use_container_width=True)
    else:
        st.caption("(derived item — no single stored level to chart)")
with right:
    m1, m2 = st.columns(2)
    m1.metric("Last", f"{float(row['value']):.4g}")
    m2.metric("|z| (headline)", f"{float(row['abs_z']):.2f}")
    m3, m4 = st.columns(2)
    zl = row.get("z_level_60")
    zr = row.get("z_ret_20")
    m3.metric("Level (z, 60)", "—" if pd.isna(zl) else f"{float(zl):+.2f}",
              help="How far the level sits from its trailing mean, in σ.")
    m4.metric("Move (z, 20)", "—" if pd.isna(zr) else f"{float(zr):+.2f}",
              help="Standardised recent rate-of-change (embeds volatility).")
    pr = row.get("pct_rank_250")
    if pd.notna(pr):
        st.metric("Percentile rank (250)", f"{float(pr):.0f}")
    st.caption("A high move-z with a small raw move implies low volatility, and vice-versa "
               "— the z-score already divides the move by its trailing volatility.")

# --- Promote to tracker -----------------------------------------------------------
st.markdown("---")
theme.title_block("Promote to tracker", "Draft a hypothesis from a flagged dislocation")
promote_from = flagged or items
col_a, col_b = st.columns([3, 1])
pick = col_a.selectbox("Flagged item", promote_from, key="promote_item")
if col_b.button("Promote →", use_container_width=True):
    h = promote_flag(res, pick)
    st.success(f"Drafted hypothesis `{h.hypothesis_id}` (direction: {h.direction.value}).")

view = tracker_store.current_view()
if not view.empty:
    with st.expander("Draft hypotheses (append-only)"):
        cols = [c for c in ["hypothesis_id", "instrument", "direction", "status",
                            "source", "created_as_of"] if c in view.columns]
        st.dataframe(view[cols], use_container_width=True, hide_index=True)

with st.expander("Full ranked table"):
    show_cols = [c for c in ["item", "value", "abs_z", "flag", "new_flag",
                             "z_level_60", "z_ret_20", "pct_rank_250"] if c in res.table.columns]
    st.dataframe(
        res.table[show_cols].head(50), use_container_width=True, hide_index=True,
        column_config={
            "abs_z": st.column_config.NumberColumn("|z|", format="%.2f"),
            "value": st.column_config.NumberColumn("Last", format="%.4g"),
            "z_level_60": st.column_config.NumberColumn("z lvl 60", format="%.2f"),
            "z_ret_20": st.column_config.NumberColumn("z ret 20", format="%.2f"),
            "pct_rank_250": st.column_config.NumberColumn("pct rank", format="%.0f"),
        },
    )
theme.source_line("Source: tracker/ append-only JSONL (charter constraint #6 — immutable).")
