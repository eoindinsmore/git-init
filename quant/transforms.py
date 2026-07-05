"""Series transformations — the registry-aware analytics the dashboard toggles between.

Charter layering: the Streamlit app contains **zero** analytics. Growth rates,
differences and moving averages are analytics, so they live here (a slice of the
step-4 quant toolkit) and the app merely calls :func:`apply`.

All transforms are **frequency-aware** and operate on the *native* frequency of the
series via positional lags — ``k`` periods back where ``k`` is the number of periods
in a year (M:12, Q:4, W:52, D:252, A:1). "MoM" is therefore period-over-period at the
series' own frequency; on a weekly series it is week-over-week, on daily it is
day-over-day. This is deliberate (the user chose native-frequency semantics with no
hidden resampling); daily/weekly series default to ``level`` in the UI.

Point-in-time note: transforms take whatever ``[date, value]`` frame they are given.
The caller fetches it via ``store.get_series(series_id, as_of=...)`` so the vintage is
already correct; a transform never reaches back into the store. Feed the transform the
**full** history and clip to the display horizon *afterwards*, so a YoY value near the
left edge of the window still uses real prior-year data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Periods per year by frequency code (matches registry.schema.Frequency values).
# Daily uses ~252 business days as an approximate one-year lag.
PERIODS_PER_YEAR: dict[str, int] = {"A": 1, "Q": 4, "M": 12, "W": 52, "D": 252}

# UI-facing transform kinds -> human label. Order is the menu order.
LABELS: dict[str, str] = {
    "level": "Level",
    "yoy_pct": "YoY %",
    "mom_pct": "MoM %",
    "mom_lvl": "MoM levels",
    "yoy_lvl": "YoY levels",
    "ma3_yoy_pct": "3MMA YoY %",
    "ma3_mom_pct": "3MMA MoM %",
    "ma3_mom_lvl": "3MMA levels MoM",
}
KINDS: tuple[str, ...] = tuple(LABELS)

# Registry ``transformations`` tokens -> our kind. Extend as the registry grows.
_TOKEN_TO_KIND: dict[str, str] = {
    "yoy": "yoy_pct",
    "mom": "mom_pct",
    "yoy_lvl": "yoy_lvl",
    "mom_lvl": "mom_lvl",
    "3m3m": "ma3_mom_pct",
}


def default_kind(transformations: list[str]) -> str:
    """The default view for a series, from its registry ``transformations`` list.

    First recognised entry wins: either a short token (``yoy`` -> ``yoy_pct``) or a
    full kind (``yoy_pct``) written directly by the registry workbook. An empty or
    unknown list falls back to ``level`` (the honest default for prices/positioning,
    which have no natural growth rate).
    """
    for tok in transformations:
        if tok in _TOKEN_TO_KIND:
            return _TOKEN_TO_KIND[tok]
        if tok in LABELS:
            return tok
    return "level"


def _pct(numer: pd.Series, denom: pd.Series) -> pd.Series:
    """100 * (numer/denom - 1), with divide-by-zero -> NaN (never inf)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (numer / denom - 1.0) * 100.0
    return out.replace([np.inf, -np.inf], np.nan)


def apply(df: pd.DataFrame, kind: str, frequency: str) -> pd.DataFrame:
    """Return ``df`` (columns ``date``, ``value``) with ``value`` transformed.

    ``kind`` is one of :data:`KINDS`; ``frequency`` is a registry frequency code
    (``M``/``Q``/``W``/``D``/``A``). The result is sorted by date with rows that are
    undefined for the transform (leading lags, zero denominators) dropped, so charts
    render a clean line. Raises ``ValueError`` on an unknown ``kind`` or ``frequency``.
    """
    if kind not in LABELS:
        raise ValueError(f"unknown transform kind {kind!r}; expected one of {list(LABELS)}")
    if df.empty:
        return df.loc[:, ["date", "value"]].copy()

    out = df.loc[:, ["date", "value"]].sort_values("date").reset_index(drop=True)
    v = pd.to_numeric(out["value"], errors="coerce")

    if kind == "level":
        out["value"] = v
        return out.dropna(subset=["value"]).reset_index(drop=True)

    if frequency not in PERIODS_PER_YEAR:
        raise ValueError(
            f"unknown frequency {frequency!r}; expected one of {list(PERIODS_PER_YEAR)}"
        )
    k = PERIODS_PER_YEAR[frequency]
    ma3 = v.rolling(3).mean()

    if kind == "yoy_pct":
        result = _pct(v, v.shift(k))
    elif kind == "mom_pct":
        result = _pct(v, v.shift(1))
    elif kind == "mom_lvl":
        result = v - v.shift(1)
    elif kind == "yoy_lvl":
        result = v - v.shift(k)
    elif kind == "ma3_yoy_pct":
        result = _pct(ma3, ma3.shift(k))
    elif kind == "ma3_mom_pct":
        result = _pct(ma3, ma3.shift(1))
    elif kind == "ma3_mom_lvl":
        result = ma3 - ma3.shift(1)
    else:  # pragma: no cover - guarded by the membership check above
        raise ValueError(kind)

    out["value"] = result
    return out.dropna(subset=["value"]).reset_index(drop=True)


def unit_label(kind: str, base_unit: str) -> str:
    """Axis/subtitle unit string for a transform (e.g. '% YoY', or the base unit)."""
    if kind == "level":
        return base_unit
    if kind.endswith("_pct"):
        return "% change"
    return f"Δ {base_unit}"
