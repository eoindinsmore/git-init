# Short-term Forecast Model Spec — `models/`

Purpose: a short-horizon price forecast for a target, **built from the same regression as
the decomposition** (step 3 → step 4 of the Analysis Workbench). Given the fitted
driver→target relationship and an assumption about where the drivers go, project the
target forward with an honest uncertainty band. This is the first occupant of the
currently-empty `models/` namespace.

**Hard boundary (tracker spec §6):** model forecasts are *not* trade calls. This module
lives in `models/`, writes nothing to `tracker/events.jsonl`, and keeps a separate
model-performance namespace. A human call may *cite* a forecast; the human owns the call.

## 1. Design: extrapolate the regression, don't re-estimate

The forecast **consumes a `DecompRun`** (the fitted regression from step 3) rather than
fitting its own — so decomposition and forecast are guaranteed consistent (same betas,
same orthogonalization, same window). One period's expected target return:

```
E[y(t+k)] = drift + Σ_i β_i · E[z_i(t+k)]
```

The only new modelling choice is **`E[z_i]` — the assumed driver path**. v1 offers three
honest, clearly-labelled assumptions; we never pretend to forecast the drivers unless a
model is supplied:

- **`hold_last`** (default): driver returns = 0 → forecast is pure drift extrapolation,
  `P(t+k) = P_last · exp(k · drift)`. The conservative "carry" baseline.
- **`momentum`**: driver returns = trailing-mean driver return over `est_window`.
- **`scenario`**: caller supplies explicit driver-return paths (e.g. "broad USD +2% over
  the month") → the regression's *conditional* answer. This is the analyst-facing value:
  "if the drivers do X, the fitted relationship implies the price goes to Y."

Where a `quant.nowcast` bridge exists for a driver, its conditional expectation may later
feed `scenario` automatically (v2 hook; not v1).

## 2. Interface

```python
# models/forecast.py
@dataclass(frozen=True)
class Forecast:
    path: pd.DataFrame          # index=future dates; cols [point, lo, hi] in LEVEL units
    horizon_periods: int
    frequency: str              # resample freq inherited from the decomposition
    conf: float                 # interval coverage, e.g. 0.80
    driver_assumption: str      # "hold_last" | "momentum" | "scenario"
    resid_std: float            # per-period residual std from the fit (interval scale)
    last_level: float
    last_date: pd.Timestamp
    as_of: pd.Timestamp | None  # point-in-time cutoff of the underlying regression
    basis: str                  # target id + regression provenance (for the source line)
    notes: list[str]            # caveats stamped on every output (see §4)

def forecast_from_regression(
    run: "quant.decomp.run.DecompRun",
    *,
    horizon_periods: int,
    driver_assumption: str = "hold_last",
    driver_paths: dict[str, pd.Series] | None = None,   # required iff assumption="scenario"
    conf: float = 0.80,
) -> Forecast
```

- **Point path:** cumulative expected log returns from §1, exponentiated onto `last_level`.
  For `return_kind="pct"` the compounding is `Π(1+E[y])`; a note records the approximation.
- **Interval (v1):** `point · exp(± z · resid_std · √k)` — the random-walk-of-errors band,
  widening with √horizon. `z` from `conf`. **Ignores parameter uncertainty** and assumes
  the driver path is known; both are stamped in `notes` (honest, not hidden). Parameter
  and scenario uncertainty are a v2 refinement.
- **Namespaced provenance:** `basis` and `as_of` come straight off the `DecompRun`, so the
  forecast is reproducible and its point-in-time discipline is inherited, not re-derived.

## 3. Evaluation (`models/evaluate.py`) — the skill gate

A forecast platform must be able to show it beats naive. Reuse the tested stats core, do
not re-implement:

- **Walk-forward** via `quant.stats.walk_forward_splits` (no look-ahead): at each split,
  refit the decomposition on train, forecast `horizon_periods`, compare to realized.
- **Skill vs benchmark** via `quant.stats.campbell_thompson_oos_r2` against a random-walk
  (`hold_last` = last level) benchmark, and `diebold_mariano` for significance.
- Report MAE/RMSE in level and return units, with sample size; suppress skill claims when
  `n` is small (mirror the tracker's small-sample honesty rule).

This is what the Workbench's step-5 backtest reads to decide whether the forecast-derived
signal is worth trading (and it dovetails with the regime filter there).

## 4. Caveats stamped on every output (`notes`)

- Which `driver_assumption` was used, verbatim — a `hold_last` forecast is drift-only and
  must never be presented as if the drivers were modelled.
- Interval assumes known driver path + fixed parameters (understates uncertainty).
- `return_kind="pct"` compounding is approximate.
- Missing drivers (`run.missing`) that were dropped from the fit.

## 5. Failure modes & tests (must exist before "done")

- `horizon_periods <= 0` → `ValueError`.
- `driver_assumption="scenario"` without `driver_paths` (or with wrong ids / short paths)
  → `ValueError` naming the offending driver.
- Unfitted / empty `DecompRun` → `ValueError`.
- **Reconstruction sanity:** a zero-drift, `hold_last` forecast returns a flat level path
  equal to `last_level` (± interval) — a hand-checkable fixture.
- **Interval monotonicity:** band half-width strictly increases with `k`.
- **Point-in-time honesty:** a forecast built with `as_of=T` uses only data ≤ T (the
  `DecompRun` already guarantees this; assert it survives the extrapolation).
- **Benchmark math:** OOS-R² of the `hold_last` forecast *against itself* is 0 (fixture).

## 6. Build order

1. `Forecast` + `forecast_from_regression` for `hold_last` and `scenario` + √k interval.
2. `momentum` assumption.
3. `models/evaluate.py` walk-forward skill vs RW; wire into the Workbench step-5 backtest.
4. (v2) parameter-uncertainty interval; nowcast-fed scenario paths.
