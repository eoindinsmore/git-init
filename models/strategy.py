"""Regression-derived strategy backtest with an optional regime filter (Workbench step 5).

Turns the walk-forward regression forecast into a position and marks it against the
target's own realized returns — the honest "would this way of reading the drivers have
made money" check. Deliberately a *transparent* sign-following rule (position = sign of
the one-step-ahead predicted return, held for the period, charged turnover cost) rather
than the vol-targeting :mod:`quant.backtest` engine, whose one-period forecast lag suits a
persistent signal, not a one-step prediction. The vol-targeted engine remains available
for a persistent-forecast signal as a follow-up.

Point-in-time: every position uses a prediction fit on data strictly before the period it
trades (see :func:`models.evaluate.walk_forward_predictions`). The regime filter flattens
the book outside the analyst-chosen regimes — the "additional filter" of the spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from models.evaluate import MOMENTUM, walk_forward_predictions
from quant import stats

_PPY = {"D": 252, "W": 52, "M": 12, "Q": 4, "A": 1}


@dataclass(frozen=True)
class StrategyResult:
    equity: pd.Series = field(repr=False)  # cumulative net return
    net: pd.Series = field(repr=False)  # per-period net return
    position: pd.Series = field(repr=False)  # position in {-1, 0, +1}
    n: int
    hit_rate: float
    sharpe_ann: float
    cumulative_return: float
    bootstrap_pvalue: float
    cost_bps: float
    regime_filtered: bool
    periods_in_market: int


def backtest_regression(
    target_levels: pd.Series,
    driver_levels: dict[str, pd.Series],
    *,
    order: list[str],
    frequency: str = "W",
    return_kind: str = "log",
    est_window: int = 104,
    min_train: int = 104,
    driver_assumption: str = MOMENTUM,
    cost_bps: float = 10.0,
    regimes: pd.Series | None = None,
    allowed_regimes: list[str] | None = None,
) -> StrategyResult:
    """Backtest the sign of the one-step regression forecast on the target's returns.

    When ``regimes`` and ``allowed_regimes`` are given, the position is flattened (0)
    whenever the prevailing regime is not in the allowed set — the regime filter. Costs
    are charged on turnover; the honest bootstrap p-value (mean net ≤ 0) is reported."""
    pred = walk_forward_predictions(
        target_levels, driver_levels, order=order, frequency=frequency,
        return_kind=return_kind, est_window=est_window, min_train=min_train,
        driver_assumption=driver_assumption,
    )
    if pred.empty:
        raise ValueError("no out-of-sample predictions were produced")

    position = np.sign(pred["pred"]).astype(float)
    filtered = False
    if regimes is not None and allowed_regimes:
        r = regimes.sort_index().reindex(pred.index, method="ffill")
        position = position.where(r.isin(allowed_regimes), 0.0)
        filtered = True

    turnover = position.diff().abs()
    turnover.iloc[0] = abs(position.iloc[0])
    cost = (cost_bps / 1e4) * turnover
    net = (position * pred["actual"] - cost).dropna()
    equity = net.cumsum()

    ppy = _PPY.get(frequency, 52)
    std = float(net.std(ddof=1))
    sharpe_ann = float(net.mean() / std * np.sqrt(ppy)) if std > 0 else float("nan")
    in_market = net[position.loc[net.index] != 0]
    hit_rate = float((in_market > 0).mean()) if len(in_market) else float("nan")
    try:
        boot_p = stats.block_bootstrap_pvalue(net)
    except ValueError:
        boot_p = float("nan")

    return StrategyResult(
        equity=equity,
        net=net,
        position=position,
        n=len(net),
        hit_rate=hit_rate,
        sharpe_ann=sharpe_ann,
        cumulative_return=float(equity.iloc[-1]) if len(equity) else float("nan"),
        bootstrap_pvalue=float(boot_p),
        cost_bps=cost_bps,
        regime_filtered=filtered,
        periods_in_market=int((position.loc[net.index] != 0).sum()),
    )
