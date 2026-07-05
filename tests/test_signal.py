"""Tests for quant.signal — the Signal abstraction and its guardrails."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from pydantic import ValidationError

from quant.signal import ScorecardRef, Signal, worst_case_lag


def _series(dates: list[str], vals: list[float]) -> pd.Series:
    return pd.Series(vals, index=pd.DatetimeIndex(dates))


def _valid_kwargs(**over):
    base = dict(
        signal_id="test_sig",
        values=_series(["2020-01-01", "2020-02-01", "2020-03-01"], [1.0, 2.0, 3.0]),
        direction_convention="high = bullish copper",
        target="copper_price_global",
        provenance=["us_industrial_production"],
        construction="z-score of IP YoY",
        publication_lag_days=16,
        created_as_of=date(2020, 4, 1),
    )
    base.update(over)
    return base


def test_valid_signal_builds_and_names_series():
    sig = Signal(**_valid_kwargs())
    assert sig.values.name == "test_sig"  # auto-named from signal_id
    assert sig.scorecard is None


def test_to_frame_shape():
    sig = Signal(**_valid_kwargs())
    frame = sig.to_frame()
    assert list(frame.columns) == ["date", "value"]
    assert len(frame) == 3
    assert frame["value"].tolist() == [1.0, 2.0, 3.0]


def test_rejects_non_datetime_index():
    with pytest.raises(ValidationError, match="DatetimeIndex"):
        Signal(**_valid_kwargs(values=pd.Series([1.0, 2.0], index=[0, 1])))


def test_rejects_unsorted_index():
    bad = _series(["2020-03-01", "2020-01-01"], [3.0, 1.0])
    with pytest.raises(ValidationError, match="sorted"):
        Signal(**_valid_kwargs(values=bad))


def test_rejects_duplicate_dates():
    bad = _series(["2020-01-01", "2020-01-01"], [1.0, 2.0])
    with pytest.raises(ValidationError, match="duplicate"):
        Signal(**_valid_kwargs(values=bad))


def test_rejects_empty_provenance():
    with pytest.raises(ValidationError, match="provenance"):
        Signal(**_valid_kwargs(provenance=[]))


def test_rejects_negative_lag():
    with pytest.raises(ValidationError, match="publication_lag_days"):
        Signal(**_valid_kwargs(publication_lag_days=-1))


def test_resolve_as_of_applies_own_lag():
    # lag 16d: the 1 Mar value is usable from 17 Mar onward.
    sig = Signal(**_valid_kwargs(publication_lag_days=16))
    on_10mar = sig.resolve_as_of("2020-03-10")
    assert on_10mar.index.max() == pd.Timestamp("2020-02-01")  # Mar not yet released
    on_20mar = sig.resolve_as_of("2020-03-20")
    assert on_20mar.index.max() == pd.Timestamp("2020-03-01")  # Mar now released


def test_scorecard_ref_attaches():
    ref = ScorecardRef(scorecard_id="sc1", path="docs/scorecards/sc1.json")
    sig = Signal(**_valid_kwargs(scorecard=ref))
    assert sig.scorecard.scorecard_id == "sc1"


class _Spec:
    def __init__(self, lag):
        self.publication_lag_days = lag


def test_worst_case_lag_picks_max():
    registry = {"a": _Spec(3), "b": _Spec(40), "c": _Spec(16)}
    assert worst_case_lag(["a", "b", "c"], registry) == 40


def test_worst_case_lag_unknown_id_raises():
    with pytest.raises(KeyError):
        worst_case_lag(["missing"], {"a": _Spec(3)})
