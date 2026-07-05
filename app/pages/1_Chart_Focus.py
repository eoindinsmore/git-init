"""Chart Focus — one series in depth: dropdown of all series, transform toggle, and
point-in-time view. The same two button rows (region, category) filter the dropdown.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import controls, theme  # noqa: E402
from app import data_access as da  # noqa: E402
from quant import transforms as tf  # noqa: E402

theme.configure_page("Chart Focus")

reg = da.registry()
in_store = da.series_ids_in_store()
specs_in_store = [reg[s] for s in sorted(in_store) if s in reg]

st.markdown("<div class='page-kicker'>Chart Focus</div>", unsafe_allow_html=True)
st.markdown("<div class='page-title'>Single-series focus</div>", unsafe_allow_html=True)

# --- Two button rows across the top filter the series dropdown --------------------
region, category = controls.filter_bar(specs_in_store, "focus")
candidates = [s.series_id for s in specs_in_store if controls.matches(s, region, category)]

if not candidates:
    st.warning("No series match this region / category combination.")
    st.stop()

series_id = st.selectbox(
    "Series", candidates, format_func=lambda sid: f"{reg[sid].name}  ·  {sid}",
)
spec = reg[series_id]

# --- Transform (main) -------------------------------------------------------------
default_kind = tf.default_kind(spec.transformations)
kind = controls.transform_picker(f"tf_{series_id}", default_kind)

# --- Left panel: date range + point-in-time --------------------------------------
months = controls.horizon_picker("focus_hz", default="120", sidebar=True)
st.sidebar.markdown("---")
lo, hi = da.as_of_bounds(series_id)
as_of = None
has_vintages = lo is not None and hi is not None and lo.date() < hi.date()
if has_vintages and st.sidebar.checkbox("Point-in-time (as of a past date)", value=False):
    as_of = pd.Timestamp(st.sidebar.date_input(
        "as_of", value=hi.date(), min_value=lo.date(), max_value=hi.date(),
        help="Show data exactly as it was known on this date (latest vintage ≤ as_of).",
    ))

# --- Fetch (point-in-time) -> transform (quant) -> clip --------------------------
raw = da.get_series(series_id, as_of=as_of)
transformed = tf.apply(raw, kind, spec.frequency.value)  # analytics lives in quant
shown = controls.clip_horizon(transformed, months)

# --- Render (WSJ) ----------------------------------------------------------------
unit = tf.unit_label(kind, spec.unit)
sub = f"{tf.LABELS[kind]} · {unit} · {spec.frequency.value} · {spec.sa_status.value}"
if as_of is not None:
    sub += f" · as of {as_of.date().isoformat()}"
theme.title_block(spec.name, sub)

if shown.empty:
    st.info("No observations for this series / window. Try a longer range or 'Level'.")
else:
    value_fmt = ".1f" if kind.endswith("_pct") else None
    chart = theme.line_chart(
        shown, y_unit=unit, show_zero=(kind != "level"), value_fmt=value_fmt,
        x_format=theme.date_format(spec.frequency.value, shown), height=420,
    )
    st.altair_chart(chart, use_container_width=True)

if spec.caveats:
    theme.caveat_block(spec.caveats)

theme.source_line(
    f"Source: {spec.source} · {spec.source_code} · series_id {series_id}"
    + (f" · vintage as of {as_of.date().isoformat()}" if as_of is not None else "")
)
if spec.transformations and kind == default_kind:
    theme.source_line(f"Default view for this series: {tf.LABELS[kind]} (registry).")
