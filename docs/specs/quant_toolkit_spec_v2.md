# Quant Toolkit Specification v2 — `quant/`

Supersedes the Step 3 outline in CLAUDE.md. Perspective: this toolkit must stand up to
scrutiny from a quantamental commodities fund evaluating an analyst-with-PM-path
candidate. The recurring themes are: point-in-time honesty, multiple-testing
discipline, and every analytic ending in a positioning implication.

## 0. Cross-cutting foundation (build first — everything depends on it)

### 0.1 The `Signal` abstraction
Every module emits a standard object; backtester, dashboard, tracker, and reports
consume only this interface.

```python
class Signal(pydantic.BaseModel):
    signal_id: str
    values: pd.Series            # date-indexed, point-in-time constructed
    direction_convention: str    # "high = bullish <target>" etc.
    target: str                  # what it is meant to lead/explain
    provenance: list[str]        # registry series_ids used
    construction: str            # short human-readable methodology
    publication_lag_days: int    # worst-case lag of inputs
    created_as_of: date
    scorecard: ScorecardRef | None
```

### 0.2 Publication-lag metadata (registry extension)
Add to every registry entry: `publication_lag` (typical days from period-end to
release) and optionally `release_schedule`. Required for nowcasting and for honest
lead-lag testing. `get_series(series_id, as_of=...)` must respect it: the March value
of a series with 45-day lag is not knowable on April 1.

### 0.3 Scorecards
Every indicator/nowcast/model gets an auto-generated evaluation page (JSON + rendered
PDF/HTML): in-sample stats, out-of-sample stats, FDR status, stability plot, last
updated. `docs/scorecards/`. Nothing enters the "approved" set without one.

## 1. Leading-indicator lab (`quant/indicators/`)

Purpose: identify AND honestly validate leading indicators. Pipeline stages, each a
gate — a candidate must pass all to be promoted:

1. **Scan**: lead-lag correlation/regression of candidate(t−k) vs target(t) across
   k = 0..K, HAC (Newey–West) standard errors, on a training window only.
2. **Multiple-testing control**: Benjamini–Hochberg FDR across the full candidate ×
   lag grid. Report q-values. Raw t-stats alone never promote an indicator.
3. **Out-of-sample confirmation**: walk-forward predictive regression on the holdout;
   require positive OOS R² vs. a no-indicator benchmark (Campbell–Thompson style)
   or a Diebold–Mariano improvement over the benchmark forecast.
4. **Economic significance**: simple signal-to-position rule; the indicator must
   improve backtest P&L or forecast MAE by a material margin net of assumed costs.
5. **Stability check**: rolling-window beta plot; flag sign flips.

Output: promoted indicators become `Signal`s with scorecards. Rejected candidates are
logged too (`docs/scorecards/rejected/`) — the graveyard is part of the credibility
story.

## 2. Nowcasting (`quant/nowcast/`)

Purpose: current-quarter/current-month estimates of slow-release targets (e.g. global
IP, China aluminium demand proxy, regional apparent demand).

- **Method v1**: bridge equations — regress the low-frequency target on time-aggregated
  higher-frequency indicators; update the nowcast every time an input releases.
  No Kalman/DFM in v1 (possible v3 extension; do not start there).
- **Ragged-edge handling**: at any as_of date, use exactly the inputs available per
  publication-lag metadata; fill the remainder of the period with the bridge model's
  conditional expectation.
- **Vintage record (the key artifact)**: store every nowcast revision:
  `(target_period, as_of, value, se)`. Deliverables: (a) nowcast evolution chart —
  estimate ± band vs. days-into-period, with eventual actual overlaid;
  (b) accuracy-vs-information curve — MAE as a function of days into the period.
