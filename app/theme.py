"""WSJ-inspired theme — colour tokens, page CSS, and Altair chart builders.

Follows the project DESIGN.md (Dona Wong / WSJ information-graphics principles):
warm paper ground, near-black ink, one accent per chart, hairline axes, no vertical
grid, direct last-point labels, a source line on every chart, tabular figures.

Building an Altair spec from a ``[date, value]`` frame is *presentation*, not
analytics, so this respects the app's zero-analytics layering rule.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

# --- Colour tokens (DESIGN.md §8) -------------------------------------------------
BG = "#F7F4EF"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#EFEBE3"
RULE = "#D8D2C6"
INK = "#1A1A17"
INK_2 = "#55514A"
INK_3 = "#8A857B"
SERIES_1 = "#0B4F6C"  # deep blue — primary
SERIES_2 = "#C1441E"  # brick red — contrast
POS = "#2C6E49"
NEG = "#A03217"
MUTED = "#B3ADA1"

# Colourblind-safe rotation for multi-series charts (blue / brick / muted / ink-2).
PALETTE = [SERIES_1, SERIES_2, INK_2, POS, MUTED]

FONT_SERIF = "Georgia, 'Times New Roman', serif"
FONT_SANS = "-apple-system, 'Helvetica Neue', Arial, sans-serif"


def configure_page(title: str) -> None:
    """``st.set_page_config`` + inject the WSJ CSS. Call once at the top of each page."""
    st.set_page_config(page_title=title, page_icon="▦", layout="wide")
    _inject_css()


def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{ background: {BG}; }}
        section.main > div {{ padding-top: 1.2rem; }}
        /* Editorial serif statement titles */
        .chart-title {{
            font-family: {FONT_SERIF}; font-size: 20px; font-weight: 600;
            color: {INK}; line-height: 1.25; margin: 0.2rem 0 0.1rem 0;
        }}
        .chart-title-sm {{
            font-family: {FONT_SERIF}; font-size: 15px; font-weight: 600;
            color: {INK}; line-height: 1.2; margin: 0.1rem 0 0.05rem 0;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .chart-sub {{ font-family: {FONT_SANS}; font-size: 13px; color: {INK_2};
            margin: 0 0 0.4rem 0; }}
        /* Tighten segmented-control button rows (region / category) */
        div[data-testid="stButtonGroup"] {{ margin-bottom: 0.1rem; }}
        .chart-source {{ font-family: {FONT_SANS}; font-size: 11px; color: {INK_3};
            margin-top: 0.35rem; }}
        .page-title {{ font-family: {FONT_SERIF}; font-size: 30px; font-weight: 600;
            color: {INK}; margin-bottom: 0.1rem; }}
        .page-kicker {{ font-family: {FONT_SANS}; font-size: 12px; letter-spacing: 0.08em;
            text-transform: uppercase; color: {INK_3}; margin-bottom: 0.6rem; }}
        .caveat {{ font-family: {FONT_SANS}; font-size: 12px; color: {INK_2};
            background: {SURFACE_ALT}; border-left: 3px solid {MUTED};
            padding: 0.5rem 0.7rem; margin: 0.4rem 0; border-radius: 2px; }}
        .body, .stMarkdown p {{ font-family: {FONT_SANS}; color: {INK_2}; }}
        h1, h2, h3 {{ font-family: {FONT_SERIF}; color: {INK}; }}
        [data-testid="stMetricValue"], .stDataFrame, table {{
            font-variant-numeric: tabular-nums; }}
        /* Quiet the sidebar to paper tones */
        section[data-testid="stSidebar"] {{ background: {SURFACE_ALT};
            border-right: 1px solid {RULE}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _num_format(sample: float) -> str:
    """d3 format: no-decimal for index/contract magnitudes, 2dp for small (premiums)."""
    return ",.0f" if abs(sample) >= 100 else ",.2f"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    return df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)


# Axis tick date format by series frequency (d3-time-format):
#   daily/weekly -> DD-MMM, monthly/quarterly -> MMM-YY, annual -> YYYY.
_X_FORMAT: dict[str, str] = {"D": "%d-%b", "W": "%d-%b", "M": "%b-%y", "Q": "%b-%y", "A": "%Y"}


def x_time_format(frequency: str) -> str:
    """d3 time-format string for the x-axis, chosen by the series' frequency."""
    return _X_FORMAT.get(frequency, "%b-%y")


def date_format(frequency: str, df: pd.DataFrame | None = None) -> str:
    """Span-aware x-axis date format.

    Annual -> YYYY; monthly/quarterly -> MMM-YY; daily/weekly -> DD-MMM for a short
    window (≤ ~1 year) but MMM-YY over a longer span, so a year-less DD-MMM label never
    repeats ambiguously across multiple January boundaries.
    """
    if frequency == "A":
        return "%Y"
    if frequency in ("M", "Q"):
        return "%b-%y"
    if df is None or df.empty:
        return "%d-%b"
    span_days = (df["date"].max() - df["date"].min()).days
    return "%d-%b" if span_days <= 400 else "%b-%y"


def _y_axis(unit: str, fmt: str) -> alt.Axis:
    """Left axis: black domain line, outside ticks, hairline horizontal grid."""
    return alt.Axis(
        title=unit, titleColor=INK_2, titleFont=FONT_SANS, titleFontSize=12,
        labelColor=INK_2, labelFont=FONT_SANS, labelFontSize=12, format=fmt,
        grid=True, gridColor=RULE, gridWidth=0.6,
        domain=True, domainColor=INK, domainWidth=1,
        ticks=True, tickColor=INK, tickWidth=1, tickSize=5, tickCount=5,
    )


