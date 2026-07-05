# Quant toolkit — foundation handover (spec §0)

The cross-cutting layer every other quant module builds on. Nothing here is an
analytic; it is the contracts (Signal), the honest data access (lag-aware PIT),
the shared math (stats core), and the evaluation artifact (scorecard).

## Public interface

### `quant.signal`
- **`Signal`** (pydantic, `arbitrary_types_allowed`) — the one object every module
  emits. Fields: `signal_id`, `values` (date-indexed `pd.Series`, sorted, unique),
  `direction_convention`, `target`, `provenance` (registry ids, non-empty),
  `construction`, `publication_lag_days`, `created_as_of`, `scorecard`.
  - `.to_frame()` → `[date, value]` for the chart/transform code.
  - `.resolve_as_of(as_of)` → sub-series usable on a decision date (applies the
    signal's own lag: a value dated `D` is usable from `D + lag`).
- **`ScorecardRef`** — lightweight `{scorecard_id, path}` pointer.
- **`worst_case_lag(provenance, registry)`** — max `publication_lag_days` across a
  signal's inputs. Modules call this instead of hand-setting the lag.

### `quant.pit`
- **`get_series_asof(series_id, as_of, *, publication_lag_days=None, ...)`** →
  `[date, value]` **publicly known** on `as_of`. Reconstructs availability from the
  release lag (`date + lag <= as_of`), not the store's vintage cutoff — because our
  histories are backfilled under a single `as_of`, so the vintage filter alone
  returns nothing for past dates. **This is the function backtests / lead-lag /
  nowcasts must call.** Lag defaults to the registry value.
- **`get_panel_asof(series_ids, as_of, ...)`** → wide date-indexed panel, one column
  per series, ragged edges left as `NaN` (the situation composites/nowcasts handle).
- **Caveat (documented, not hidden):** uses the *latest* vintage of each date
  (revisions folded in). For revision-accurate PIT use `store.get_series(as_of=...)`
  directly — the two are complementary. Revisit if/when true intraday vintages are
  captured for a series.

### `quant.stats` — the shared, tested math (reuse; don't re-implement)
- `ols_hac(y, X, maxlags=None)` → `OLSResult` (params, HAC/Newey–West SEs, t/p, R²).
  **HAC is the default** because overlapping returns are the norm.
- `rolling_ols(y, X, window)` → time series of betas (stability plots).
- `benjamini_hochberg(pvalues, q)` → `{pvalue, qvalue, reject}` (FDR gate).
- `campbell_thompson_oos_r2(actual, forecast, benchmark)` / `diebold_mariano(...)`.
- `block_bootstrap_pvalue(returns, ...)` / `deflated_sharpe(sharpe, n_obs, n_trials)`.
- `mahalanobis(vec, mean, cov)` (scanner multivariate flag).
- `walk_forward_splits(index, min_train, test_size, expanding)` → PIT splits.

### `quant.scorecard`
- **`Scorecard`** — `kind`, `target`, `in_sample`/`out_of_sample` free-form stat
  bags, `fdr_status`, `n_variants_tried`, `stability_note`, `provenance`, `notes`.
- **`write_scorecard(sc, approved=True, base_dir=...)`** → writes JSON + sibling HTML
  to `docs/scorecards/` (approved) or `docs/scorecards/rejected/` (the graveyard),
  returns a `ScorecardRef`. `base_dir` overridable so tests never touch real docs.
- **`render_html(sc)`** — minimal self-contained HTML. PDF is deferred (WeasyPrint,
  project step 9) — a later pass over this renderer.

## Registry extension
`SeriesSpec` gained `publication_lag_days: int = 0` and `release_schedule: str|None`.
All 16 series populated (premiums 0, CFTC 3, LME 4, IMF price 14, US IP 16, JP 30,
DE 40, StatCan placeholder 45). Additive with defaults — the registry workbook and
adapters keep working unchanged.

## Data dependencies
None new. Reads the existing fact table via `quant.store`. Lag values are release
*calendars*, not licensed data.

## Known limitations / follow-ups
- Revision-accurate PIT vs lag-reconstruction — see the pit caveat above.
- Registry workbook doesn't yet surface `publication_lag_days` as an editable column
  (additive default means no breakage; a small follow-up).
- PDF rendering deferred to project step 9.

## How to test
```
.venv/Scripts/python -m pip install -e .[quant]   # scipy, statsmodels, scikit-learn
.venv/Scripts/python -m pytest tests/test_signal.py tests/test_pit.py \
    tests/test_scorecard.py tests/test_stats.py -q
.venv/Scripts/python -m ruff check .
```

## What the next module (decomposition) consumes
`get_series_asof` for point-in-time driver/target series, `stats.rolling_ols` +
`stats.ols_hac` for the attribution regression, `Signal` for any composite it
builds, and `write_scorecard` for its evaluation page.
