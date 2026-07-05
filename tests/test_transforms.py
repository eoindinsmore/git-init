"""Tests for quant.transforms — the dashboard's growth/level/MA transforms."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant import transforms as tf


def _monthly(values: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame({"date": dates, "value": values})


def test_level_is_passthrough_sorted():
    df = _monthly([3.0, 1.0, 2.0])
    df = df.iloc[::-1].reset_index(drop=True)  # feed out of order
    out = tf.apply(df, "level", "M")
    assert list(out["value"]) == [3.0, 1.0, 2.0]
    assert out["date"].is_monotonic_increasing


def test_yoy_pct_monthly_lags_12():
    # 13 months: month 13 is +10% vs month 1.
    vals = [100.0] * 12 + [110.0]
    out = tf.apply(_monthly(vals), "yoy_pct", "M")
    # First 12 rows are undefined (dropped); one row remains.
    assert len(out) == 1
    assert out["value"].iloc[0] == pytest.approx(10.0)


def test_mom_pct_and_levels():
    out_pct = tf.apply(_monthly([100.0, 110.0]), "mom_pct", "M")
    assert out_pct["value"].iloc[-1] == pytest.approx(10.0)
    out_lvl = tf.apply(_monthly([100.0, 110.0]), "mom_lvl", "M")
    assert out_lvl["value"].iloc[-1] == pytest.approx(10.0)


def test_yoy_levels_quarterly_lags_4():
    vals = [10.0, 11.0, 12.0, 13.0, 15.0]  # Q5 - Q1 = 5
    out = tf.apply(_monthly(vals), "yoy_lvl", "Q")
    assert len(out) == 1
    assert out["value"].iloc[0] == pytest.approx(5.0)


def test_ma3_mom_levels_smooths_first():
    # 3-mo MA of [1,2,3,4] = [_, _, 2, 3]; MoM diff of the MA = [_, _, _, 1].
    out = tf.apply(_monthly([1.0, 2.0, 3.0, 4.0]), "ma3_mom_lvl", "M")
    assert len(out) == 1
    assert out["value"].iloc[0] == pytest.approx(1.0)


def test_divide_by_zero_becomes_nan_not_inf():
    out = tf.apply(_monthly([0.0, 5.0]), "mom_pct", "M")
    # denom is 0 -> undefined -> dropped, not an inf row.
    assert not np.isinf(out["value"]).any()
    assert len(out) == 0


def test_default_kind_from_registry_tokens():
    assert tf.default_kind(["yoy"]) == "yoy_pct"
    assert tf.default_kind([]) == "level"
    assert tf.default_kind(["unknown_token"]) == "level"


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown transform kind"):
        tf.apply(_monthly([1.0, 2.0]), "bogus", "M")


def test_unknown_frequency_raises_for_growth():
    with pytest.raises(ValueError, match="unknown frequency"):
        tf.apply(_monthly([1.0, 2.0]), "yoy_pct", "Z")


def test_empty_frame_roundtrips():
    empty = pd.DataFrame(
        {"date": pd.Series(dtype="datetime64[ns]"), "value": pd.Series(dtype=float)}
    )
    out = tf.apply(empty, "yoy_pct", "M")
    assert out.empty
