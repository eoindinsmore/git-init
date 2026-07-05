"""Nowcasting via bridge equations (spec §2).

A bridge equation regresses a slow-release low-frequency target (e.g. quarterly IP)
on **time-aggregated** higher-frequency indicators, then updates the current-period
estimate every time an input releases. Ragged edges — a partial current period — are
handled by using the bridge's conditional expectation for the missing remainder; with
a *mean* aggregation the period-to-date mean is itself an unbiased estimate of the
full-period mean, which is the conditional expectation we use here.

No Kalman/DFM in v1 (spec: a v3 possibility; do not start there).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant import stats


def period_bounds(target_index: pd.DatetimeIndex) -> dict[pd.Timestamp, tuple]:
    """Map each target period-end to its ``(start, end]`` span.

    A period runs from the day after the previous period-end to this period-end. The
    first period is back-dated by the modal spacing of the index."""
    idx = pd.DatetimeIndex(target_index).sort_values()
    spans: dict[pd.Timestamp, tuple] = {}
    if len(idx) == 0:
        return spans
    gap = pd.Series(idx).diff().dropna()
    modal = gap.median() if len(gap) else pd.Timedelta(days=30)
    prev = idx[0] - modal
    for end in idx:
        spans[end] = (prev + pd.Timedelta(days=1), end)
        prev = end
    return spans


def aggregate_over(indicator: pd.Series, start, end, *, how: str = "mean") -> float:
    """Aggregate an indicator's observations within ``[start, end]``.

    ``mean`` (default) makes the partial-period value a valid conditional expectation
    of the full-period value under within-period stationarity — the ragged-edge fill."""
    s = indicator[(indicator.index >= start) & (indicator.index <= end)].dropna()
    if s.empty:
        return np.nan
    if how == "mean":
        return float(s.mean())
    if how == "sum":
        return float(s.sum())
    if how == "last":
        return float(s.iloc[-1])
    raise ValueError("how must be 'mean', 'sum' or 'last'")


@dataclass
class BridgeModel:
    indicators: list[str]
    agg: str = "mean"
    params: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    resid_std: float = float("nan")
    nobs: int = 0

    def fit(self, target: pd.Series, indicator_data: dict[str, pd.Series]) -> BridgeModel:
        """Fit ``target ~ const + Σ aggregated indicator`` over fully-covered periods."""
        spans = period_bounds(pd.DatetimeIndex(target.index))
        rows = []
        for end, (start, stop) in spans.items():
            feat = {ind: aggregate_over(indicator_data[ind], start, stop, how=self.agg)
                    for ind in self.indicators if ind in indicator_data}
            feat["__y__"] = float(target.loc[end])
            feat["__end__"] = end
            rows.append(feat)
        df = pd.DataFrame(rows).set_index("__end__").dropna()
        if len(df) < len(self.indicators) + 2:
            raise ValueError("not enough fully-covered periods to fit the bridge")
        res = stats.ols_hac(df["__y__"], df[self.indicators])
        self.params = res.params
        self.resid_std = float(res.resid.std(ddof=1))
        self.nobs = res.nobs
        return self

    def predict_period(
        self, indicator_data: dict[str, pd.Series], start, end
    ) -> tuple[float, float, int]:
        """Nowcast one period from whatever indicator data is available in ``[start, end]``.

        Returns ``(value, se, n_inputs_used)``. Missing indicators fall back to the fitted
        constant's implicit expectation (dropped from the linear term)."""
        if self.params.empty:
            raise ValueError("model is not fitted")
        pred = float(self.params.get("const", 0.0))
        used = 0
        for ind in self.indicators:
            if ind not in indicator_data:
                continue
            val = aggregate_over(indicator_data[ind], start, end, how=self.agg)
            if not np.isnan(val):
                pred += float(self.params.get(ind, 0.0)) * val
                used += 1
        return pred, self.resid_std, used


def naive_benchmarks(target: pd.Series, *, seasonal_periods: int = 4) -> dict[str, pd.Series]:
    """Benchmark forecasts a nowcast must beat: last value (RW) and seasonal naive."""
    t = target.sort_index()
    return {
        "last_value": t.shift(1),
        "seasonal_naive": t.shift(seasonal_periods),
    }


def mae(actual: pd.Series, forecast: pd.Series) -> float:
    df = pd.concat([actual.rename("a"), forecast.rename("f")], axis=1, sort=True).dropna()
    if df.empty:
        return float("nan")
    return float((df["a"] - df["f"]).abs().mean())
