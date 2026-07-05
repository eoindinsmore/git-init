"""Composite indicators — aggregate many series into one Signal.

Calls quant.composites; the app plots the resulting Signal. The point-in-time PCA
composite is built with no look-ahead (loadings estimated up to each date)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app import data_access as da  # noqa: E402
from app import theme  # noqa: E402
from app import toolkit_ui as ui  # noqa: E402
from quant.composites import build_composite, load_named  # noqa: E402

theme.configure_page("Composites")

ui.page_header(
    "Aggregation",
    "Composite indicators",
    "Diffusion index, coverage-weighted z-score, or point-in-time PCA. A composite is "
    "itself a Signal — it carries provenance and a worst-case publication lag.",
)

SPECS = ["positioning_copper"]
name = st.sidebar.selectbox("Composite", SPECS, key="comp_spec")


@st.cache_data(show_spinner="Building the composite…")
def _build(spec_name: str):
    build = build_composite(load_named(spec_name), as_of=None, registry=da.registry())
    return build, ui.signal_frame(build.signal.values)


build, frame = _build(name)
sig = build.signal

c1, c2, c3 = st.columns(3)
c1.metric("Method", build.method.upper())
c2.metric("Components", len(build.used))
c3.metric("Publication lag", f"{sig.publication_lag_days}d")

ui.missing_note(build.missing)
st.markdown(
    f"<div class='chart-sub'>{sig.construction}<br>Provenance: "
    f"{', '.join(sig.provenance)}</div>", unsafe_allow_html=True)
st.markdown("---")

theme.title_block(sig.signal_id, sig.direction_convention)
st.altair_chart(
    theme.line_chart(frame, y_unit="composite (z)", show_zero=True,
                     x_format=theme.date_format("W", frame)),
    use_container_width=True,
)
theme.source_line(f"Source: quant.composites · {build.method} · "
                  "sign-fixed, point-in-time loadings.")
