"""Shared UI controls: the two-row region/category button bar, the left-panel date
range, and the transform picker.

Filtering and horizon clipping are presentation (date-range selection). The transform
picker just wires the UI to ``quant.transforms`` — the maths itself stays in quant.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.data_access import region_for
from quant import transforms as tf
from registry.schema import SeriesSpec

# Left-panel date range: label -> months back (None = full history).
HORIZONS: dict[str, int | None] = {
    "3": 3, "12": 12, "24": 24, "48": 48, "120": 120, "Max": None,
}


def horizon_picker(key: str, default: str = "24", sidebar: bool = True) -> int | None:
    """Radio over the month-based date range. Rendered in the left panel by default."""
    container = st.sidebar if sidebar else st
    container.markdown("**Date range** _(months)_")
    labels = list(HORIZONS)
    choice = container.radio(
        "Date range", labels, index=labels.index(default), key=key,
        label_visibility="collapsed", horizontal=not sidebar,
    )
    return HORIZONS[choice]


def clip_horizon(df: pd.DataFrame, months: int | None) -> pd.DataFrame:
    """Keep rows within ``months`` of the latest observation (None = all)."""
    if months is None or df.empty:
        return df
    cutoff = df["date"].max() - pd.DateOffset(months=months)
    return df[df["date"] >= cutoff].reset_index(drop=True)


def filter_bar(specs: list[SeriesSpec], key_prefix: str) -> tuple[str, str]:
    """Two rows of buttons across the top: region (row 1), category (row 2).

    Single-select each, with a leading "All". Returns (region, category); an empty
    selection coalesces back to "All".
    """
    regions = ["All"] + sorted({region_for(s.tags.country) for s in specs})
    themes = ["All"] + sorted({
        s.tags.macro_theme.value for s in specs if s.tags.macro_theme
    })
    region = st.segmented_control(
        "Region", regions, default="All", key=f"{key_prefix}_region",
        selection_mode="single",
    ) or "All"
    category = st.segmented_control(
        "Category", themes, default="All", key=f"{key_prefix}_category",
        selection_mode="single", format_func=str.title,
    ) or "All"
    return region, category


def matches(spec: SeriesSpec, region: str, category: str) -> bool:
    """Whether a series passes the region + category filter ('All' matches anything)."""
    region_ok = region == "All" or region_for(spec.tags.country) == region
    theme_val = spec.tags.macro_theme.value if spec.tags.macro_theme else None
    category_ok = category == "All" or theme_val == category
    return region_ok and category_ok


def transform_picker(key: str, default_kind: str) -> str:
    """Radio over the transform menu, preselecting the series' registry default."""
    kinds = list(tf.KINDS)
    labels = [tf.LABELS[k] for k in kinds]
    idx = kinds.index(default_kind) if default_kind in kinds else 0
    chosen_label = st.radio("Transformation", labels, index=idx, key=key, horizontal=True)
    return kinds[labels.index(chosen_label)]
