"""Forecast skill evaluation — does the model beat a random walk out of sample?

Reuses the tested stats core (walk-forward splits, Campbell–Thompson OOS-R²) rather than
re-implementing evaluation. Only *out-of-sample-valid* assumptions are evaluated: at each
split the forecast may use train-window information only, never future driver values —
so ``hold_last`` (drift) and ``momentum`` (trailing driver mean) are admissible;
``scenario`` is not evaluable (it is an assumption, not a forecast).

This is what the Workbench step-5 backtest reads to decide whether a forecast-derived
signal is worth trading.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from models.forecast import HOLD_LAST, MOMENTUM
from quant import stats
from quant.decomp.core import _resample_freq, to_returns


def _build_panel(target_levels, driver_levels, order, frequency, return_kind) -> pd.DataFrame:
    freq = _resample_freq(frequency)
    tgt = target_levels.astype(float).resample(freq).last()
    y = to_returns(tgt, return_kind).rename("__y__")
    driver_rets = pd.DataFrame(
        {k: to_returns(driver_levels[k].astype(float).resample(freq).last(), return_kind)
         for k in order}
    )
    return pd.concat([y, driver_rets], axis=1).dropna()


def walk_forward_skill(
    target_levels: pd.Series,
    driver_levels: dict[str, pd.Series],
    *,
    order: list[str],
    frequency: str = "W",
    return_kind: str = "log",
    est_window: int = 104,
    min_train: int = 104,
    driver_assumption: str = HOLD_LAST,
) -> dict:
    """Expanding-window, 1-step-ahead OOS evaluation vs a random-walk benchmark.

    At each split the regression is fit on the trailing ``est_window`` of the train block
    and the next period's target return is predicted (drift, plus the trailing driver mean
    for ``momentum``). The random-walk benchmark predicts a zero expected return. Returns a
    dict with ``oos_r2_vs_rw`` (>0 beats the random walk), MAE for both, and the sample
    size; skill claims are meaningless when ``n`` is small, so ``n`` is always returned.
    """
    pred = walk_forward_predictions(
        target_levels, driver_levels, order=order, frequency=frequency,
        return_kind=return_kind, est_window=est_window, min_train=min_train,
        driver_assumption=driver_assumption,
    )
    if pred.empty:
        return {"n": 0, "oos_r2_vs_rw": np.nan, "mae": np.nan, "mae_rw": np.nan,
                "driver_assumption": driver_assumption, "min_train": min_train}

    actual, fcast = pred["actual"], pred["pred"]
    bench = pd.Series(0.0, index=pred.index)  # random walk: zero expected return
    oos_r2 = stats.campbell_thompson_oos_r2(actual, fcast, bench)
    return {
        "n": len(pred),
        "oos_r2_vs_rw": float(oos_r2),
        "mae": float((actual - fcast).abs().mean()),
        "mae_rw": float((actual - bench).abs().mean()),
        "driver_assumption": driver_assumption,
        "min_train": min_train,
    }


def walk_forward_predictions(
    target_levels: pd.Series,
    driver_levels: dict[str, pd.Series],
    *,
    order: list[str],
    frequency: str = "W",
    return_kind: str = "log",
    est_window: int = 104,
    min_train: int = 104,
    driver_assumption: str = HOLD_LAST,
) -> pd.DataFrame:
    """Expanding-window 1-step-ahead predicted vs realized target returns (point-in-time).

    Returns a date-indexed frame ``[pred, actual]``. Each prediction uses train data only
    — the honest out-of-sample record the skill metrics and the strategy backtest build on.
    """
    order = [c for c in order if c in driver_levels]
    if not order:
        raise ValueError("no drivers available to evaluate")
    if driver_assumption not in (HOLD_LAST, MOMENTUM):
        raise ValueError("only hold_last and momentum are out-of-sample evaluable")
    panel = _build_panel(target_levels, driver_levels, order, frequency, return_kind)
    if len(panel) <= min_train:
        raise ValueError(f"not enough observations ({len(panel)}) for min_train={min_train}")

    preds, actuals, dates = [], [], []
    for train_idx, test_idx in stats.walk_forward_splits(
        panel.index, min_train=min_train, test_size=1, expanding=True
    ):
        train = panel.loc[train_idx]
        if est_window and len(train) > est_window:
            train = train.iloc[-est_window:]
        try:
            res = stats.ols_hac(train["__y__"], train[order])
        except ValueError:
            continue
        mu = float(res.params.get("const", 0.0))
        if driver_assumption == MOMENTUM:
            mu += sum(float(res.params.get(k, 0.0)) * float(train[k].mean()) for k in order)
        for d in test_idx:
            preds.append(mu)
            actuals.append(float(panel.loc[d, "__y__"]))
            dates.append(d)

    return pd.DataFrame({"pred": preds, "actual": actuals}, index=pd.DatetimeIndex(dates))
