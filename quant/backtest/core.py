"""Backtester engine — signal → position → P&L, honestly (spec §3).

Design commitments:
- **No look-ahead.** Positions are formed from information up to date t and earn the
  return from t to t+1 (``position.shift(1) * returns``). Every rolling estimate
  (z-score, realised vol) is trailing.
- **Reimplemented forecast capping.** The forecast is a trailing z-score of the signal
  capped at ±``cap`` — a from-scratch implementation of the capping *concept*; no code
  is copied from the GPL ``pysystemtrade`` (charter constraint #3).
- **Volatility targeting.** Position = capped forecast × (target vol / trailing realised
  vol of the instrument), so risk is comparable across instruments and time.
- **Costs.** A per-instrument bps-per-unit-turnover haircut, charged when the position
  changes.
- **Honest stats.** Deflated Sharpe (given the number of variants tried) and a
  block-bootstrap p-value account for multiple testing and autocorrelation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant import stats

# Approximate periods per year by inferred frequency (for annualisation).
PERIODS_PER_YEAR = {"D": 252, "W": 52, "M": 12, "Q": 4, "A": 1}


def rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    """Trailing z-score (point-in-time): (x − trailing_mean) / trailing_std."""
    mean = s.rolling(window, min_periods=max(3, window // 2)).mean()
    std = s.rolling(window, min_periods=max(3, window // 2)).std(ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (s - mean) / std
    return z.replace([np.inf, -np.inf], np.nan)


def capped_forecast(signal: pd.Series, *, window: int, cap: float = 2.0) -> pd.Series:
    """Trailing-z-scored signal, capped to ±``cap`` (reimplemented forecast capping)."""
    return rolling_zscore(signal, window).clip(-cap, cap)


def vol_target_position(
    forecast: pd.Series,
    returns: pd.Series,
    *,
    target_vol: float,
    vol_window: int,
    max_leverage: float = 3.0,
) -> pd.Series:
    """Scale the forecast to a per-period volatility target using trailing realised vol.

    ``target_vol`` is per-period (e.g. 0.01 = 1% per period). Realised vol is a trailing
    std of ``returns`` shifted by one period so only past data sets today's size."""
    realised = returns.rolling(vol_window, min_periods=max(3, vol_window // 2)).std(ddof=1)
    realised = realised.shift(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = target_vol / realised
    scale = scale.replace([np.inf, -np.inf], np.nan)
    pos = forecast * scale
    return pos.clip(-max_leverage, max_leverage)


@dataclass(frozen=True)
class BacktestResult:
    net: pd.Series = field(repr=False)  # per-period net P&L (return units)
    gross: pd.Series = field(repr=False)
    position: pd.Series = field(repr=False)
    equity: pd.Series = field(repr=False)  # cumulative net P&L
    metrics: dict = field(default_factory=dict)
    periods_per_year: int = 252
    n_variants_tried: int = 1


def _infer_ppy(index: pd.Index) -> int:
    if len(index) < 3:
        return 252
    med = pd.Series(index).diff().dt.days.median()
    if med <= 2:
        return 252
    if med <= 10:
        return 52
    if med <= 45:
        return 12
    if med <= 130:
        return 4
    return 1


def backtest(
    signal: pd.Series,
    returns: pd.Series,
    *,
    forecast_window: int = 52,
    cap: float = 2.0,
    target_vol: float = 0.01,
    vol_window: int = 52,
    cost_bps: float = 10.0,
    max_leverage: float = 3.0,
    n_variants_tried: int = 1,
    periods_per_year: int | None = None,
) -> BacktestResult:
    """Run a walk-forward, cost-aware backtest of ``signal`` on instrument ``returns``.

    Both are date-indexed; they are aligned on their common dates. ``cost_bps`` is
    charged on turnover (change in position). ``n_variants_tried`` feeds the deflated
    Sharpe — record how many strategy variants you tried (spec §3)."""
    # Align the signal onto the instrument's return dates using the most recent known
    # signal value (forward-fill) — point-in-time safe (never uses a future signal), and
    # it lets a weekly signal trade a monthly instrument (or vice-versa).
    returns = returns.astype(float).sort_index()
    sig_on_ret = signal.astype(float).sort_index().reindex(returns.index, method="ffill")
    df = pd.concat([sig_on_ret.rename("sig"), returns.rename("ret")], axis=1, sort=True).dropna()
    if len(df) < max(forecast_window, vol_window) + 5:
        raise ValueError("not enough overlapping observations to backtest")

    ppy = periods_per_year or _infer_ppy(df.index)
    forecast = capped_forecast(df["sig"], window=forecast_window, cap=cap)
    pos = vol_target_position(
        forecast, df["ret"], target_vol=target_vol, vol_window=vol_window,
        max_leverage=max_leverage,
    ).fillna(0.0)

    gross = pos.shift(1) * df["ret"]
    turnover = pos.diff().abs()
    cost = (cost_bps / 1e4) * turnover.shift(1)
    net = (gross - cost).dropna()
    pos_used = pos.loc[net.index]
    equity = net.cumsum()

    metrics = _performance(net, pos_used, turnover.loc[net.index], ppy, n_variants_tried)
    return BacktestResult(
        net=net, gross=gross.loc[net.index], position=pos_used, equity=equity,
        metrics=metrics, periods_per_year=ppy, n_variants_tried=n_variants_tried,
    )


def _performance(net, pos, turnover, ppy, n_variants_tried) -> dict:
    mean = float(net.mean())
    sd = float(net.std(ddof=1))
    sharpe_per = mean / sd if sd > 0 else np.nan
    equity = net.cumsum()
    drawdown = float((equity - equity.cummax()).min())
    hit = float((net > 0).mean())
    try:
        boot_p = stats.block_bootstrap_pvalue(net, block=min(20, len(net) // 3 or 1),
                                              n_boot=1000, seed=0)
    except ValueError:
        boot_p = np.nan
    dsr = (
        stats.deflated_sharpe(sharpe_per, n_obs=len(net), n_trials=n_variants_tried)
        if pd.notna(sharpe_per) else np.nan
    )
    return {
        "ann_return": mean * ppy,
        "ann_vol": sd * np.sqrt(ppy),
        "sharpe_ann": (sharpe_per * np.sqrt(ppy)) if pd.notna(sharpe_per) else np.nan,
        "sharpe_per_period": sharpe_per,
        "max_drawdown": drawdown,
        "avg_turnover": float(turnover.mean()),
        "hit_rate": hit,
        "bootstrap_pvalue": boot_p,
        "deflated_sharpe": dsr,
        "n_obs": len(net),
    }
