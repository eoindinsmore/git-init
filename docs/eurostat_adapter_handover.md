# Handover — Eurostat adapter (Build Order Step 2)

## Purpose
Pull series from the Eurostat dissemination API (JSON-stat, no key) into the fact table.

## Public interface
```python
from adapters.eurostat import EurostatAdapter
EurostatAdapter().run("de_industrial_production")   # -> rows written
```
`source_code` = dataset id; `source_params` = dimension filters that must reduce
the cube to a single series.

## Data dependencies
[`registry/eurostat.yaml`](../registry/eurostat.yaml): `de_industrial_production`
(`sts_inpr_m`, geo=DE, nace_r2=B-D, s_adj=SCA, unit=I21).

## Point-in-time mapping
Eurostat gives **no per-observation vintage**. The dataset-level `updated`
timestamp (tz-aware) is stored as both `as_of` and `last_updated`; the store
normalizes it to tz-naive UTC. Revisions are only distinguishable at dataset-refresh
granularity — capture runs regularly to build vintage history.

## Failure modes (loud)
- Missing JSON-stat keys (`id`/`size`/`dimension`/`value`) → `AdapterError`.
- Any non-time dimension with >1 category → `AdapterError` (would silently merge
  multiple series; add a `source_params` filter).
- HTTP 429/5xx → retried; other non-200 → `AdapterError`.

## Limitations / next
- Value indexing assumes non-time dims are pinned to 1 category (enforced).
- Quarterly/annual periods handled (`_period_to_date`), but only monthly is exercised
  by the current series.

## Test
`pytest tests/test_eurostat_adapter.py` — offline against
`tests/fixtures/*/eurostat_sts_inpr_m_DE.json`.
