"""Shared presentation helpers for the quant-toolkit pages.

Keeps the toolkit pages thin and consistent with the WSJ theme. Everything here is
*presentation* — page headers, turning a `Signal`/DataFrame into an Altair spec — so it
respects the app's zero-analytics rule (the maths lives in `quant/`).
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app import theme
from quant import store


def page_header(kicker: str, title: str, subtitle: str = "") -> None:
    st.markdown(f"<div class='page-kicker'>{kicker}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='page-title'>{title}</div>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f"<div class='chart-sub'>{subtitle}</div>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def series_with_data() -> list[str]:
    """Sorted series_ids that actually have observations in the store."""
    f = store.read_facts()
    return sorted(f["series_id"].unique())


def signal_frame(values: pd.Series) -> pd.DataFrame:
    """A date-indexed `Signal.values` (or any Series) → `[date, value]` for charting."""
    return pd.DataFrame({"date": pd.DatetimeIndex(values.index), "value": values.to_numpy()})


def contribution_bar(
    df: pd.DataFrame,
    *,
    label_field: str,
    value_field: str,
    height: int = 300,
) -> alt.Chart:
    """Horizontal bar with diverging colour (green up / brick down) — for decomposition
    contributions, regime stats, etc. Presentation only."""
    df = df.copy()
    df["_pos"] = df[value_field] >= 0
    fmt = ",.4f" if df[value_field].abs().max() < 10 else ",.2f"
    bars = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(f"{value_field}:Q", axis=alt.Axis(
                title=None, format=fmt, grid=True, gridColor=theme.RULE,
                domainColor=theme.INK, tickColor=theme.INK, labelColor=theme.INK_2)),
            y=alt.Y(f"{label_field}:N", sort=None, axis=alt.Axis(
                title=None, labelColor=theme.INK, labelFont=theme.FONT_SANS,
                labelFontSize=12, domainColor=theme.INK, ticks=False)),
            color=alt.condition(
                alt.datum._pos, alt.value(theme.POS), alt.value(theme.NEG)),
        )
    )
    return bars.properties(height=height, background=theme.SURFACE).configure_view(stroke=None)


def area_chart(
    df: pd.DataFrame,
    *,
    y_unit: str,
    color: str = theme.SERIES_1,
    height: int = 320,
) -> alt.Chart:
    """A filled area (equity curve / cumulative P&L). `df` is `[date, value]`."""
    df = df.dropna(subset=["value"]).sort_values("date")
    base = alt.Chart(df).encode(
        x=alt.X("date:T", axis=alt.Axis(title=None, grid=False, domainColor=theme.INK,
                                        tickColor=theme.INK, labelColor=theme.INK_2)),
        y=alt.Y("value:Q", axis=alt.Axis(title=y_unit, grid=True, gridColor=theme.RULE,
                                         domainColor=theme.INK, tickColor=theme.INK,
                                         labelColor=theme.INK_2),
                scale=alt.Scale(zero=False)),
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color=theme.INK_3, strokeWidth=1).encode(y="y:Q")
    area = base.mark_area(color=color, opacity=0.15, line={"color": color, "strokeWidth": 1.6})
    return (zero + area).properties(height=height, background=theme.SURFACE).configure_view(
        stroke=None)


def missing_note(missing: list[str]) -> None:
    if missing:
        theme.caveat_block(
            "Declared but not yet in the store (see docs/quant_data_gaps.md): "
            + ", ".join(missing) + "."
        )
