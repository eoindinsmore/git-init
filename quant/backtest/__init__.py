"""Backtester — signal → position → P&L, honestly (spec §3)."""

from __future__ import annotations

from quant.backtest.core import (
    BacktestResult,
    backtest,
    capped_forecast,
    rolling_zscore,
    vol_target_position,
)
from quant.backtest.report import render_html, to_scorecard
from quant.backtest.run import backtest_signal, instrument_returns, signal_sharpe

__all__ = [
    "BacktestResult",
    "backtest",
    "backtest_signal",
    "capped_forecast",
    "instrument_returns",
    "render_html",
    "rolling_zscore",
    "signal_sharpe",
    "to_scorecard",
    "vol_target_position",
]
