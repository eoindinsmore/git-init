# Decomposition-as-time-series Spec — `quant/decomp` extension

Purpose: turn the price decomposition from a **single-window contribution bar** into a
**stacked-area time series** — the intercept (drift), each driver's contribution, and the
unexplained residual, accumulated over time so the stacked bands reconstruct the price
path. This is step 3 of the Analysis Workbench ("residual plus intercept get combined").

The engine already computes everything needed per period; today `decompose()` only sums
it into one window total. This adds the time-resolved view **without touching** the
existing single-window output. Zero-analytics rule holds: the app stacks and renders;
this function produces the numbers.

## 1. Where it lives

`quant/decomp/core.py`: new `contribution_timeseries(...)` + a `ContributionSeries`
dataclass. `quant/decomp/run.py`: extend `run_decomposition` to also attach the series
(or a sibling `run_contribution_timeseries`) so the app fetches point-in-time levels the
same way it already does. No new estimation path — reuse the fit from `decompose()`.

## 2. The maths (additive by construction)

With log returns, the target's cumulative return over the window equals the sum of its
per-period returns, and each period's return decomposes exactly:

```
y(t)      = drift + Σ_i β_i · z_i(t) + ε(t)
          = contribution_drift(t) + Σ_i contribution_i(t) + contribution_resid(t)
```

where `z_i(t)` is the **orthogonalized** driver return (same `orthogonalize()` used today)
and `β_i`, `drift` are the fitted coefficients from the trailing `est_window` OLS-HAC fit.
Per period:
- `contribution_drift(t) = const` (the intercept, one per period)
- `contribution_i(t)     = β_i · z_i(t)`
- `contribution_resid(t)  = y(t) − drift − Σ_i β_i·z_i(t)`  (closes the identity exactly)

Cumulative sums reconstruct the log-price path:

```
ln P(t) = ln P(t0) + Σ_{s≤t} [ drift + Σ_i β_i·z_i(s) + ε(s) ]
```

So a stacked area of the **cumulative** component columns, offset by `ln P(t0)`, sits
exactly on `ln P(t)` — the residual band visibly closes the gap between the
driver-explained path and the actual. This is the exhibit.

## 3. Interface

```python
@dataclass(frozen=True)
class ContributionSeries:
    increments: pd.DataFrame    # per-period contributions; cols: [DRIFT, *driver_ids, RESIDUAL]
    cumulative: pd.DataFrame    # cumsum of `increments` from window start (first row = 0)
    level_start: float          # ln P at the first window date (log) — the stacking offset
    reconstructed: pd.Series    # level_start + cumulative.sum(axis=1); == actual within tol
    actual: pd.Series           # target's resampled log-level over the window (overlay)
    betas: pd.Series            # the fitted coefficients used (incl. 'const')
    order: list[str]            # driver ids in orthogonalization order
    return_kind: str            # "log" | "pct"
    frequency: str
    additive_exact: bool        # True for log returns; False (approx) for pct — flagged

def contribution_timeseries(
    target_levels: pd.Series,
    driver_levels: dict[str, pd.Series],
    *,
    order: list[str],
    frequency: str = "W",
    return_kind: str = "log",
    est_window: int = 104,
    window: tuple | None = None,
    betas: str = "static",      # "static" (trailing-window fit, default) | "rolling" (v2)
) -> ContributionSeries
```

- **Inputs** are the same date-indexed level series `decompose()` already takes (fetch via
  `quant.pit.get_series_asof` in the run wrapper). `order`, `frequency`, `return_kind`,
  `est_window`, `window` carry identical meaning to `decompose()` so the two agree.
- **`betas="static"`** (v1): one coefficient vector from the trailing-`est_window` fit,
  applied to every period in the window — matches `decompose()` exactly, so the summed
  increments equal the existing single-window contributions (a tested invariant, §5).
- **`betas="rolling"`** deferred to v2: uses `rolling_ols` betas per period (time-varying
  attribution — more honest, less tidy). Spec'd here so the field exists; not built in v1.

## 4. Consistency with the existing bar

The new series and the old bar are the **same fit**: `Σ_t increments[col]` over the window
must equal `decompose(...).contributions[col]` for every column, and `reconstructed` must
match `decompose(...).actual`. The Workbench shows the bar (window total) and the area
(time path) side by side, guaranteed to reconcile.

## 5. Failure modes & tests (must exist before "done")

- **Additivity invariant (log):** for `return_kind="log"`, `reconstructed` equals `actual`
  at every window date within `1e-9`; `additive_exact is True`.
- **Reconciles with the bar:** column-wise `increments.sum()` == `decompose().contributions`
  and `reconstructed[-1] − level_start` == `decompose().actual` within tolerance.
- **pct is approximate, and says so:** `return_kind="pct"` sets `additive_exact=False` and a
  reconstruction note; residual absorbs the compounding gap (never silently mis-stacks).
- **Insufficient overlap:** reuse `decompose()`'s guard (`< len(order)+2` obs → `ValueError`).
- **Mid-series NaN / ragged edge:** periods with any NaN driver are dropped from the panel
  (as today); the cumulative path steps over the gap without inventing values.
- **Empty window:** `window` outside the sample → `ValueError` with a clear message.

## 6. What the app does with it (not this spec, but the contract it serves)

`app/toolkit_ui.py` gets a `stacked_contribution_area(series)` helper: an Altair stacked
area of `cumulative` offset by `level_start`, drift/drivers/residual as distinct bands
(residual in a muted "unexplained" tone), with the `actual` log-level overlaid as a line
that the bands should trace. Diverging colours reuse the existing `theme` palette.
