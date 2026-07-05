"""StatCan adapter — Statistics Canada Web Data Service (WDS), no API key.

The registry ``source_code`` is the numeric vector id. WDS returns each data
point with a ``releaseTime`` — a genuine per-observation vintage, so this adapter
captures real point-in-time revision history (``as_of`` = releaseTime).

``source_params`` may set ``latestN`` (number of most-recent periods to pull;
default 600 ≈ 50 years of monthly data). The store dedups, so re-pulls are cheap.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import requests

from adapters.base import AdapterError, BaseAdapter, TransientFetchError
from registry.schema import SeriesSpec

_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
_TIMEOUT = 60
_UA = {"User-Agent": "home-fund/0.1 (personal research)", "Content-Type": "application/json"}
_DEFAULT_LATEST_N = 600


class StatCanAdapter(BaseAdapter):
    source = "statcan"

    def fetch_raw(self, spec: SeriesSpec) -> Any:
        try:
            vector = int(spec.source_code)
        except ValueError as e:
            raise AdapterError(
                f"StatCan '{spec.series_id}': source_code must be a numeric vector id"
            ) from e
        latest_n = int(spec.source_params.get("latestN", _DEFAULT_LATEST_N))
        payload = [{"vectorId": vector, "latestN": latest_n}]
        try:
            r = requests.post(_URL, json=payload, headers=_UA, timeout=_TIMEOUT)
        except requests.RequestException as e:
            raise TransientFetchError(f"StatCan request error: {e}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientFetchError(f"StatCan -> HTTP {r.status_code}")
        if r.status_code != 200:
            raise AdapterError(f"StatCan -> HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except json.JSONDecodeError as e:
            raise AdapterError(f"StatCan returned non-JSON: {r.text[:200]}") from e

    def parse(self, spec: SeriesSpec, raw: Any) -> pd.DataFrame:
        # WDS returns a list with one entry per requested vector.
        if not isinstance(raw, list) or not raw:
            raise AdapterError(
                f"StatCan '{spec.series_id}': unexpected payload shape (expected non-empty list)"
            )
        entry = raw[0]
        if entry.get("status") != "SUCCESS":
            raise AdapterError(
                f"StatCan '{spec.series_id}': WDS status {entry.get('status')!r} (not SUCCESS)"
            )

        obj = entry.get("object") or {}
        datapoints = obj.get("vectorDataPoint")
        if datapoints is None:
            raise AdapterError(
                f"StatCan '{spec.series_id}': no 'vectorDataPoint' in payload (layout change)"
            )

        rows = []
        for dp in datapoints:
            # symbolCode/statusCode != 0 flags suppressed/unavailable values.
            value = dp.get("value")
            rows.append(
                {
                    "date": dp.get("refPer"),
                    "value": value,
                    "as_of": dp.get("releaseTime"),  # true per-observation vintage
                    "last_updated": dp.get("releaseTime"),
                }
            )
        return pd.DataFrame(rows, columns=["date", "value", "as_of", "last_updated"])
