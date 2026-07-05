"""Parquet fact-table store tests — append-only + point-in-time invariants."""

from __future__ import annotations

import pandas as pd
import pytest

from quant import store


def _row(sid, date, value, as_of, last_updated="2026-01-01"):
    return dict(series_id=sid, date=date, value=value, as_of=as_of,
                source="fred", frequency="M", unit="u", last_updated=last_updated)


def test_append_idempotent_and_revision(tmp_path):
    p = tmp_path / "facts.parquet"
    df1 = pd.DataFrame([_row("s", "2020-01-01", 100.0, "2020-02-15"),
                        _row("s", "2020-02-01", 101.0, "2020-03-15")])
    assert store.write_observations(df1, p) == 2
    assert store.write_observations(df1, p) == 0  # idempotent
    # revision: same date, later as_of, new value -> a new row
    rev = pd.DataFrame([_row("s", "2020-01-01", 99.5, "2020-03-15")])
    assert store.write_observations(rev, p) == 1
    assert len(store.read_facts(p)) == 3


def test_point_in_time(tmp_path):
    p = tmp_path / "facts.parquet"
    store.write_observations(pd.DataFrame([
        _row("s", "2020-01-01", 100.0, "2020-02-15"),
        _row("s", "2020-01-01", 99.5, "2020-03-15"),  # revision
    ]), p)
    # as of before the revision we only knew 100.0
    early = store.get_series("s", "2020-02-20", p)
    assert float(early["value"].iloc[0]) == 100.0
    # latest view sees the revision
    latest = store.get_series("s", None, p)
    assert float(latest["value"].iloc[0]) == 99.5


def test_vintage_conflict_fails_loudly(tmp_path):
    p = tmp_path / "facts.parquet"
    store.write_observations(pd.DataFrame([_row("s", "2020-01-01", 100.0, "2020-02-15")]), p)
    with pytest.raises(ValueError, match="vintage conflict"):
        store.write_observations(pd.DataFrame([_row("s", "2020-01-01", 999.0, "2020-02-15")]), p)


def test_missing_date_or_asof_rejected(tmp_path):
    p = tmp_path / "facts.parquet"
    with pytest.raises(ValueError, match="valid 'date' and 'as_of'"):
        store.write_observations(pd.DataFrame([_row("s", None, 100.0, "2020-02-15")]), p)
