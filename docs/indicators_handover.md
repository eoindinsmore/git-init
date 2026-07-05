# Leading-indicator lab — handover (spec §1)

The credibility core: find AND honestly validate leading indicators through five
sequential gates. Answers "how do you avoid data-mining?"

## The five gates (a candidate must pass ALL to be promoted)
1. **Scan** (`lead_lag_scan`) — HAC-robust OLS of `target(t) ~ candidate(t−k)` for
   k=0..K, on the **training window only**.
2. **FDR** — Benjamini–Hochberg across the **whole candidate×lag grid at once**
   (`stats.benjamini_hochberg`). Raw t-stats never promote; q-values do.
3. **OOS** (`oos_confirm`) — walk-forward predictive regression on the holdout;
   require positive Campbell–Thompson OOS R² vs the prevailing-mean benchmark.
4. **Economic** (`economic_significance`) — a z-scored signal→position rule must
   beat the benchmark net of costs. **Lightweight stub**; Phase-5 backtester
   (vol-targeting, proper costs, deflated Sharpe) replaces it.
5. **Stability** (`stability`) — rolling-beta sign-flip check.

## Public interface (`quant.indicators`)
- **`run_lab(target_id, target, candidates, *, config, registry, write_scorecards,
  scorecard_dir, created_as_of)` → `list[CandidateEval]`** — the orchestrator on
  in-memory aligned series.
- **`run_lab_from_store(target_id, candidate_ids, *, freq, difference, as_of, ...)`
  → `(evals, missing)`** — fetches from the point-in-time store, resamples, optionally
  first-differences to stationarity.
- **`LabConfig`** — `max_lag`, `train_frac`, `fdr_q`, `min_train`, `stability_window`,
  `min_oos_r2`, `min_sharpe`, `max_flip_share`, `cost_per_turnover`.
- **`CandidateEval`** — `promoted`, `best_lag`, `gates` (per-gate `GateOutcome`),
  `failed_gate`, `signal` (a `Signal` if promoted), `scorecard` (a `ScorecardRef`).

## Outputs
- Promoted → a `Signal` (`<cand>__leads__<target>`, provenance, direction from beta
  sign, worst-case publication lag from the registry) + an **approved scorecard**.
- Rejected → a scorecard in `docs/scorecards/rejected/` — the graveyard is part of
  the credibility story (answers "do you report what didn't work?").

## Data dependencies / gaps
Reads the fact table. Real-data smoke (target=copper price change, monthly diffs):
`copper_cot_mm_long` promotes at lag 1; US IP and the other COT legs fail the FDR
gate. As more candidate series land, the pool grows; the FDR gate keeps the family-
wide false-discovery rate controlled.

## Known limitations
- Economic gate is a stub until Phase 5 wires the real backtester.
- Point-in-time timing uses lead-lag k in native periods; the candidate's own
  publication lag is recorded on the promoted Signal but not yet folded into the
  lag search itself (documented follow-up).
- FDR controls the false-discovery *rate*, not to exactly zero — with a real signal
  present a stray noise candidate can occasionally survive; the pure-noise case
  promotes none.

## How to test
```
.venv/Scripts/python -m pytest tests/test_indicators.py -q
```
