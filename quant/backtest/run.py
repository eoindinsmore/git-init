"""Wire the backtester to the store and to `Signal`s (spec §3)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from quant import pit, store
from quant.backtest.core import BacktestResult, backtest
from quant.signal import Signal

# Wide default cost for illiquid premium contracts; tighter for liquid proxies.
DEFAULT_COST_BPS = {
    "aluminium_premium_mw_us": 50.0,
    "aluminium_premium_eu_dp": 50.0,
    "copper_price_global": 10.0,
}


def instrument_returns(
    series_id: str,
    *,
    as_of: str | pd.Timestamp | None = None,
    kind: str = "log",
    registry_dir: Path | None = None,
    path: Path = store.FACTS_PATH,
) -> pd.Series:
    """Point-in-time period returns of an instrument's price series."""
    if as_of is None:
        f = store.get_series(series_id, as_of=None, path=path)
    else:
        f = pit.get_series_asof(series_id, as_of, registry_dir=registry_dir, path=path)
    if f.empty:
        return pd.Series(dtype=float)
    lv = pd.Series(f["value"].to_numpy(), index=pd.DatetimeIndex(f["date"])).astype(float)
    return np.log(lv).diff() if kind == "log" else lv.pct_change()


def backtest_signal(
    signal: Signal,
    instrument_id: str,
    *,
    as_of: str | pd.Timestamp | None = None,
    cost_bps: float | None = None,
    n_variants_tried: int = 1,
    registry_dir: Path | None = None,
    path: Path = store.FACTS_PATH,
    **kwargs,
) -> BacktestResult:
    """Backtest a `Signal` as a position rule on ``instrument_id``'s returns.

    ``cost_bps`` defaults to a per-instrument haircut (wide for illiquid premiums)."""
    rets = instrument_returns(instrument_id, as_of=as_of, registry_dir=registry_dir, path=path)
    if rets.empty:
        raise ValueError(f"instrument '{instrument_id}' has no data in the store")
    cb = cost_bps if cost_bps is not None else DEFAULT_COST_BPS.get(instrument_id, 20.0)
    return backtest(
        signal.values, rets, cost_bps=cb, n_variants_tried=n_variants_tried, **kwargs
    )


def signal_sharpe(
    signal_values: pd.Series,
    returns: pd.Series,
    *,
    cost_bps: float = 10.0,
    n_variants_tried: int = 1,
    **kwargs,
) -> float:
    """Convenience: the annualised net Sharpe of trading ``signal_values`` on ``returns``.

    Used by the indicator lab's economic-significance gate (Phase-5 retrofit)."""
    try:
        res = backtest(signal_values, returns, cost_bps=cost_bps,
                       n_variants_tried=n_variants_tried, **kwargs)
    except ValueError:
        return float("nan")
    return float(res.metrics["sharpe_ann"])
