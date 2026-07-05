# Analysis Workbench + engine additions — handover

Built overnight 2026-07-05→06 on branch `quant-toolkit`, after the trade-tracker session
finished. Turns the seven disconnected toolkit pages into one **guided six-step flow** and
makes the dislocation screen **visual**. Specs: `docs/specs/decomp_timeseries_spec.md`,
`docs/specs/forecast_model_spec.md` (both drafted then implemented — **not yet reviewed by
the user**; veto welcome).

## Engine additions (all tested, zero-analytics rule held — app calls these, does no maths)

- **`quant/decomp` — `contribution_timeseries()` + `ContributionSeries`** (`core.py`), run
  wrapper `run_contribution_timeseries()` + `ContributionTSRun` (`run.py`). The stacked-area
  companion to `decompose()`: per-period `βᵢ·zᵢ(t)` from the *same* fit, so summed over the
  window it reconciles with the single-window bar exactly, and (log returns) the cumulative
  bands offset by `level_start` reconstruct the price path — a tested invariant. `run.py`
  refactor: shared `fetch_levels()` used by both runners. Tests: `tests/test_decomp_timeseries.py`.
- **`models/` (new package, project step 4)** — separate namespace from the tracker
  (forecasts are not calls, tracker spec §6):
  - `forecast.py` — `forecast()` core + `run_forecast()` runner + `Forecast`. Extrapolates a
    plain OLS of target returns on **raw** driver returns (total betas — the right basis for
    forecasting a marginal driver move; the decomposition's orthogonalized betas are for
    additive attribution). Driver-path assumptions: `hold_last` (drift-only), `momentum`,
    `scenario` (analyst supplies per-period driver returns). Band = `point·exp(±z·σ·√k)`,
    understatement stamped in `notes`.
  - `evaluate.py` — `walk_forward_predictions()` (PIT one-step preds) + `walk_forward_skill()`
    (OOS-R² vs random walk, MAE, n) reusing `quant.stats`.
  - `strategy.py` — `backtest_regression()`: transparent sign-following P&L on the target's
    own returns with an **optional regime filter** (flattens the book outside allowed regimes),
    honest bootstrap p-value. Deliberately NOT the vol-targeting `quant.backtest` engine, whose
    one-period forecast lag mismatches a one-step prediction (documented in the module).
  - Tests: `tests/test_forecast.py`, `tests/test_strategy.py`.
  - **Gotcha:** the pure `forecast()` is intentionally not re-exported from `models/__init__`
    (it would shadow the `models.forecast` submodule). Import as `from models.forecast import forecast`.
- **`quant/scanner` — `mahalanobis_timeseries()`** (`core.py`) + `run_mahalanobis_timeseries()`
  (`run.py`): the joint-dislocation screen as a rolling time series. Tests appended to
  `tests/test_scanner.py`.

## UI

- **`app/pages/0_Workbench.py`** — the guided flow. Shared sidebar selection (target + drivers
  + frequency + est-window) threads through six tabs: **1 Scatter** (target vs driver returns,
  Altair regression aid) · **2 Regression** (HAC betas, R², orthogonalization order, missing
  drivers) · **3 Decomposition** (stacked-area contribution over time + reconciliation caption)
  · **4 Forecast** (path + band, `hold_last`/`momentum`/`scenario`) · **5 Backtest** (walk-forward
  skill vs RW + regime-filtered sign strategy) · **6 Recommend** (pre-filled `tracker.calls.new_call`
  draft; the human submits). Free-pick, so it works regardless of which declared drivers exist.
- **`app/pages/4_Scanner.py`** — redesigned from a dataframe to: the **dislocation map**
  (return-z vs level-z scatter, size |z|, brick = flagged), **joint dislocation over time**
  (rolling Mahalanobis; hidden when the set has too little history), and a **per-item inspect
  card** (price sparkline + level/move z + percentile). Full ranked table demoted to an expander.
- **`app/toolkit_ui.py`** — new presentation helpers: `scatter_chart`, `stacked_contribution_area`,
  `forecast_chart`, `universe_scatter`.

## Verified

- `pytest -q` green (all suites incl. 16 new tests); `ruff check` clean across quant/ models/ app/ tests/.
- Rendered via the Streamlit dev server: Workbench tabs 1–6 compute without error (scatter,
  stacked area, forecast, backtest equity all draw); Scanner map + inspect card render.
- **Honest observation, not a bug:** with copper ~ US IP + COT (the only decomp drivers in the
  store), step-5 OOS-R² vs random walk is ≈ 0 and the page says so. The declared USD/real-yield/
  energy drivers are still missing (`docs/quant_data_gaps.md`); the free FRED quick-wins
  (`DTWEXBGS`, `DFII10`, `VIXCLS`) would materially improve every step.

## Known follow-ups / judgment calls left for review

- **Page demotion not done structurally.** The 7 toolkit pages still appear in the flat nav
  (renaming files / `st.navigation` sections is a nav restructure best done with you). The
  Workbench sorts first (`0_`) and is the intended primary path.
- Forecast interval ignores parameter uncertainty (v1, caveated). `betas="rolling"` for the
  stacked area is spec'd but not built. Regime filter needs the global-macro state series in the
  store to light up (currently degrades gracefully to no filter).
- `models.forecast` design deviates from the draft spec's "reuse the decomposition fit" — it
  refits total betas instead. Rationale in the module docstring; flag if you'd rather couple them.
