"""
harvest_fixtures.py
===================
One-shot fixture harvester for the home-fund adapter build.

Hits each free data source ONCE and saves the raw response into
tests/fixtures/<YYYYMMDD>/ along with a manifest.json recording the
exact URL, timestamp, HTTP status, and SHA-256 of every payload.

Purpose: these raw payloads are the ground truth Claude builds and
tests adapters against, offline. Run locally (network required),
then upload the fixtures folder to the Claude Project.

Usage:
    pip install requests yfinance python-dotenv
    cp .env.example .env   # then fill in your keys
    python harvest_fixtures.py

Keys / config read from .env (never hard-code, never share):
    FRED_API_KEY            required for FRED
    ESTAT_APP_ID            required for e-Stat Japan
    ESTAT_STATS_DATA_ID     optional - a statsDataId to pull actual data
                            (find one via the statsList fixture first)
    STATCAN_VECTOR_ID       optional - defaults to a placeholder vector;
                            replace with the series you actually want

Each source is independent: one failure never stops the others.
An error response is still saved (as *_ERROR.*) because the error
payload shape is itself useful for writing adapter error handling.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # .env loading is a convenience; env vars set another way also work

# ---------------------------------------------------------------- config

OUT_ROOT = Path("tests/fixtures") / datetime.now().strftime("%Y%m%d")
TIMEOUT = 60
UA = {"User-Agent": "home-fund-fixture-harvest/0.1 (personal research)"}

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
ESTAT_APP_ID = os.getenv("ESTAT_APP_ID", "")
ESTAT_STATS_DATA_ID = os.getenv("ESTAT_STATS_DATA_ID", "")
# Placeholder StatCan vector - REPLACE with a vector you care about.
# Look vectors up in a table on the StatCan site (they are shown per series).
STATCAN_VECTOR_ID = os.getenv("STATCAN_VECTOR_ID", "65201210")

manifest: list[dict] = []

# Query params that carry secrets — redacted from recorded URLs so the
# committed manifest never leaks a key (rule #5: never print/commit secrets).
_SECRET_PARAMS = ("api_key", "appId", "token", "apikey", "api-key", "key")


def _redact(url: str) -> str:
    """Mask secret query-string values in a URL before recording it."""
    import re

    alt = "|".join(re.escape(p) for p in _SECRET_PARAMS)
    pattern = rf"(?i)([?&](?:{alt})=)[^&#]+"
    return re.sub(pattern, r"\1<REDACTED>", url)


# ---------------------------------------------------------------- helpers


def _record(name: str, url: str, status: int | str, path: Path | None, note: str = ""):
    entry = {
        "source": name,
        "url": _redact(url),
        "http_status": status,
        "saved_to": str(path) if path else None,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path else None,
        "harvested_utc": datetime.now(UTC).isoformat(),
        "note": note,
    }
    manifest.append(entry)
    flag = "OK " if path and "ERROR" not in path.name else "!! "
    print(f"  {flag}{name}: {status} -> {path}")


def save_get(name: str, url: str, filename: str, params: dict | None = None,
             note: str = ""):
    """GET a URL and save the raw body, whatever it is."""
    try:
        r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
        ok = r.status_code == 200
        fn = filename if ok else filename.replace(".", "_ERROR.", 1)
        path = OUT_ROOT / fn
        path.write_bytes(r.content)
        _record(name, r.url, r.status_code, path, note)
    except Exception as e:  # noqa: BLE001 - fixture harvest must not die
        _record(name, url, f"EXCEPTION: {e}", None, note)


def save_post_json(name: str, url: str, payload, filename: str, note: str = ""):
    try:
        r = requests.post(url, json=payload, headers=UA, timeout=TIMEOUT)
        ok = r.status_code == 200
        fn = filename if ok else filename.replace(".", "_ERROR.", 1)
        path = OUT_ROOT / fn
        path.write_bytes(r.content)
        _record(name, url, r.status_code, path, note)
    except Exception as e:  # noqa: BLE001
        _record(name, url, f"EXCEPTION: {e}", None, note)


# ---------------------------------------------------------------- sources


def harvest_fred():
    if not FRED_API_KEY:
        _record("fred", "-", "SKIPPED (no FRED_API_KEY)", None)
        return
    save_get(
        "fred_observations",
        "https://api.stlouisfed.org/fred/series/observations",
        "fred_INDPRO_observations.json",
        params={
            "series_id": "INDPRO",
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "observation_start": "2015-01-01",
        },
        note="US industrial production - canonical FRED payload shape",
    )
    save_get(
        "fred_series_meta",
        "https://api.stlouisfed.org/fred/series",
        "fred_INDPRO_meta.json",
        params={"series_id": "INDPRO", "api_key": FRED_API_KEY,
                "file_type": "json"},
        note="series metadata payload - feeds registry validation",
    )


def harvest_eurostat():
    # Dissemination API, no key. If this 400s, the dimension filters have
    # drifted - retry with only {format, lang, sinceTimePeriod} and let the
    # adapter do filtering client-side.
    save_get(
        "eurostat_ip",
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_inpr_m",
        "eurostat_sts_inpr_m_DE.json",
        params={
            "format": "JSON",
            "lang": "EN",
            "geo": "DE",
            "nace_r2": "B-D",
            "s_adj": "SCA",
            "unit": "I21",
            "sinceTimePeriod": "2022-01",
        },
        note="German industrial production, JSON-stat format",
    )


def harvest_statcan():
    save_post_json(
        "statcan_vector",
        "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
        [{"vectorId": int(STATCAN_VECTOR_ID), "latestN": 24}],
        f"statcan_v{STATCAN_VECTOR_ID}.json",
        note="WDS vector payload; replace placeholder vector with real target",
    )


def harvest_estat():
    if not ESTAT_APP_ID:
        _record("estat", "-", "SKIPPED (no ESTAT_APP_ID)", None)
        return
    # Always works with just an appId: captures the catalogue payload shape
    # and is how you FIND statsDataIds for the data call below.
    save_get(
        "estat_statslist",
        "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsList",
        "estat_statslist_iip.json",
        params={"appId": ESTAT_APP_ID, "searchWord": "IIP", "limit": 5},
        note="catalogue search payload - use to locate statsDataId values",
    )
    if ESTAT_STATS_DATA_ID:
        save_get(
            "estat_statsdata",
            "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData",
            f"estat_statsdata_{ESTAT_STATS_DATA_ID}.json",
            params={"appId": ESTAT_APP_ID,
                    "statsDataId": ESTAT_STATS_DATA_ID,
                    "limit": 1000},
            note="actual data payload shape",
        )


def harvest_cftc():
    # Socrata public reporting API - disaggregated futures-only COT.
    # If the dataset id has changed, browse publicreporting.cftc.gov for
    # the current one and update here.
    save_get(
        "cftc_cot_copper",
        "https://publicreporting.cftc.gov/resource/72hh-3qpy.json",
        "cftc_disagg_copper.json",
        params={
            "$limit": 100,
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$where": "upper(market_and_exchange_names) like 'COPPER%'",
        },
        note="disaggregated COT, COMEX copper incl. related contracts",
    )


def harvest_yfinance():
    try:
        import yfinance as yf
    except ImportError:
        _record("yfinance", "-", "SKIPPED (pip install yfinance)", None)
        return
    tickers = {
        "HG=F": "yf_HG_comex_copper.csv",
        "ALI=F": "yf_ALI_aluminum.csv",
        "AUP=F": "yf_AUP_midwest_premium.csv",
    }
    for tkr, fn in tickers.items():
        try:
            df = yf.download(tkr, period="2y", interval="1d",
                             auto_adjust=False, progress=False)
            path = OUT_ROOT / fn
            buf = io.StringIO()
            df.to_csv(buf)
            path.write_text(buf.getvalue())
            note = ("thin/illiquid contract - expect gaps and stale quotes"
                    if tkr == "AUP=F" else "")
            _record(f"yfinance {tkr}", f"yfinance:{tkr}",
                    "OK" if len(df) else "EMPTY", path, note)
        except Exception as e:  # noqa: BLE001
            _record(f"yfinance {tkr}", f"yfinance:{tkr}",
                    f"EXCEPTION: {e}", None)


# ---------------------------------------------------------------- main


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"Harvesting fixtures into {OUT_ROOT}/\n")

    harvest_fred()
    harvest_eurostat()
    harvest_statcan()
    harvest_estat()
    harvest_cftc()
    harvest_yfinance()

    (OUT_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest written to {OUT_ROOT / 'manifest.json'}")

    failures = [m for m in manifest
                if m["saved_to"] is None or "ERROR" in str(m["saved_to"])]
    if failures:
        print(f"{len(failures)} source(s) failed or were skipped - "
              "see manifest. Error payloads (if saved) are still useful.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
