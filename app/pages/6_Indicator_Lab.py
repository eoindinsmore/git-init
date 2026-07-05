"""Leading-indicator lab — five FDR-gated tests, promote or reject.

Calls quant.indicators; the app renders the gate-by-gate verdicts. The graveyard is
part of the story: rejected candidates are shown with the gate they failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import theme  # noqa: E402
from app import toolkit_ui as ui  # noqa: E402
from quant.indicators import run_lab_from_store  # noqa: E402
from quant.indicators.lab import LabConfig  # noqa: E402

theme.configure_page("Indicator Lab")

ui.page_header(
    "Credibility core",
    "Leading-indicator lab",
    "Scan → Benjamini–Hochberg FDR (whole grid) → out-of-sample → economic → stability. "
    "A candidate is promoted only if it passes every gate.",
)

ids = ui.series_with_data()
default_target = "copper_price_global" if "copper_price_global" in ids else ids[0]
target = st.sidebar.selectbox("Target", ids, index=ids.index(default_target), key="lab_target")
default_cands = [s for s in [
    "copper_cot_mm_long", "copper_cot_mm_short", "copper_cot_prod_long",
    "us_industrial_production"] if s in ids][:4]
candidates = st.sidebar.multiselect(
    "Candidates", [s for s in ids if s != target], default=default_cands, key="lab_cands")
freq = st.sidebar.radio("Frequency", ["M", "W", "Q"], index=0, horizontal=True, key="lab_freq")
difference = st.sidebar.checkbox("First-difference (stationarity)", value=True, key="lab_diff")


@st.cache_data(show_spinner="Running the five gates…")
def _run(target, candidates, freq, difference):
    evals, missing = run_lab_from_store(
        target, list(candidates), freq=freq, difference=difference, config=LabConfig())
    rows = []
    for e in evals:
        row = {"candidate": e.candidate_id, "promoted": e.promoted,
               "best_lag": e.best_lag, "failed_gate": e.failed_gate or "—"}
        for gate in ["scan", "fdr", "oos", "economic", "stability"]:
            row[gate] = "✓" if (gate in e.gates and e.gates[gate].passed) else (
                "✗" if gate in e.gates else "·")
        rows.append(row)
    return pd.DataFrame(rows), missing


if not candidates:
    st.info("Pick at least one candidate in the sidebar to run the lab.")
    st.stop()

table, missing = _run(target, tuple(candidates), freq, difference)
ui.missing_note(missing)

promoted = table[table["promoted"]]
c1, c2 = st.columns(2)
c1.metric("Promoted", int(table["promoted"].sum()))
c2.metric("Rejected (graveyard)", int((~table["promoted"]).sum()))

st.markdown("---")
theme.title_block("Gate-by-gate verdicts", f"Target: {target} · {freq} · "
                  + ("differenced" if difference else "levels"))
st.dataframe(
    table, use_container_width=True, hide_index=True,
    column_config={"promoted": st.column_config.CheckboxColumn("promoted")},
)
theme.source_line("Source: quant.indicators.run_lab_from_store · "
                  "BH FDR across the candidate×lag grid.")

if not promoted.empty:
    theme.title_block("Promoted signals", "These carry a Signal + approved scorecard")
    st.dataframe(promoted[["candidate", "best_lag"]], use_container_width=True, hide_index=True)
