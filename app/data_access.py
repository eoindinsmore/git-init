"""Read-only bridge between the app and the store/registry.

Everything here is *reading* — loading the registry, point-in-time series retrieval,
and descriptive coverage (counts, date spans, latest vintage). Per the charter, reading
the store is not analytics. Growth/level transforms are NOT here; pages call
``quant.transforms`` for those.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from quant import store
from registry.loader import load_registry
from registry.schema import SeriesSpec

# country/region tags -> reader-facing region bucket.
_REGION_BY_COUNTRY: dict[str, str] = {
    "US": "North America", "CA": "North America", "MX": "North America",
    "DE": "Europe", "GB": "Europe", "FR": "Europe", "EU": "Europe",
    "JP": "Asia", "CN": "Asia", "KR": "Asia", "IN": "Asia", "TW": "Asia",
    "CL": "Latin America", "PE": "Latin America",
}


def region_for(country: str | None) -> str:
    """Map a series' country tag to a region bucket ('Global' when unset/unknown)."""
    if not country:
        return "Global"
    return _REGION_BY_COUNTRY.get(country, country)


@st.cache_data(show_spinner=False)
def _facts() -> pd.DataFrame:
    return store.read_facts()


def registry() -> dict[str, SeriesSpec]:
    """The full registry (uncached — cheap, and always reflects edited YAML)."""
    return load_registry()


def series_ids_in_store() -> set[str]:
    return set(_facts()["series_id"].unique())


def get_series(series_id: str, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Point-in-time ``[date, value]`` for a series (delegates to the store)."""
    return store.get_series(series_id, as_of=as_of)


def as_of_bounds(series_id: str) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """(min, max) ``as_of`` seen for a series — the range of the point-in-time slider."""
    facts = _facts()
    sel = facts[facts["series_id"] == series_id]
    if sel.empty:
        return None, None
    return sel["as_of"].min(), sel["as_of"].max()


def coverage_table() -> pd.DataFrame:
    """Descriptive per-series coverage/freshness (a read, not analytics).

    Columns: series_id, source, frequency, n_obs (distinct dates), n_rows (vintages),
    first_date, last_date, latest_as_of, staleness_days (now - last_date).
    """
    facts = _facts()
    if facts.empty:
        return pd.DataFrame()
    now = pd.Timestamp.now().normalize()
    rows = []
    for sid, g in facts.groupby("series_id"):
        last_date = g["date"].max()
        rows.append({
            "series_id": sid,
            "source": g["source"].iloc[0],
            "frequency": g["frequency"].iloc[0],
            "n_obs": g["date"].nunique(),
            "n_rows": len(g),
            "first_date": g["date"].min(),
            "last_date": last_date,
            "latest_as_of": g["as_of"].max(),
            "staleness_days": int((now - last_date).days),
        })
    return pd.DataFrame(rows).sort_values("series_id").reset_index(drop=True)
