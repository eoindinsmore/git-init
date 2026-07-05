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


# --- Workbench helpers (presentation only) ----------------------------------------

def scatter_chart(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    x_title: str,
    y_title: str,
    color: str | None = None,
    fit: bool = True,
    height: int = 320,
) -> alt.Chart:
    """Scatter of ``y`` vs ``x`` with an optional OLS fit line (Altair's own regression
    transform — a drawing aid, not a stored analytic). Optional ``color`` field (e.g.
    regime or time bucket)."""
    df = df.dropna(subset=[x, y])
    enc = dict(
        x=alt.X(f"{x}:Q", axis=alt.Axis(title=x_title, grid=True, gridColor=theme.RULE,
                                        domainColor=theme.INK, tickColor=theme.INK,
                                        labelColor=theme.INK_2)),
        y=alt.Y(f"{y}:Q", axis=alt.Axis(title=y_title, grid=True, gridColor=theme.RULE,
                                        domainColor=theme.INK, tickColor=theme.INK,
                                        labelColor=theme.INK_2)),
    )
    if color:
        names = list(pd.Series(df[color]).astype(str).unique())
        enc["color"] = alt.Color(f"{color}:N", scale=alt.Scale(
            domain=names, range=theme.PALETTE[: len(names)]),
            legend=alt.Legend(title=None, orient="top"))
    pts = alt.Chart(df).mark_circle(size=42, opacity=0.55, color=theme.SERIES_1).encode(**enc)
    layers = [pts]
    if fit:
        line = alt.Chart(df).transform_regression(x, y).mark_line(
            color=theme.INK, strokeWidth=1.4).encode(x=f"{x}:Q", y=f"{y}:Q")
        layers.append(line)
    zero_x = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
        color=theme.INK_3, strokeWidth=0.6).encode(x="x:Q")
    zero_y = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color=theme.INK_3, strokeWidth=0.6).encode(y="y:Q")
    return alt.layer(zero_x, zero_y, *layers).properties(
        height=height, background=theme.SURFACE).configure_view(stroke=None)


def stacked_contribution_area(
    cumulative: pd.DataFrame,
    *,
    labels: dict[str, str],
    residual_col: str,
    drift_col: str,
    height: int = 360,
) -> alt.Chart:
    """Stacked area of the cumulative per-driver contributions over time (spec:
    decomp_timeseries). Each band is a component's running contribution to the cumulative
    move; they stack to the total, with the residual band closing to the actual path.

    ``cumulative`` is the ContributionSeries.cumulative frame; ``labels`` maps column →
    display name. Presentation only — the maths is quant.decomp.contribution_timeseries."""
    cols = list(cumulative.columns)
    long = (cumulative.reset_index(names="date")
            .melt(id_vars="date", var_name="component", value_name="value"))
    long["label"] = long["component"].map(lambda c: labels.get(c, c))

    # Colour: drift muted-ink, residual muted-grey, drivers the accent palette.
    order = cols
    palette = {}
    di = 0
    for c in order:
        if c == drift_col:
            palette[labels.get(c, c)] = theme.INK_2
        elif c == residual_col:
            palette[labels.get(c, c)] = theme.MUTED
        else:
            palette[labels.get(c, c)] = theme.PALETTE[di % len(theme.PALETTE)]
            di += 1
    dom = [labels.get(c, c) for c in order]

    area = alt.Chart(long).mark_area(opacity=0.85).encode(
        x=alt.X("date:T", axis=alt.Axis(title=None, grid=False, domainColor=theme.INK,
                                        tickColor=theme.INK, labelColor=theme.INK_2)),
        y=alt.Y("value:Q", stack="zero", axis=alt.Axis(
            title="cumulative contribution (log-return)", grid=True, gridColor=theme.RULE,
            domainColor=theme.INK, tickColor=theme.INK, labelColor=theme.INK_2)),
        color=alt.Color("label:N", scale=alt.Scale(domain=dom, range=[palette[d] for d in dom]),
                        legend=alt.Legend(title=None, orient="top")),
        order=alt.Order("component:N"),
    )
    return area.properties(height=height, background=theme.SURFACE).configure_view(stroke=None)


