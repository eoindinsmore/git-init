"""Nowcast deliverables (spec §2): evolution charts and the accuracy-vs-information
curve, plus evaluation against naive benchmarks.

- **Evolution**: for one target period, the estimate ± band as a function of
  days-into-period, as inputs release (the ragged edge fills in).
- **Accuracy-vs-information**: across many periods, MAE as a function of how far into
  the period we are — quantifies how quickly the nowcast sharpens.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant.nowcast.core import BridgeModel, mae, naive_benchmarks


def _truncate(indicator_data: dict[str, pd.Series], as_of) -> dict[str, pd.Series]:
    cutoff = pd.Timestamp(as_of)
    return {k: v[v.index <= cutoff] for k, v in indicator_data.items()}


def nowcast_evolution(
    model: BridgeModel,
    indicator_data: dict[str, pd.Series],
    *,
    period_start,
    period_end,
    as_of_dates,
) -> pd.DataFrame:
    """Estimate ± band vs days-into-period for a single target period.

    At each ``as_of`` only indicator obs dated ≤ as_of are used (point-in-time). Returns
    ``[as_of, days_into_period, value, se, n_inputs]``."""
    start = pd.Timestamp(period_start)
    rows = []
    for as_of in as_of_dates:
        av = _truncate(indicator_data, as_of)
        value, se, n = model.predict_period(av, start, pd.Timestamp(period_end))
        rows.append({
            "as_of": pd.Timestamp(as_of),
            "days_into_period": (pd.Timestamp(as_of) - start).days,
            "value": value, "se": se, "n_inputs": n,
        })
    return pd.DataFrame(rows)


def accuracy_vs_information(
    model: BridgeModel,
    target: pd.Series,
    indicator_data: dict[str, pd.Series],
    *,
    step_days: int = 15,
    max_days: int = 120,
) -> pd.DataFrame:
    """MAE of the nowcast as a function of days-into-period, across all target periods.

    For each realized target period, nowcast at day 0, step, 2·step … then aggregate the
    absolute error at each horizon. Returns ``[days_into_period, mae, n_periods]``."""
    from quant.nowcast.core import period_bounds

    spans = period_bounds(pd.DatetimeIndex(target.index))
    horizons = list(range(0, max_days + 1, step_days))
    errs: dict[int, list[float]] = {h: [] for h in horizons}
    for end, (start, stop) in spans.items():
        actual = float(target.loc[end])
        for h in horizons:
            as_of = start + pd.Timedelta(days=h)
            if as_of > stop + pd.Timedelta(days=max_days):
                continue
            av = _truncate(indicator_data, as_of)
            value, _, n = model.predict_period(av, start, stop)
            if n > 0 and not np.isnan(value):
                errs[h].append(abs(actual - value))
    rows = [{"days_into_period": h, "mae": float(np.mean(v)) if v else np.nan,
             "n_periods": len(v)} for h, v in errs.items()]
    return pd.DataFrame(rows)


def benchmark_comparison(
    model: BridgeModel,
    target: pd.Series,
    indicator_data: dict[str, pd.Series],
    *,
    days_into_period: int = 30,
    seasonal_periods: int = 4,
) -> pd.DataFrame:
    """Nowcast MAE vs naive benchmarks (last value, seasonal naive) — mandatory eval.

    The nowcast is evaluated at a fixed information point (``days_into_period``)."""
    from quant.nowcast.core import period_bounds

    spans = period_bounds(pd.DatetimeIndex(target.index))
    now_pred = {}
    for end, (start, stop) in spans.items():
        as_of = start + pd.Timedelta(days=days_into_period)
        av = _truncate(indicator_data, as_of)
        value, _, n = model.predict_period(av, start, stop)
        if n > 0:
            now_pred[end] = value
    now_s = pd.Series(now_pred)
    benches = naive_benchmarks(target, seasonal_periods=seasonal_periods)
    out = {"nowcast": mae(target, now_s)}
    for name, fc in benches.items():
        out[name] = mae(target, fc)
    return pd.DataFrame([out])
