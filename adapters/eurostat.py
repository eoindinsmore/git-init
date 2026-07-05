"""Eurostat adapter — dissemination API, JSON-stat format, no API key.

The registry ``source_code`` is the dataset id (e.g. ``sts_inpr_m``) and
``source_params`` carries the dimension filters (geo, nace_r2, s_adj, unit, ...)
that must reduce the cube to a single series. Eurostat provides no per-observation
vintage, so the dataset-level ``updated`` timestamp is used as both ``as_of`` and
``last_updated``.
"""

from __future__ import annotations

import json

import pandas as pd
import requests

from adapters.base import AdapterError, BaseAdapter, TransientFetchError
from registry.schema import SeriesSpec

_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
_TIMEOUT = 60
_UA = {"User-Agent": "home-fund/0.1 (personal research)"}


def _period_to_date(period: str) -> pd.Timestamp:
    """Convert a Eurostat time label to the period-start date.

    Handles monthly ('2022-01'), annual ('2022') and quarterly ('2022-Q1').
    """
    if "Q" in period:
        return pd.Period(period.replace("-", ""), freq="Q").to_timestamp()
    return pd.Timestamp(pd.to_datetime(period))


class EurostatAdapter(BaseAdapter):
    source = "eurostat"

    def _get(self, dataset: str, params: dict) -> dict:
        url = f"{_BASE}/{dataset}"
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=_TIMEOUT)
        except requests.RequestException as e:
            raise TransientFetchError(f"Eurostat request error: {e}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientFetchError(f"Eurostat {dataset} -> HTTP {r.status_code}")
        if r.status_code != 200:
            raise AdapterError(f"Eurostat {dataset} -> HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except json.JSONDecodeError as e:
            raise AdapterError(f"Eurostat {dataset} returned non-JSON: {r.text[:200]}") from e

    def fetch_raw(self, spec: SeriesSpec) -> dict:
        params = {"format": "JSON", "lang": "EN", **spec.source_params}
        return self._get(spec.source_code, params)

    def parse(self, spec: SeriesSpec, raw: dict) -> pd.DataFrame:
        try:
            dims = raw["id"]
            sizes = raw["size"]
            dimension = raw["dimension"]
            values = raw["value"]
        except KeyError as e:
            raise AdapterError(
                f"Eurostat payload for '{spec.series_id}' missing JSON-stat key {e} "
                "(layout change) — failing loudly"
            ) from e

        if "time" not in dims:
            raise AdapterError(f"Eurostat '{spec.series_id}': no 'time' dimension in payload")

        # Every non-time dimension must be pinned to a single category, otherwise
        # we'd be silently collapsing multiple series. Fail loudly if not.
        for dim, size in zip(dims, sizes, strict=True):
            if dim != "time" and size != 1:
                raise AdapterError(
                    f"Eurostat '{spec.series_id}': dimension '{dim}' has {size} categories; "
                    "add a source_params filter so the query returns a single series"
                )

        # Row-major stride of the time dimension (all other indices are 0).
        t_idx = dims.index("time")
        stride = 1
        for size in sizes[t_idx + 1:]:
            stride *= size

        updated = raw.get("updated")  # dataset-level vintage
        time_index: dict[str, int] = dimension["time"]["category"]["index"]

        rows = []
        for period, pos in time_index.items():
            flat = str(pos * stride)
            if flat not in values:
                continue  # Eurostat omits missing observations entirely
            rows.append(
                {
                    "date": _period_to_date(period),
                    "value": values[flat],
                    "as_of": updated,
                    "last_updated": updated,
                }
            )
        return pd.DataFrame(rows, columns=["date", "value", "as_of", "last_updated"])