def forecast_chart(
    history: pd.DataFrame,
    path: pd.DataFrame,
    *,
    y_unit: str,
    height: int = 340,
) -> alt.Chart:
    """History tail (line) + forecast point path with a shaded confidence band.

    ``history`` is ``[date, value]``; ``path`` is the Forecast.path frame (index=future
    date, cols point/lo/hi)."""
    history = history.dropna(subset=["value"]).sort_values("date")
    p = path.reset_index(names="date")

    x_axis = alt.Axis(title=None, grid=False, domainColor=theme.INK,
                      tickColor=theme.INK, labelColor=theme.INK_2)
    y_axis = alt.Axis(title=y_unit, grid=True, gridColor=theme.RULE, domainColor=theme.INK,
                      tickColor=theme.INK, labelColor=theme.INK_2)

    hist_line = alt.Chart(history).mark_line(color=theme.INK, strokeWidth=1.6).encode(
        x=alt.X("date:T", axis=x_axis),
        y=alt.Y("value:Q", axis=y_axis, scale=alt.Scale(zero=False)))
    band = alt.Chart(p).mark_area(opacity=0.15, color=theme.SERIES_1).encode(
        x="date:T", y=alt.Y("lo:Q", scale=alt.Scale(zero=False)), y2="hi:Q")
    fcast_line = alt.Chart(p).mark_line(
        color=theme.SERIES_1, strokeWidth=1.8, strokeDash=[4, 3]).encode(
        x="date:T", y="point:Q")
    return alt.layer(band, hist_line, fcast_line).properties(
        height=height, background=theme.SURFACE).configure_view(stroke=None)


def universe_scatter(
    table: pd.DataFrame,
    *,
    x: str = "z_ret_20",
    y: str = "z_level_60",
    height: int = 420,
) -> alt.Chart:
    """The dislocation *map*: every series placed by return-z (x) vs level-z (y), sized by
    |z|, coloured by flag. Outliers sit in the corners — the screen you *see*. Presentation
    of quant.scanner's already-computed columns."""
    df = table.dropna(subset=[x, y]).copy()
    df["state"] = df["flag"].map({True: "flagged", False: "normal"})
    band = alt.Chart(pd.DataFrame({"v": [-2, 2]})).mark_rule(
        color=theme.INK_3, strokeWidth=0.5, strokeDash=[3, 3])
    guides = band.encode(y="v:Q") + band.encode(x="v:Q")
    pts = alt.Chart(df).mark_circle(opacity=0.7).encode(
        x=alt.X(f"{x}:Q", axis=alt.Axis(title="return z-score (20)", grid=True,
                gridColor=theme.RULE, domainColor=theme.INK, tickColor=theme.INK,
                labelColor=theme.INK_2)),
        y=alt.Y(f"{y}:Q", axis=alt.Axis(title="level z-score (60)", grid=True,
                gridColor=theme.RULE, domainColor=theme.INK, tickColor=theme.INK,
                labelColor=theme.INK_2)),
        size=alt.Size("abs_z:Q", scale=alt.Scale(range=[30, 500]),
                      legend=alt.Legend(title="|z|", orient="top")),
        color=alt.Color("state:N", scale=alt.Scale(
            domain=["flagged", "normal"], range=[theme.SERIES_2, theme.MUTED]),
            legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip("item:N"), alt.Tooltip("abs_z:Q", format=".2f"),
                 alt.Tooltip(f"{x}:Q", format=".2f"), alt.Tooltip(f"{y}:Q", format=".2f")],
    )
    labels = alt.Chart(df[df["flag"]]).mark_text(
        align="left", dx=8, fontSize=10, color=theme.INK).encode(
        x=f"{x}:Q", y=f"{y}:Q", text="item:N")
    return (guides + pts + labels).properties(
        height=height, background=theme.SURFACE).configure_view(stroke=None)
