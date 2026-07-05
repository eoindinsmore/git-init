# Nowcasting — handover (spec §2)

Current-period estimates of a slow-release low-frequency target from time-aggregated
higher-frequency indicators, updated as inputs release. Answers "what did you know, and
when?"

## Public interface (`quant.nowcast`)
- **`BridgeModel(indicators, agg).fit(target, indicator_data)`** — regresses the
  low-frequency target on its indicators aggregated over each target period
  (`aggregate_over`, mean/sum/last). `predict_period(indicator_data, start, end)` →
  `(value, se, n_inputs)`.
- **Ragged edge:** a partial current period uses only the indicator obs available so far;
  with `agg="mean"` the period-to-date mean is a valid conditional expectation of the
  full-period mean (the fill for the unreleased remainder).
- **`fit_from_store(target_id, indicator_ids, *, agg, as_of, ...)` → `NowcastSetup`** —
  fetches from the point-in-time store; missing indicators reported.
- **Vintage record** (`vintage.py`): `NowcastVintage(target_id, target_period, as_of,
  value, se, n_inputs)`, append-only JSONL (`record` / `read_all`); `record_nowcast`
  computes and appends. The key artifact — every revision preserved.
- **Deliverables** (`evaluate.py`): `nowcast_evolution` (estimate ± band vs days-into-
  period for one period) and `accuracy_vs_information` (MAE vs days-into-period across
  periods). `benchmark_comparison` evaluates vs naive benchmarks (**mandatory**).

## Benchmarks (a nowcast must beat these)
`naive_benchmarks`: last value (random walk) and seasonal naive. Verified: with the full
period observed the bridge beats last-value RW (test_nowcast.py::test_beats_naive_benchmark);
accuracy improves as more of the period is observed.

## Data dependencies / gaps
Reads the fact table. **This is the module most constrained by our thin data** — it needs
a genuinely slow-release target paired with faster indicators. Good pairs (global IP,
China aluminium demand proxy, regional apparent demand vs weekly/monthly activity inputs)
await their adapters — see `docs/quant_data_gaps.md`. The machinery is proven on synthetic
data (quarterly target ← monthly indicator) and a monthly-target ← weekly-indicator smoke.

## Known limitations
- v1 is bridge equations only — no Kalman/DFM (a documented v3 possibility).
- `se` is the in-sample residual std (a flat band), not a full predictive interval.
- `agg="sum"` on a partial period under-counts; `mean` is the honest ragged-edge default.

## How to test
```
.venv/Scripts/python -m pytest tests/test_nowcast.py -q
```