- Evaluation vs. naive benchmarks (last period's value, seasonal naive) is mandatory.

## 3. Backtester (`quant/backtest/`)

Purpose: signal → position → P&L, honestly.

- Signal-to-position: z-scored signal, capped (Carver-style forecast capping,
  reimplemented — never copy GPL code), volatility-targeted sizing.
- Walk-forward only; all parameters estimated point-in-time.
- Cost model: configurable per-instrument haircut (bps per unit turnover);
  premium contracts get a wide default (illiquid).
- Report per strategy: ann. return/vol/Sharpe, max drawdown, turnover, hit rate,
  exposure over time, and **bootstrap p-value / deflated-Sharpe commentary** given the
  number of strategy variants tried (record N-tried in the scorecard).
- Overlapping-horizon returns: HAC errors or non-overlapping resampling in any stats.

## 4. Price decomposition (`quant/decomp/`)

Purpose: "why did the price move" attribution — the weekly desk product.

- Rolling regression (window configurable, default ~2y weekly) of target returns on a
  driver set declared in a YAML spec per target (e.g. aluminium: broad USD, US 10y
  real yield, China activity composite from module 5, energy input composite, COT
  positioning change). Residual explicitly labelled "unexplained/idiosyncratic".
- Correlated-regressor policy: default = documented economic orthogonalization order
  (USD first, then rates, then activity, ...); optional Shapley/LMG allocation for
  robustness comparison. The choice and its consequences must be stated on the chart.
- Outputs: stacked-bar decomposition of any window's price change (week, month, YTD);
  rolling beta charts with stability flags; auto-generated one-page PDF.

## 5. Composite indicators (`quant/composites/`)

Purpose: aggregate many series into single indicators (activity composites, demand
proxies, financial-conditions style indices).

- Methods: diffusion index (% of components improving), coverage-weighted z-score
  average, PCA first component.
- **PCA rules**: loadings estimated point-in-time only (expanding or rolling window),
  sign-fixed against a declared reference series, ragged edges handled by
  per-date available-component reweighting. Full-sample PCA is look-ahead and is
  forbidden outside clearly-labelled exploratory notebooks.
- Composites are `Signal`s: they carry provenance and worst-case publication lag,
  and are eligible inputs to the indicator lab, nowcasts, and decomposition drivers.

## 6. Outlier / dislocation scanner (`quant/scanner/`)

Purpose: daily idea-generation screen across the whole registry.

- Universe: all price proxies, spreads, ratios, curve slopes (incl. CME premium curve),
  plus key macro surprise series. Derived pairs/ratios declared in YAML.
- Univariate: rolling z-scores of levels and of returns over multiple windows
  (20/60/250d); percentile ranks vs. own history.
- Multivariate: Mahalanobis distance of the daily move vector on the driver set —
  flags "this combination is unusual" even when no single series is extreme.
- Output: ranked daily table (top-N by |z|, new flags highlighted), rendered in the
  Streamlit app and exportable.
- **Tracker hook**: one action promotes a flagged outlier to a draft hypothesis in the
  trade tracker (pre-filled instrument, direction of mean-revert vs. momentum left to
  the analyst, link back to the scan record). Screen → thesis → sized call → outcome
  is the analyst-to-PM loop; the plumbing must make it one click.

## 7. Regime identification (`quant/regimes/`)

Purpose: simple, transparent, defensible market-state classification that other
modules consume.

- **v1 = rule-based** (deliberate choice; document why: explainability, no estimation
  instability, every historical classification auditable). State variables: VIX band,
  global manufacturing PMI level (>50/<50) × 3m delta (rising/falling), broad USD
  trend (price vs. 200d), optionally curve/positioning extremes.
- Core output: dated regime series + transition matrix + conditional performance
  tables (return distribution of each tracked asset per regime, with sample sizes and
  overlapping-data caveats).
- **Consumption hooks (mandatory — a regime model must do something)**:
  (a) forecast-combination weights conditional on regime;
  (b) sizing multiplier suggestion surfaced in the trade tracker;
  (c) regime banner on dashboards and PDF reports.
- v2 extension (later, optional): HMM comparison as a robustness exhibit, not a
  replacement.

## 8. Build order within the toolkit

1. Signal abstraction + registry publication-lag extension + scorecard skeleton
2. Decomposition module (fast to build, immediately demonstrable, forces the driver
   composites to exist in basic form)
3. Outlier scanner + tracker hook (idea-generation loop live early)
4. Indicator lab with FDR gates (the credibility core)
5. Composites (formalize what 2–3 prototyped)
6. Backtester
7. Nowcasting (flagship; needs lag metadata matured)
8. Regimes + consumption hooks

## 9. Interview-readiness checklist (why each piece exists)

- FDR-gated indicator lab → answers "how do you avoid data-mining?"
- Vintage-recorded nowcasts → answers "what did you know and when?"
- Cost-and-capacity-aware backtests with deflated-Sharpe commentary → answers
  "would this survive real capital?"
- Decomposition with documented orthogonalization choice → answers "do you understand
  your own tools' limits?"
- Scanner→tracker loop with calibration analytics → answers "can you go from research
  to sized risk?" — the PM-path question.
- Rejected-indicator graveyard → answers "do you report what didn't work?"
