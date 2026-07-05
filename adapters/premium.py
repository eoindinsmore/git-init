"""Premium capture job — daily, vintage-stamped capture of aluminium premiums.

Charter priority theme. The intended source (CME daily settlements across all
listed contract months → full forward curve) is behind Akamai bot protection and
must not be scraped. This job instead captures the **front-month continuous**
premium from yfinance (charter option a) — ToS-clean and, critically, run daily so
we accumulate premium history that yfinance's rolling window cannot backfill.

Covered series (declared in registry/premiums.yaml, all ``category: price_proxy``):
    aluminium_premium_mw_us   — CME AUP=F, US Midwest, USD/lb
    aluminium_premium_eu_dp   — CME EDP=F, European duty-paid, USD/metric ton

Vintage discipline
------------------
Each observation date's settlement is stored point-in-time:
- a **newly seen** date is stored with ``as_of = observation date`` (honest floor —
  the settlement was published that day; on the first run this seeds history);
- a **changed** value for a date we already stored is a revision, kept as a NEW row
  with ``as_of = capture_date`` (the day we observed the revision);
- an **unchanged** date is skipped (idempotent — safe to run many times a day).

This keeps daily re-runs cheap while capturing genuine revisions as distinct
vintages, and never overwrites (append-only).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant import store
from registry.loader import load_registry
from registry.schema import SeriesSpec

# Registry source key for premium series captured by this job.
SOURCE = "premium"


class PremiumCaptureError(RuntimeError):
    """Raised on unrecoverable capture failure (loud failure)."""


def fetch_yf(ticker: str, period: str = "2y") -> pd.DataFrame:
    """Fetch a ticker's daily close from yfinance as a clean [date, value] frame."""
    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover - env guard
        raise PremiumCaptureError("yfinance not installed (pip install '.[proxies]')") from e

    df = yf.download(ticker, period=period, interval="1d", auto_adjust=False, progress=False)
    if df is None or df.empty:
        raise PremiumCaptureError(f"yfinance returned no data for {ticker!r}")
    close = df["Close"]
    # yfinance may return a single-column DataFrame (MultiIndex columns) for Close.
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    out = pd.DataFrame({"date": pd.to_datetime(df.index), "value": close.to_numpy()})
    out = out.dropna(subset=["value"]).reset_index(drop=True)
    return out


def read_yf_csv(path: Path) -> pd.DataFrame:
    """Parse a harvested yfinance CSV fixture into a clean [date, value] frame.

    The harvester saves a MultiIndex-column frame, so the first two rows under the
    'Price' column are the 'Ticker' and 'Date' header remnants, not data.
    """
    raw = pd.read_csv(path)
    parsed_date = pd.to_datetime(raw["Price"], format="ISO8601", errors="coerce")
    raw = raw[parsed_date.notna()]
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["Price"], format="ISO8601"),
            "value": pd.to_numeric(raw["Close"], errors="coerce"),
        }
    )
    return out.dropna(subset=["value"]).reset_index(drop=True)


def plan_rows(
    spec: SeriesSpec,
    incoming: pd.DataFrame,
    existing: pd.DataFrame,
    capture_date: pd.Timestamp,
) -> pd.DataFrame:
    """Decide which fact rows to write, applying vintage discipline.

    ``incoming`` and ``existing`` are [date, value] frames (existing = latest
    vintage per date from the store). Returns fact-table-shaped rows.
    """
    latest: dict[pd.Timestamp, float] = {}
    if not existing.empty:
        ex = existing.copy()
        ex["date"] = pd.to_datetime(ex["date"])
        latest = dict(zip(ex["date"], ex["value"], strict=True))

    rows = []
    for d, v in zip(pd.to_datetime(incoming["date"]), incoming["value"], strict=True):
        if pd.isna(v):
            continue
        prior = latest.get(d)
        if prior is None:
            as_of = d  # newly seen — honest floor
        elif float(prior) != float(v):
            as_of = capture_date  # revision — new vintage stamped at capture time
        else:
            continue  # unchanged — skip
        rows.append(
            {
                "series_id": spec.series_id,
                "date": d,
                "value": float(v),
                "as_of": as_of,
                "source": spec.source,
                "frequency": spec.frequency.value,
                "unit": spec.unit,
                "last_updated": capture_date,
            }
        )
    return pd.DataFrame(rows, columns=store.COLUMNS)


def capture_series(
    spec: SeriesSpec,
    capture_date: pd.Timestamp,
    period: str = "2y",
    path: Path = store.FACTS_PATH,
) -> int:
    """Capture one premium series into the store. Returns rows written."""
    incoming = fetch_yf(spec.source_code, period=period)
    existing = store.get_series(spec.series_id, path=path)
    rows = plan_rows(spec, incoming, existing, capture_date)
    if rows.empty:
        return 0
    return store.write_observations(rows, path)


def run_all(
    capture_date: pd.Timestamp | None = None,
    path: Path = store.FACTS_PATH,
) -> dict[str, int]:
    """Capture every registry series with source == 'premium'. Returns {series_id: rows}."""
    if capture_date is not None:
        cap = pd.Timestamp(capture_date)
    else:
        cap = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    registry = load_registry()
    specs = [s for s in registry.values() if s.source == SOURCE]
    if not specs:
        raise PremiumCaptureError("no premium series declared in registry (source: premium)")
    written = {}
    for spec in specs:
        written[spec.series_id] = capture_series(spec, cap, path=path)
    return written


def main() -> int:
    """CLI entry point for the daily scheduled job."""
    from dotenv import load_dotenv

    load_dotenv()
    result = run_all()
    total = sum(result.values())
    for sid, n in result.items():
        print(f"  {sid}: {n} row(s)")
    print(f"premium capture complete — {total} new row(s) across {len(result)} series")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
