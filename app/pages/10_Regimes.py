"""Regime identification — transparent, rule-based, with consumption hooks.

Calls quant.regimes (analytics). The canonical global-macro states (VIX / PMI / USD) are
not yet ingested, so this page demonstrates the engine on an available price series via a
trend rule, then shows the transition matrix and per-regime conditional performance."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import data_access as da  # noqa: E402
from app import theme  # noqa: E402
from app import toolkit_ui as ui  # noqa: E402
from quant.decomp import to_returns  # noqa: E402
from quant.regimes import (  # noqa: E402
    classify,
    conditional_performance,
    ma_trend,
    regime_banner,
    sizing_multiplier,
    transition_matrix,
)

theme.configure_page("Regimes")

_PPY = {"D": 252, "W": 52, "M": 12, "Q": 4, "A": 1}

ui.page_header(
    "Market state",
    "Regime identification",
    "Rule-based (auditable, no estimation instability). Below: a trend regime on a chosen "
    "series, its transition matrix, and returns conditional on the regime.",
)

theme.caveat_block(
    "The canonical global-macro regime (VIX band × PMI level/Δ × USD vs 200d) needs VIX, "
    "global PMI and a broad-USD series — not yet ingested (see docs/quant_data_gaps.md). "
    "This page demonstrates the engine on a price-trend state variable instead."
)

reg = da.registry()
ids = ui.series_with_data()
default = "copper_price_global" if "copper_price_global" in ids else ids[0]
sid = st.sidebar.selectbox("State / asset series", ids, index=ids.index(default), key="rg_series")
window = st.sidebar.slider("Trend window (periods)", 6, 60, 12, key="rg_window")


@st.cache_data(show_spinner="Classifying…")
def _run(sid: str, window: int):
    df = da.get_series(sid)
    px = pd.Series(df["value"].to_numpy(), index=pd.DatetimeIndex(df["date"]))
    regimes = classify({"trend": ma_trend(px, window=window)})
    rets = to_returns(px, "log")
    ppy = _PPY.get(reg[sid].frequency.value, 12)
    perf = conditional_performance(regimes, rets, periods_per_year=ppy)
    trans = transition_matrix(regimes)
    banner = regime_banner(regimes)
    return regimes, perf, trans, banner


regimes, perf, trans, banner = _run(sid, window)

# Current-regime banner + a sample sizing-multiplier consumption hook.
mult = sizing_multiplier(str(banner["regime"]),
                         {"trend=up": 1.25, "trend=down": 0.5}, default=1.0)
c1, c2, c3 = st.columns(3)
c1.metric("Current regime", str(banner["regime"] or "—"))
c2.metric("As of", str(banner["as_of"].date()) if banner["as_of"] is not None else "—")
c3.metric("Sizing multiplier", f"{mult:.2f}×", help="Consumption hook: a risk dial for the tracker")

st.markdown("---")
left, right = st.columns(2)
with left:
    theme.title_block("Conditional performance", "Returns by regime (annualised)")
    st.dataframe(
        perf, use_container_width=True, hide_index=True,
        column_config={
            "mean_ann": st.column_config.NumberColumn("mean", format="%.3f"),
            "vol_ann": st.column_config.NumberColumn("vol", format="%.3f"),
            "sharpe_ann": st.column_config.NumberColumn("Sharpe", format="%.2f"),
            "hit_rate": st.column_config.NumberColumn("hit", format="%.2f"),
        },
    )
with right:
    theme.title_block("Transition matrix", "Row-normalized regime persistence")
    st.dataframe(trans.round(2), use_container_width=True)

theme.source_line(
    f"Source: quant.regimes · trend rule (price vs {window}-period MA) on {sid}.")
