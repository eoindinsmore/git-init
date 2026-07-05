"""Home Hedge Fund — chart dashboard (grid of charts).

Run with:  .venv/Scripts/python -m streamlit run app/Home.py

Two rows of buttons across the top filter the grid: region (row 1), category (row 2).
The left panel sets the date range. Each tile shows a series in its default view.

Charter layering: reads the point-in-time store + registry and calls quant.transforms
for each tile's default view. No analytics in the app.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from app import controls, theme  # noqa: E402
from app import data_access as da  # noqa: E402
from quant import transforms as tf  # noqa: E402

theme.configure_page("Chart Dashboard")

reg = da.registry()
in_store = da.series_ids_in_store()
specs_in_store = [reg[s] for s in sorted(in_store) if s in reg]

st.markdown("<div class='page-kicker'>Commodities research · free/public data</div>",
            unsafe_allow_html=True)
st.markdown("<div class='page-title'>Chart Dashboard</div>", unsafe_allow_html=True)

# --- Two button rows across the top: region, then category ------------------------
region, category = controls.filter_bar(specs_in_store, "dash")

# --- Left panel: date range -------------------------------------------------------
months = controls.horizon_picker("dash_hz", default="24", sidebar=True)
st.sidebar.markdown("---")
st.sidebar.caption(
    "Tiles show each series' default view (registry). Open **Chart Focus** to change "
    "the transformation or view a single series point-in-time."
)

selected = [s.series_id for s in specs_in_store if controls.matches(s, region, category)]

st.markdown(
    f"<div class='chart-sub'>{len(selected)} series · region <b>{region}</b> · "
    f"category <b>{category.title()}</b></div>",
    unsafe_allow_html=True,
)
st.markdown("---")

if not selected:
    st.info("No series match this region / category combination.")
    st.stop()

# --- Grid: charts side by side ----------------------------------------------------
NCOLS = 3
cols = st.columns(NCOLS)
for i, sid in enumerate(selected):
    spec = reg[sid]
    with cols[i % NCOLS]:
        kind = tf.default_kind(spec.transformations)
        unit = tf.unit_label(kind, spec.unit)
        raw = da.get_series(sid)
        shown = controls.clip_horizon(tf.apply(raw, kind, spec.frequency.value), months)
        theme.title_block(spec.name, f"{tf.LABELS[kind]} · {unit}", compact=True)
        if shown.empty:
            st.info("No data in range.")
        else:
            chart = theme.line_chart(
                shown, y_unit=unit, show_zero=(kind != "level"),
                value_fmt=".1f" if kind.endswith("_pct") else None,
                x_format=theme.date_format(spec.frequency.value, shown),
                x_tick_count=4, height=230,
            )
            st.altair_chart(chart, use_container_width=True)
        theme.source_line(f"Source: {spec.source} · {sid}")
        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
