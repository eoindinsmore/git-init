"""e-Stat adapter — Japan official statistics portal, getStatsData API.

e-Stat returns a multi-dimensional cube: each VALUE row is a set of ``@<dim>``
category codes plus a ``$`` value. The registry ``source_code`` is the
``statsDataId`` and ``selector`` pins the non-time dimensions to a single series
(e.g. ``{"cat02": "2021010010"}``). Time codes are decoded via ``CLASS_INF``.

e-Stat exposes no per-observation vintage; ``TABLE_INF.UPDATED_DATE`` is used as
``as_of`` / ``last_updated``. The appId is read from ``ESTAT_APP_ID`` (rule #5).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import pandas as pd

from adapters.base import AdapterError, BaseAdapter, TransientFetchError
from registry.schema import SeriesSpec

_URL = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
_TIMEOUT = 60
_UA = {"User-Agent": "home-fund/0.1 (personal research)"}
_DEFAULT_LIMIT = 100000


def _time_name_to_date(name: str) -> pd.Timestamp | None:
    """Decode an e-Stat time-category name to a period-start date.

    Names look like '202401' (monthly) or '2024' (annual). Returns None if the
    name cannot be interpreted as a date.
    """
    digits = re.sub(r"\D", "", name)
    if len(digits) >= 6:
        return pd.Timestamp(int(digits[:4]), int(digits[4:6]), 1)
    if len(digits) == 4:
        return pd.Timestamp(int(digits), 1, 1)
    return None


class EstatAdapter(BaseAdapter):
    source = "estat"

    def __init__(self, *args: Any, app_id: str | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._app_id = app_id if app_id is not None else os.getenv("ESTAT_APP_ID", "")

    def fetch_raw(self, spec: SeriesSpec) -> dict:
        if not self._app_id:
            raise AdapterError("ESTAT_APP_ID is not set (rule #5: keys live in .env)")
        params = {
            "appId": self._app_id,
            "statsDataId": spec.source_code,
            "limit": int(spec.source_params.get("limit", _DEFAULT_LIMIT)),
        }
        import requests

        try:
            r = requests.get(_URL, params=params, headers=_UA, timeout=_TIMEOUT)
        except requests.RequestException as e:
            raise TransientFetchError(f"e-Stat request error: {e}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientFetchError(f"e-Stat -> HTTP {r.status_code}")
        if r.status_code != 200:
            raise AdapterError(f"e-Stat -> HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except json.JSONDecodeError as e:
            raise AdapterError(f"e-Stat returned non-JSON: {r.text[:200]}") from e

    def parse(self, spec: SeriesSpec, raw: dict) -> pd.DataFrame:
        try:
            gsd = raw["GET_STATS_DATA"]
            result = gsd["RESULT"]
        except KeyError as e:
            raise AdapterError(f"e-Stat '{spec.series_id}': missing key {e} (layout change)") from e

        if str(result.get("STATUS")) != "0":
            raise AdapterError(
                f"e-Stat '{spec.series_id}': API status {result.get('STATUS')} "
                f"— {result.get('ERROR_MSG')}"
            )

        stat = gsd["STATISTICAL_DATA"]
        table_inf = stat.get("TABLE_INF", {})
        updated = table_inf.get("UPDATED_DATE")

        # Build the time-code -> date map from CLASS_INF.
        class_objs = stat["CLASS_INF"]["CLASS_OBJ"]
        if isinstance(class_objs, dict):
            class_objs = [class_objs]
        time_map: dict[str, pd.Timestamp] = {}
        dim_ids = set()
        for co in class_objs:
            dim_ids.add(co["@id"])
            if co["@id"] == "time":
                cats = co["CLASS"]
                for cat in (cats if isinstance(cats, list) else [cats]):
                    d = _time_name_to_date(str(cat.get("@name", "")))
                    if d is not None:
                        time_map[cat["@code"]] = d

        # Validate the selector references real dimensions.
        for dim in spec.selector:
            if dim not in dim_ids:
                raise AdapterError(
                    f"e-Stat '{spec.series_id}': selector dimension '{dim}' not in payload "
                    f"(available: {sorted(dim_ids)})"
                )

        values = stat["DATA_INF"]["VALUE"]
        if isinstance(values, dict):
            values = [values]

        rows = []
        for v in values:
            if not all(v.get(f"@{dim}") == code for dim, code in spec.selector.items()):
                continue
            date = time_map.get(v.get("@time"))
            if date is None:
                continue  # non-time-indexed or undecodable row
            rows.append(
                {"date": date, "value": v.get("$"), "as_of": updated, "last_updated": updated}
            )

        df = pd.DataFrame(rows, columns=["date", "value", "as_of", "last_updated"])
        # Selector must isolate a single series: no duplicate dates allowed.
        dups = df["date"].duplicated().sum()
        if dups:
            raise AdapterError(
                f"e-Stat '{spec.series_id}': {dups} duplicate dates after selection — "
                "selector does not isolate a single series (pin more dimensions)"
            )
        return df