def _x_axis(x_format: str, tick_count: int | None = None) -> alt.Axis:
    """Bottom axis: black domain line, outside ticks, frequency-aware date labels.

    ``tick_count`` thins ticks on narrow (grid) charts so date labels don't collide.
    """
    return alt.Axis(
        title=None, labelColor=INK_2, labelFont=FONT_SANS, labelFontSize=12,
        grid=False, format=x_format, formatType="time", labelOverlap="greedy",
        labelPadding=6, tickCount=tick_count if tick_count is not None else alt.Undefined,
        domain=True, domainColor=INK, domainWidth=1,
        ticks=True, tickColor=INK, tickWidth=1, tickSize=5,
    )


def line_chart(
    df: pd.DataFrame,
    *,
    y_unit: str,
    color: str = SERIES_1,
    show_zero: bool = False,
    value_fmt: str | None = None,
    x_format: str = "%b-%y",
    x_tick_count: int | None = None,
    height: int = 340,
) -> alt.LayerChart | alt.Chart:
    """A single-series WSJ line: black axes with outside ticks, hairline y-grid,
    highlighted last observation (marker + value label).

    ``show_zero`` draws a baseline (growth-rate views that cross zero). ``value_fmt``
    overrides the end-label number format; ``x_format`` is the d3 date format for ticks.
    """
    df = _clean(df)
    if df.empty:
        return _empty(height)

    fmt = value_fmt or _num_format(df["value"].iloc[-1])
    base = alt.Chart(df).encode(
        x=alt.X("date:T", axis=_x_axis(x_format, x_tick_count)),
        y=alt.Y("value:Q", axis=_y_axis(y_unit, fmt), scale=alt.Scale(zero=False)),
    )
    layers: list[alt.Chart] = []
    if show_zero:
        layers.append(
            alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
                color=INK_3, strokeWidth=1.0
            ).encode(y="y:Q")
        )
    layers.append(base.mark_line(color=color, strokeWidth=1.6))
    # Direct label on the final point (no legend needed for one series).
    last = df.iloc[[-1]]
    layers.append(
        alt.Chart(last).mark_point(color=color, size=28, filled=True).encode(
            x="date:T", y="value:Q"
        )
    )
    layers.append(
        alt.Chart(last).mark_text(
            align="left", dx=7, color=color, font=FONT_SANS, fontSize=12, fontWeight=600
        ).encode(x="date:T", y="value:Q", text=alt.Text("value:Q", format=fmt))
    )
    return _finish(alt.layer(*layers), height)


def multi_line_chart(
    df_long: pd.DataFrame,
    *,
    y_unit: str,
    color_field: str = "series",
    show_zero: bool = False,
    x_format: str = "%b-%y",
    height: int = 360,
) -> alt.Chart:
    """Multi-series line (long-format: date, value, <color_field>) with direct labels."""
    df_long = df_long.dropna(subset=["value"]).sort_values("date")
    if df_long.empty:
        return _empty(height)

    fmt = _num_format(df_long["value"].abs().max())
    series_names = list(df_long[color_field].unique())
    scale = alt.Scale(domain=series_names, range=PALETTE[: len(series_names)])
    base = alt.Chart(df_long).encode(
        x=alt.X("date:T", axis=_x_axis(x_format)),
        y=alt.Y("value:Q", axis=_y_axis(y_unit, fmt), scale=alt.Scale(zero=False)),
        color=alt.Color(f"{color_field}:N", scale=scale, legend=None),
    )
    layers: list[alt.Chart] = []
    if show_zero:
        layers.append(
            alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
                color=INK_3, strokeWidth=1.0
            ).encode(y="y:Q")
        )
    layers.append(base.mark_line(strokeWidth=1.5))
    last = df_long.sort_values("date").groupby(color_field, as_index=False).last()
    layers.append(
        alt.Chart(last).mark_text(
            align="left", dx=7, font=FONT_SANS, fontSize=11, fontWeight=600
        ).encode(
            x="date:T", y="value:Q", text=f"{color_field}:N",
            color=alt.Color(f"{color_field}:N", scale=scale, legend=None),
        )
    )
    return _finish(alt.layer(*layers), height)


def _finish(chart: alt.LayerChart, height: int) -> alt.LayerChart:
    return (
        chart.properties(height=height, background=SURFACE)
        .configure_view(stroke=None)
        .configure_axisX(labelPadding=6)
    )


def _empty(height: int) -> alt.Chart:
    """A faint hairline empty-state (DESIGN.md: skeleton, never a spinner)."""
    return alt.Chart(pd.DataFrame({"date": [], "value": []})).mark_line().encode(
        x="date:T", y="value:Q"
    ).properties(height=height, background=SURFACE).configure_view(
        stroke=RULE, strokeWidth=0.6
    )


def title_block(title: str, subtitle: str, *, compact: bool = False) -> None:
    """Render a WSJ chart header: serif title + sans subtitle/unit.

    ``compact`` uses a smaller title for grid/tiled charts.
    """
    cls = "chart-title-sm" if compact else "chart-title"
    st.markdown(f"<div class='{cls}'>{title}</div>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f"<div class='chart-sub'>{subtitle}</div>", unsafe_allow_html=True)


def source_line(text: str) -> None:
    st.markdown(f"<div class='chart-source'>{text}</div>", unsafe_allow_html=True)


def caveat_block(text: str) -> None:
    st.markdown(f"<div class='caveat'>⚠ {text}</div>", unsafe_allow_html=True)
