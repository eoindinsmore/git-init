# Backtester — handover (spec §3)

Signal → position → P&L, honestly. Answers "would this survive real capital?"

## Public interface (`quant.backtest`)
- **`backtest(signal, returns, *, forecast_window, cap, target_vol, vol_window, cost_bps,
  max_leverage, n_variants_tried, periods_per_year)` → `BacktestResult`** — the engine.
- **`backtest_signal(signal, instrument_id, *, as_of=None, cost_bps=None, n_variants_tried,
  ...)`** — backtest a `Signal` on a stored instrument's returns; `cost_bps` defaults to a
  per-instrument haircut (wide for illiquid premiums).
- **`signal_sharpe(signal_values, returns, ...)`** — convenience net annual Sharpe; used by
  the indicator lab's economic gate (retrofit, below).
- **`to_scorecard(result, ...)` / `render_html(result)`** — evaluation artifact + tearsheet.
- Building blocks: `capped_forecast`, `vol_target_position`, `rolling_zscore`.

## Method
- **Forecast:** trailing z-score of the signal, capped at ±`cap` — a from-scratch
  reimplementation of the forecast-capping *concept*; **no GPL `pysystemtrade` code copied**
  (charter #3).
- **Sizing:** volatility targeting — position scaled by `target_vol / trailing_realised_vol`
  (realised vol shifted one period), clipped to `max_leverage`.
- **No look-ahead:** positions earn `position.shift(1) * returns`; every estimate is trailing.
  Verified: truncating future data does not change any past P&L
  (test_backtest.py::test_no_lookahead...).
- **Costs:** `cost_bps` per unit turnover, charged when the position changes.
- **Frequency alignment:** the signal is forward-filled onto the instrument's return dates
  (most-recent-known value), so a weekly signal can trade a monthly instrument.

## Honest statistics (the headline)
`BacktestResult.metrics`: `sharpe_ann`, `ann_return`, `ann_vol`, `max_drawdown`,
`avg_turnover`, `hit_rate`, plus **`bootstrap_pvalue`** (circular block bootstrap — respects
autocorrelation of overlapping returns) and **`deflated_sharpe`** (discounts the Sharpe for
`n_variants_tried`). Record how many variants you tried — it is a first-class input.

## Indicator-lab retrofit
`LabConfig(use_backtester=True)` makes the indicator lab's economic-significance gate (gate 4)
call this backtester instead of the lightweight stub.

## Data dependencies / gaps
Reads the fact table. Real-data smoke (positioning composite → copper): negative Sharpe,
deflated Sharpe ≈ 0 — the machinery honestly reports a non-surviving strategy rather than
flattering it. Per-instrument cost defaults live in `run.DEFAULT_COST_BPS`; premium contracts
get a wide illiquid default.

## Known limitations
- Single-instrument backtests only (no portfolio/cross-sectional combination yet).
- Cost model is a flat bps haircut; no slippage/impact curve.
- Annualisation frequency is inferred from the return index spacing (overridable).

## How to test
```
.venv/Scripts/python -m pytest tests/test_backtest.py -q
```
