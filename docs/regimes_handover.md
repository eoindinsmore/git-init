# Regime identification + consumption hooks — handover (spec §7)

Transparent, auditable market-state classification that other modules consume.

## Why rule-based (v1)
Deliberate: explainability, no estimation instability, every historical classification
auditable. An HMM is a later robustness *exhibit*, not a replacement.

## Public interface (`quant.regimes`)
- **Categorizers** (`core.py`): `band` (level buckets, e.g. VIX low/mid/high),
  `ma_trend` (above/below a trailing MA, e.g. USD vs 200d), `level_delta` (level ×
  k-period change sign, e.g. PMI >50 & rising). All trailing / point-in-time.
- **`classify(state_categories)`** → dated regime-label series (`name=cat | …`); a date
  with any missing state is left NaN (no guessed regime).
- **`transition_matrix(regimes)`** → row-normalized transition probabilities.
- **`conditional_performance(regimes, asset_returns)`** → per-regime mean/vol/Sharpe/
  hit-rate **and sample size n** (regime known at t matched to the t→t+1 return — no
  look-ahead; overlapping-data caveats are the reader's to weigh, n is shown).
- **`RegimeSpec` / `classify_from_store`** — declare state series + rules in YAML
  (`specs/global_macro.yaml`); the runner classifies from the store and reports missing
  states.

## Consumption hooks (mandatory — a regime model must do something)
- **`combination_weights(regime, mse_by_regime_model)`** — regime-conditional forecast-
  combination weights (inverse-MSE; equal-weight fallback for unseen regimes).
- **`sizing_multiplier(regime, mapping, default=1.0)`** — position-sizing suggestion for
  the tracker (dial risk down in risk-off regimes). Mappings live on the spec.
- **`regime_banner(regimes, as_of=None)`** — `{as_of, regime, components}` payload for
  dashboards / PDF reports.

## Data dependencies / gaps
Reads the fact table. The canonical `global_macro` state series (VIX, global mfg PMI,
broad USD) are **not yet ingested** — the spec declares them so the intended model is
explicit; `classify_from_store` uses whatever states are available and reports the rest
(see `docs/quant_data_gaps.md`). Real-data smoke: a copper-price trend regime
(price vs 12m MA) shows the expected conditioning — returns Sharpe +0.81 above the MA vs
−0.28 below, with persistent states — proving the engine end-to-end.

## Known limitations
- v1 rule-based only (HMM comparison is a future exhibit).
- Conditional-performance stats don't yet adjust for overlapping returns beyond showing n;
  pair with the backtester's bootstrap p-values for inference.

## How to test
```
.venv/Scripts/python -m pytest tests/test_regimes.py -q
```
