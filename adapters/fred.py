"""FRED adapter — St. Louis Fed FRED API.

Pulls a series' observations plus its metadata and emits point-in-time rows.
FRED gives each observation a ``realtime_start`` — that is the vintage we store
as ``as_of``. Missing values arrive as ``"."`` and are dropped downstream.

Endpoints (proven in harvest_fixtures.py):
    GET /fred/series/observations   -> {"observations": [...]}
    GET /fred/series                -> {"seriess": [{... "last_updated" ...}]}

The API key is read from the ``FRED_API_KEY`` env var (rule #5: never hard-coded).
"""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd
import requests

from adapters.base import AdapterError, BaseAdapter, TransientFetchError
from registry.schema import SeriesSpec

_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"
_META_URL = "https://api.stlouisfed.org/fred/series"
_TIMEOUT = 60
_UA = {"User-Agent": "home-fund/0.1 (personal research)"}
# FRED missing-value sentinel.
_MISSING = "."


class FredAdapter(BaseAdapter):
    source = "fred"

    def __init__(
        self,
        *args: Any,
        api_key: str | None = None,
        observation_start: str = "1990-01-01",
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self._api_key = api_key if api_key is not None else os.getenv("FRED_API_KEY", "")
        self._observation_start = observation_start

    def _get(self, url: str, params: dict) -> dict:
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=_TIMEOUT)
        except requests.RequestException as e:
            raise TransientFetchError(f"FRED request error: {e}") from e
        # 429 (rate limit) and 5xx are transient; 4xx are permanent (bad key/params).
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientFetchError(f"FRED {url} -> HTTP {r.status_code}")
        if r.status_code != 200:
            raise AdapterError(f"FRED {url} -> HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except json.JSONDecodeError as e:
            raise AdapterError(f"FRED {url} returned non-JSON body: {r.text[:200]}") from e

    def fetch_raw(self, spec: SeriesSpec) -> dict:
        if not self._api_key:
            raise AdapterError("FRED_API_KEY is not set (rule #5: keys live in .env)")
        obs = self._get(
            _OBS_URL,
            {
                "series_id": spec.source_code,
                "api_key": self._api_key,
                "file_type": "json",
                "observation_start": self._observation_start,
            },
        )
        meta = self._get(
            _META_URL,
            {"series_id": spec.source_code, "api_key": self._api_key, "file_type": "json"},
        )
        return {"observations": obs, "meta": meta}

    def parse(self, spec: SeriesSpec, raw: dict) -> pd.DataFrame:
        obs_payload = raw.get("observations", raw)  # tolerate a bare observations dict
        observations = obs_payload.get("observations")
        if observations is None:
            raise AdapterError(
                f"FRED payload for '{spec.series_id}' has no 'observations' key "
                "(layout change or error payload) — failing loudly"
            )

        # last_updated from metadata when present; else fall back to obs realtime_end.
        last_updated = None
        meta = raw.get("meta")
        if meta and meta.get("seriess"):
            last_updated = meta["seriess"][0].get("last_updated")

        rows = []
        for o in observations:
            val = o.get("value")
            rows.append(
                {
                    "date": o.get("date"),
                    # keep "." as NaN via numeric coercion downstream
                    "value": None if val == _MISSING else val,
                    "as_of": o.get("realtime_start"),
                    "last_updated": last_updated or o.get("realtime_end"),
                }
            )
        return pd.DataFrame(rows, columns=["date", "value", "as_of", "last_updated"])
