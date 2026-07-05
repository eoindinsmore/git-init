"""Dislocation scanner — daily idea-generation screen, with promote-to-tracker.

Calls quant.scanner (analytics) and renders the ranked table; the app itself does no
maths. One click promotes a flagged row to a draft hypothesis in the append-only tracker.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app import theme  # noqa: E402
from app import toolkit_ui as ui  # noqa: E402
from quant.scanner import load_named, promote_flag, run_scan  # noqa: E402
from tracker import store as tracker_store  # noqa: E402

theme.configure_page("Scanner")

ui.page_header(
    "Idea generation",
    "Dislocation scanner",
    "Rolling z-scores of levels and returns across the universe, plus a Mahalanobis "
    "check on the joint move. Flagged rows promote to the trade tracker in one click.",
)


@st.cache_data(show_spinner="Scanning the universe…")
def _scan():
    return run_scan(load_named("base"))


res = _scan()

c1, c2, c3 = st.columns(3)
c1.metric("As of", str(res.as_of.date()) if res.as_of is not None else "—")
c2.metric("Items scanned", len(res.table))
c3.metric(
    "Joint Mahalanobis",
    "—" if res.mahalanobis is None else f"{res.mahalanobis:.2f}",
    help="Distance of the latest joint move vector vs history; "
    + ("" if res.mahalanobis_pvalue is None else f"chi-square p = {res.mahalanobis_pvalue:.3f}"),
)

st.markdown("---")
theme.title_block("Ranked dislocations", "Top of the screen by |z|; new flags in bold")

if res.table.empty:
    st.info("No items had enough history to scan.")
    st.stop()

show_cols = [c for c in ["item", "value", "abs_z", "flag", "new_flag",
                         "z_level_60", "z_ret_20", "pct_rank_250"] if c in res.table.columns]
table = res.table[show_cols].head(25).copy()
st.dataframe(
    table,
    use_container_width=True,
    hide_index=True,
    column_config={
        "abs_z": st.column_config.NumberColumn("|z|", format="%.2f"),
        "value": st.column_config.NumberColumn("Last", format="%.4g"),
        "z_level_60": st.column_config.NumberColumn("z lvl 60", format="%.2f"),
        "z_ret_20": st.column_config.NumberColumn("z ret 20", format="%.2f"),
        "pct_rank_250": st.column_config.NumberColumn("pct rank", format="%.0f"),
    },
)
theme.source_line("Source: quant.scanner over the 'base' universe "
                  "(registry price/positioning series).")

# --- Promote to tracker -----------------------------------------------------------
st.markdown("---")
theme.title_block("Promote to tracker", "Draft a hypothesis from a flagged dislocation")
flagged = res.table[res.table["flag"]]["item"].tolist() or res.table["item"].tolist()
col_a, col_b = st.columns([3, 1])
pick = col_a.selectbox("Flagged item", flagged, key="promote_item")
if col_b.button("Promote →", use_container_width=True):
    h = promote_flag(res, pick)
    st.success(f"Drafted hypothesis `{h.hypothesis_id}` (direction: {h.direction.value}).")

view = tracker_store.current_view()
if not view.empty:
    theme.title_block("Trade tracker", "Append-only; latest record per hypothesis")
    cols = [c for c in ["hypothesis_id", "instrument", "direction", "status",
                        "source", "created_as_of"] if c in view.columns]
    st.dataframe(view[cols], use_container_width=True, hide_index=True)
    theme.source_line("Source: tracker/ append-only JSONL (charter constraint #6 — immutable).")
