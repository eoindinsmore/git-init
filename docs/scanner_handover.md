# Dislocation scanner + tracker hook — handover (spec §6)

Daily idea-generation screen across the registry, and the one-click screen→thesis
promotion into the append-only tracker — the analyst-to-PM loop's first rung.

## Public interface (`quant.scanner`)
- **`UniverseSpec` / `DerivedItem`** + `load_named("base")` — the scan universe: raw
  registry series + declared derived items (`ratio` = a/b, `spread` = a−b, curve
  slopes), the `mahalanobis_set`, `windows`, and `z_threshold`. Universes live in
  `quant/scanner/universe/*.yaml`.
- **`run_scan(spec, *, as_of=None, ...)` → `ScanResult`** — builds levels from the
  point-in-time store, constructs derived items, runs the screen.
- **`scan(levels, *, windows, z_threshold, mahalanobis_set)` → `ScanResult`** — pure
  engine. `ScanResult.table` is one row per item (`value`, `z_level_*`, `z_ret_*`,
  `pct_rank_*`, `abs_z`, `flag`, `new_flag`) ranked by `abs_z`; plus `mahalanobis`
  and `mahalanobis_pvalue` (chi-square tail, df = set size) and `coverage`.
- **`promote_flag(result, item, *, created_as_of=None, direction=UNDECIDED, path=...)`
  → `Hypothesis`** — the tracker hook: drafts an immutable hypothesis (instrument
  pre-filled, scan back-reference, thesis stub), direction left `undecided`.

## Minimal tracker (`tracker/`) — a seed of project step 6
- **`Hypothesis`** (`tracker/schema.py`) — frozen/immutable record: id, `created_as_of`,
  `instrument`, `direction` (long/short/**undecided**), `thesis`, `source`, `scan_ref`,
  `status` (draft/open/closed/discarded), `supersedes`.
- **`tracker/store.py`** — append-only JSONL: `append`, `read_all` (full audit trail),
  `current_view` (folds `supersedes` chains to the latest per hypothesis, file never
  rewritten). Charter constraint #6 (immutable; corrections are new records).

## Method
- Univariate: rolling z-scores of **levels and of returns** over each window, plus a
  percentile rank over the longest window. Headline `abs_z` = max magnitude. `new_flag`
  = crossed `z_threshold` this step (was below at the prior step).
- Multivariate: Mahalanobis distance of the latest joint return vector vs its history
  (`stats.mahalanobis`) — flags an unusual *combination* even when no single leg is
  extreme.

## Data dependencies / gaps
Reads the fact table. Shipped `base` universe covers the two aluminium premiums, the
IMF copper proxy, and CFTC COT (raw + net spreads + US/EU premium ratio). **CME premium
forward-curve slopes** are not yet available (front-month capture only — see
`docs/quant_data_gaps.md`); they slot into `derived`/`series` once the full curve lands.

## Known limitations
- `new_flag` compares only the last two observations of a series; a persistent-but-not-
  freshly-crossed dislocation shows `flag=True, new_flag=False`.
- Mahalanobis needs ≥2 covering series and a non-singular covariance (pinv guards
  near-singularity); returns `None` when the set is too thin.

## How to test
```
.venv/Scripts/python -m pytest tests/test_scanner.py tests/test_tracker.py -q
.venv/Scripts/python -c "from quant.scanner import load_named, run_scan; \
  print(run_scan(load_named('base')).table.head())"
```
