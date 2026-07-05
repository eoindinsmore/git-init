"""Premium capture tests — vintage discipline (offline) + real fixture parsing."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from adapters import premium
from quant import store
from registry.schema import Category, Frequency, SAStatus, SeriesSpec, Tags

SPEC = SeriesSpec(
    series_id="aluminium_premium_mw_us",
    source="premium",
    source_code="AUP=F",
    name="Aluminium US Midwest Premium (front-month)",
    unit="USD per pound",
    frequency=Frequency.D,
    sa_status=SAStatus.NSA,
    tags=Tags(metal="aluminium", country="US", category=Category.PRICE_PROXY),
    caveats="front-month proxy, not the forward curve",
)

CAP1 = pd.Timestamp("2026-01-10")
CAP2 = pd.Timestamp("2026-01-11")


def _inc(pairs):
    return pd.DataFrame({"date": pd.to_datetime([d for d, _ in pairs]),
                         "value": [v for _, v in pairs]})


def test_new_dates_stamped_at_observation_date():
    incoming = _inc([("2026-01-08", 1.00), ("2026-01-09", 1.02)])
    rows = premium.plan_rows(SPEC, incoming, pd.DataFrame(columns=["date", "value"]), CAP1)
    assert len(rows) == 2
    # newly seen -> as_of == observation date (honest floor)
    assert (pd.to_datetime(rows["as_of"]) == pd.to_datetime(rows["date"])).all()


def test_unchanged_dates_skipped():
    existing = _inc([("2026-01-08", 1.00)])
    incoming = _inc([("2026-01-08", 1.00), ("2026-01-09", 1.02)])
    rows = premium.plan_rows(SPEC, incoming, existing, CAP2)
    assert len(rows) == 1  # only the new date
    assert str(pd.to_datetime(rows["date"]).iloc[0].date()) == "2026-01-09"


def test_revision_kept_as_new_vintage_at_capture_date():
    existing = _inc([("2026-01-08", 1.00)])
    incoming = _inc([("2026-01-08", 0.95)])  # same date, changed value
    rows = premium.plan_rows(SPEC, incoming, existing, CAP2)
    assert len(rows) == 1
    assert float(rows["value"].iloc[0]) == 0.95
    assert pd.to_datetime(rows["as_of"].iloc[0]) == CAP2  # revision stamped at capture time


def test_daily_cycle_end_to_end(tmp_path):
    facts = tmp_path / "facts.parquet"
    # day 1: seed two dates
    r1 = premium.plan_rows(SPEC, _inc([("2026-01-08", 1.00), ("2026-01-09", 1.02)]),
                           store.get_series(SPEC.series_id, path=facts), CAP1)
    assert store.write_observations(r1, facts) == 2
    # day 2: one new date + a revision to 01-08
    day2 = _inc([("2026-01-08", 0.98), ("2026-01-09", 1.02), ("2026-01-10", 1.05)])
    r2 = premium.plan_rows(SPEC, day2, store.get_series(SPEC.series_id, path=facts), CAP2)
    assert store.write_observations(r2, facts) == 2  # revision + new date (01-09 unchanged skipped)
    # latest view reflects the revision
    latest = store.get_series(SPEC.series_id, path=facts)
    v = float(latest[latest["date"] == "2026-01-08"]["value"].iloc[0])
    assert v == 0.98
    # point-in-time before the revision still shows the original
    early = store.get_series(SPEC.series_id, as_of="2026-01-10", path=facts)
    assert float(early[early["date"] == "2026-01-08"]["value"].iloc[0]) == 1.00


def test_real_fixture_parses(fixture_dir: Path):
    df = premium.read_yf_csv(fixture_dir / "yf_AUP_midwest_premium.csv")
    assert len(df) > 100
    assert df["value"].notna().all()
    assert df["date"].is_monotonic_increasing
    # feeds cleanly into plan_rows against an empty store
    rows = premium.plan_rows(SPEC, df, pd.DataFrame(columns=["date", "value"]), CAP1)
    assert len(rows) == len(df)
