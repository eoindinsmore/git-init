"""Parquet fact table — the append-only, point-in-time store of all observations.

Architecture contract (do not redesign without asking):

    long-format Parquet at data/facts.parquet, schema:
    series_id | date | value | as_of | source | frequency | unit | last_updated

Rules:
- **Append-only.** A revision is a NEW row with a later ``as_of``; existing rows
  are never overwritten. Re-ingesting an identical (series_id, date, as_of, value)
  row is a no-op (idempotent), so adapters can re-run safely.
- **Point-in-time.** ``get_series(series_id, as_of=...)`` returns the value that
  was known as of a given date — the latest vintage with ``as_of <= as_of`` for
  each observation date. Backtests must call this; they must never see a value
  that did not exist on their decision date.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
FACTS_PATH = DATA_DIR / "facts.parquet"

# Canonical column order and dtypes for the fact table.
COLUMNS = [
    "series_id",
    "date",
    "value",
    "as_of",
    "source",
    "frequency",
    "unit",
    "last_updated",
]
# Columns that together identify a single observation vintage.
_VINTAGE_KEY = ["series_id", "date", "as_of"]


def _empty_frame() -> pd.DataFrame:
    df = pd.DataFrame(columns=COLUMNS)
    return _coerce(df)


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    """Enforce column presence, order and dtypes. Raises on missing columns."""
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"observations missing required columns: {sorted(missing)}")
    df = df.loc[:, COLUMNS].copy()
    df["series_id"] = df["series_id"].astype("string")
    df["source"] = df["source"].astype("string")
    df["frequency"] = df["frequency"].astype("string")
    df["unit"] = df["unit"].astype("string")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    # Normalize every datetime column to tz-naive UTC. Sources vary (FRED naive,
    # Eurostat tz-aware); a single dtype keeps vintage merges and comparisons sane.
    for col in ("date", "as_of", "last_updated"):
        df[col] = pd.to_datetime(df[col], errors="coerce", utc=True).dt.tz_localize(None)
    return df


def read_facts(path: Path = FACTS_PATH) -> pd.DataFrame:
    """Return the full fact table (empty, correctly-typed frame if none exists)."""
    if not path.exists():
        return _empty_frame()
    return _coerce(pd.read_parquet(path))


def write_observations(df: pd.DataFrame, path: Path = FACTS_PATH) -> int:
    """Append observations to the fact table, append-only and idempotent.

    Rows whose (series_id, date, as_of) already exist with the same value are
    dropped (idempotent re-runs). A row with an existing (series_id, date, as_of)
    but a DIFFERENT value is a provenance conflict and raises — the store never
    silently rewrites a vintage.

    Returns the number of new rows actually written.
    """
    incoming = _coerce(df)
    if incoming["date"].isna().any() or incoming["as_of"].isna().any():
        raise ValueError(
            "every observation must have a valid 'date' and 'as_of' (point-in-time discipline)"
        )

    # De-dup within the incoming batch first.
    incoming = incoming.drop_duplicates(subset=_VINTAGE_KEY + ["value"])

    existing = read_facts(path)
    if not existing.empty:
        merged = incoming.merge(
            existing[_VINTAGE_KEY + ["value"]],
            on=_VINTAGE_KEY,
            how="left",
            suffixes=("", "_existing"),
        )
        conflicts = merged[
            merged["value_existing"].notna() & (merged["value"] != merged["value_existing"])
        ]
        if not conflicts.empty:
            s = conflicts.iloc[0]
            raise ValueError(
                f"vintage conflict for series '{s['series_id']}' "
                f"date={s['date'].date()} as_of={s['as_of'].date()}: "
                f"existing value {s['value_existing']} != incoming {s['value']}. "
                "Revisions must use a new as_of, not rewrite a vintage."
            )
        # Keep only genuinely new rows (no existing value for this vintage key).
        new_rows = incoming[merged["value_existing"].isna().to_numpy()]
    else:
        new_rows = incoming

    if new_rows.empty:
        return 0

    combined = pd.concat([existing, new_rows], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return len(new_rows)


def get_series(
    series_id: str,
    as_of: str | pd.Timestamp | None = None,
    path: Path = FACTS_PATH,
) -> pd.DataFrame:
    """Point-in-time retrieval for one series.

    Returns a frame [date, value] with the latest vintage known as of ``as_of``
    for each observation date. With ``as_of=None`` the newest vintage of each
    date is returned (the "current best" view). Result is sorted by date.
    """
    facts = read_facts(path)
    sel = facts[facts["series_id"] == series_id]
    if as_of is not None:
        cutoff = pd.to_datetime(as_of)
        sel = sel[sel["as_of"] <= cutoff]
    if sel.empty:
        return pd.DataFrame({
            "date": pd.Series(dtype="datetime64[ns]"),
            "value": pd.Series(dtype="float64"),
        })

    # For each date keep the row with the greatest as_of (latest vintage <= cutoff).
    sel = sel.sort_values(["date", "as_of"])
    latest = sel.groupby("date", as_index=False).last()
    return latest[["date", "value"]].sort_values("date").reset_index(drop=True)
