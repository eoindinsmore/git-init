# Price decomposition — handover (spec §4)

"Why did the price move" attribution: rolling regression of a target's returns on a
declared driver set, with the residual explicitly labelled *unexplained*. The
weekly desk product.

## Public interface (`quant.decomp`)
- **`DecompSpec` / `DriverSpec`** + `load_named(name)` / `load_spec(path)` — a target
  and its drivers, each with an `order` (orthogonalization rank) and `label`. Specs
  live in `quant/decomp/specs/*.yaml` (shipped: `copper`, `aluminium`).
- **`run_decomposition(spec, *, as_of=None, window=None, ...)` → `DecompRun`** — fetches
  target + drivers from the store (point-in-time via `pit.get_series_asof` when `as_of`
  is given), decomposes, and **flags missing drivers** in `DecompRun.missing`.
- **`decompose(target_levels, driver_levels, *, order, frequency, return_kind,
  est_window, window)` → `DecompResult`** — the pure engine (no store dependency).
- **`orthogonalize(drivers, order)`** — sequential Gram–Schmidt residualization.
- **`contributions_frame(run)`** — tidy `[component, label, contribution]` for a stacked
  bar. **`render_html(run)`** — one-page HTML (PDF later).

## Method
- Returns: log by default, so contributions sum **exactly** to the total log price
  change over any window (`actual == sum(contributions)`, the key invariant).
- Correlated regressors: **sequential economic orthogonalization** in the spec's
  declared order (USD → rates → activity → energy → positioning). Driver *k* keeps only
  the part not explained by drivers 1..k-1. The order is rendered on the page — the
  choice and its consequence are stated, never hidden. (Shapley/LMG robustness variant
  is a documented future option, not built.)
- Fit: HAC-robust OLS (`stats.ols_hac`) over the trailing `est_window`. The intercept
  becomes a `DRIFT` contribution; the leftover is `RESIDUAL`.
- Stability: `stats.rolling_ols` betas + per-driver sign-flip counts.

## Data dependencies / gaps
Reads the fact table. The shipped specs declare the *intended* driver sets; most macro
drivers (broad USD, US 10y real yield, China activity composite, energy composite) are
**not yet ingested** — `run_decomposition` drops them and lists them in `.missing`. See
`docs/quant_data_gaps.md`. Today the copper spec runs on `us_industrial_production` +
`copper_cot_mm_long` only (R²≈0.22, n=60) — machinery proven; exhibit fills out as
adapters land.

## Known limitations
- Orthogonalization order is a modelling choice; a different order yields different
  per-driver splits (total is invariant). Stated on the chart by design.
- No Shapley/LMG allocation yet (documented future robustness exhibit).
- Composites (China activity, energy) will come from `quant/composites` (Phase 4).

## How to test
```
.venv/Scripts/python -m pytest tests/test_decomp.py -q
.venv/Scripts/python -c "from quant.decomp import load_named, run_decomposition, render_html; \
  print(render_html(run_decomposition(load_named('copper')))[:200])"
```
