"""Nowcasting — bridge equations, accuracy-vs-information, benchmark comparison.

Calls quant.nowcast; the app renders the accuracy curve and the mandatory naive-benchmark
comparison. Needs a slow-release target paired with faster indicators (data is thin — see
docs/quant_data_gaps.md)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import altair as alt  # noqa: E402
import streamlit as st  # noqa: E402

from app import theme  # noqa: E402
from app import toolkit_ui as ui  # noqa: E402
from quant.nowcast import (  # noqa: E402
    accuracy_vs_information,
    benchmark_comparison,
    fit_from_store,
)

theme.configure_page("Nowcast")

ui.page_header(
    "What did you know, and when?",
    "Nowcasting",
    "Bridge equations: a low-frequency target regressed on time-aggregated higher-frequency "
    "indicators, updated as inputs release. Evaluated against naive benchmarks.",
)

ids = ui.series_with_data()
default_target = "copper_price_global" if "copper_price_global" in ids else ids[0]
target = st.sidebar.selectbox("Target (slow)", ids, index=ids.index(default_target),
                              key="nc_target")
default_inds = [s for s in ["copper_cot_mm_long", "copper_cot_prod_long"] if s in ids]
indicators = st.sidebar.multiselect(
    "Indicators (fast)", [s for s in ids if s != target], default=default_inds, key="nc_inds")


@st.cache_data(show_spinner="Fitting the bridge…")
def _run(target, indicators):
    setup = fit_from_store(target, list(indicators))
    acc = accuracy_vs_information(setup.model, setup.target, setup.indicator_data,
                                 step_days=15, max_days=120)
    cmp = benchmark_comparison(setup.model, setup.target, setup.indicator_data,
                               days_into_period=95)
    return setup, acc, cmp


if not indicators:
    st.info("Pick at least one indicator in the sidebar to fit the bridge.")
    st.stop()

try:
    setup, acc, cmp = _run(target, tuple(indicators))
except ValueError as e:
    st.warning(f"Could not fit the bridge: {e}")
    st.stop()

c1, c2 = st.columns(2)
c1.metric("Periods fitted", setup.model.nobs)
c2.metric("Indicators used", len(setup.used))
ui.missing_note(setup.missing)
st.markdown("---")

left, right = st.columns([3, 2])
with left:
    theme.title_block("Accuracy vs information", "MAE as more of the period is observed")
    acc_plot = acc.dropna(subset=["mae"])
    if not acc_plot.empty:
        chart = alt.Chart(acc_plot).mark_line(color=theme.SERIES_1, point=True).encode(
            x=alt.X("days_into_period:Q", axis=alt.Axis(title="days into period",
                    domainColor=theme.INK, tickColor=theme.INK, labelColor=theme.INK_2)),
            y=alt.Y("mae:Q", axis=alt.Axis(title="MAE", grid=True, gridColor=theme.RULE,
                    domainColor=theme.INK, tickColor=theme.INK, labelColor=theme.INK_2)),
        ).properties(height=320, background=theme.SURFACE).configure_view(stroke=None)
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("Not enough coverage to trace the accuracy curve.")

with right:
    theme.title_block("Vs naive benchmarks", "Mean absolute error (fully-informed)")
    row = cmp.iloc[0]
    st.dataframe(
        [{"forecast": k, "MAE": round(float(row[k]), 2)} for k in cmp.columns],
        use_container_width=True, hide_index=True,
    )
    beat = row["nowcast"] < row.get("last_value", float("inf"))
    st.caption("✓ Beats last-value RW" if beat else
               "✗ Does not beat the random walk here (honest negative — see data-gaps).")

theme.source_line("Source: quant.nowcast · bridge equations, mean aggregation ragged-edge fill.")
