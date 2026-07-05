# Composite indicators — handover (spec §5)

Aggregate many series into a single indicator that is itself a `Signal` (so it can
feed the indicator lab, nowcasts, and decomposition drivers).

## Methods (`quant.composites.core`)
- **`diffusion_index(panel)`** — % of components improving (positive change) each date;
  missing components excluded from that date's denominator (ragged-edge safe).
- **`zscore_composite(panel, *, window=None, weights=None)`** — coverage-weighted average
  of per-component z-scores; averages over available components only. `window` gives the
  rolling (point-in-time-safe) z-score; `None` is full-sample (exploratory only).
- **`pit_pca_first_component(panel, *, reference, min_window, expanding=True)`** — first
  principal component with **point-in-time loadings**: at each date t the PCA is fitted on
  history up to t, standardized by that window's stats, **sign-fixed** to load positively
  on `reference`, and the latest observation is projected with **ragged-edge reweighting**
  onto whatever components are present. Full-sample PCA is forbidden (look-ahead).

## Build a composite Signal (`quant.composites.build`)
- **`CompositeSpec`** (`spec.py`) + `load_named(name)` — `composite_id`, `label`,
  `components`, `method`, `reference`, `window`/`min_window`, `target`,
  `direction_convention`. Shipped: `positioning_copper` (a PCA of the COMEX COT long legs
  + open interest, sign-fixed to managed-money long).
- **`build_composite(spec, *, as_of=None, registry=None, ...)` → `CompositeBuild`** —
  fetches the panel from the point-in-time store, computes the composite, and wraps it as a
  `Signal` with `provenance` = components used and `publication_lag_days` = worst-case lag
  across them. Missing components are dropped and reported in `.missing`.

## Verified invariant
The PIT PCA composite has **no look-ahead**: a date's score is identical whether or not
later data exists in the panel (test_composites.py::test_pit_pca_has_no_lookahead).

## Data dependencies / gaps
Reads the fact table. The shipped `positioning_copper` composite runs today on real CFTC
COT series (481 weekly points). Activity/demand composites (China activity, energy inputs)
that the decomposition specs reference await their component adapters — see
`docs/quant_data_gaps.md`.

## Known limitations
- PIT PCA refits per date (O(n) fits) — fine at our data sizes; not optimized for very
  long daily panels.
- `zscore_composite` full-sample mode (`window=None`) is exploratory only; use a `window`
  for anything feeding a backtest.

## How to test
```
.venv/Scripts/python -m pytest tests/test_composites.py -q
.venv/Scripts/python -c "from quant.composites import load_named, build_composite; \
  print(build_composite(load_named('positioning_copper')).signal.values.tail())"
```
