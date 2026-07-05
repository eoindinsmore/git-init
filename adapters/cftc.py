"""CFTC COT adapter — Commitments of Traders, Socrata public API (no key).

Disaggregated futures-only report. Each report row carries many position metrics;
we model **one registry series per field**: ``source_code`` is the CFTC column
(e.g. ``m_money_positions_long_all``) and ``source_params`` carries the market
filter (``market`` pattern) and optional ``dataset``/``limit``/``where``.

Point-in-time discipline
------------------------
A COT report is a **Tuesday** snapshot **published the following Friday**. Storing
``as_of = report_date`` would let a backtest see positioning 3 days early
(lookahead). This adapter sets ``as_of = report_date + 3 days`` — the publication
date, the honest "known by" — and ``last_updated`` to the same.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import requests

from adapters.base import AdapterError, BaseAdapter, TransientFetchError
from registry.schema import SeriesSpec

_BASE = "https://publicreporting.cftc.gov/resource"
_DEFAULT_DATASET = "72hh-3qpy"  # disaggregated futures-only COT
_TIMEOUT = 60
_UA = {"User-Agent": "home-fund/0.1 (personal research)"}
_DEFAULT_LIMIT = 520  # ~10 years of weekly reports
_PUBLICATION_LAG = pd.Timedelta(days=3)  # Tuesday snapshot -> Friday release
_DATE_FIELD = "report_date_as_yyyy_mm_dd"


class CftcAdapter(BaseAdapter):
    source = "cftc"

    def fetch_raw(self, spec: SeriesSpec) -> Any:
        dataset = spec.source_params.get("dataset", _DEFAULT_DATASET)
        limit = int(spec.source_params.get("limit", _DEFAULT_LIMIT))
        where = spec.source_params.get("where")
        if not where:
            market = spec.source_params.get("market")
            if not market:
                raise AdapterError(
                    f"CFTC '{spec.series_id}': source_params needs a 'market' pattern "
                    "or 'where' clause"
                )
            where = f"upper(market_and_exchange_names) like '{market.upper()}'"
        params = {
            "$where": where,
            "$order": f"{_DATE_FIELD} DESC",
            "$limit": limit,
        }
        url = f"{_BASE}/{dataset}.json"
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=_TIMEOUT)
        except requests.RequestException as e:
            raise TransientFetchError(f"CFTC request error: {e}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientFetchError(f"CFTC -> HTTP {r.status_code}")
        if r.status_code != 200:
            raise AdapterError(f"CFTC -> HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except json.JSONDecodeError as e:
            raise AdapterError(f"CFTC returned non-JSON: {r.text[:200]}") from e

    def parse(self, spec: SeriesSpec, raw: Any) -> pd.DataFrame:
        if not isinstance(raw, list):
            raise AdapterError(
                f"CFTC '{spec.series_id}': expected a JSON list, got {type(raw).__name__}"
            )
        field = spec.source_code
        rows = []
        for row in raw:
            if field not in row:
                continue  # field absent on this row (mixed markets) — skip
            report_date = pd.to_datetime(row.get(_DATE_FIELD), errors="coerce")
            if pd.isna(report_date):
                continue
            as_of = report_date + _PUBLICATION_LAG  # publication date — no lookahead
            rows.append(
                {
                    "date": report_date,
                    "value": row.get(field),
                    "as_of": as_of,
                    "last_updated": as_of,
                }
            )
        if not rows:
            raise AdapterError(
                f"CFTC '{spec.series_id}': field '{field}' not present in any row "
                "(check the field name / market filter) — failing loudly"
            )
        return pd.DataFrame(rows, columns=["date", "value", "as_of", "last_updated"])
