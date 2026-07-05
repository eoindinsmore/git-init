# Handover — StatCan adapter (Build Order Step 2)

## Purpose
Pull Statistics Canada series via the WDS REST API (no key) into the fact table.

## Public interface
```python
from adapters.statcan import StatCanAdapter
StatCanAdapter().run("ca_placeholder_vector")   # -> rows written
```
`source_code` = numeric WDS vector id; `source_params.latestN` = number of recent
periods (default 600).

## Data dependencies
[`registry/statcan.yaml`](../registry/statcan.yaml): currently only
`ca_placeholder_vector` (65201210) — the harvester's placeholder. **Replace with
real metals-relevant vectors** (mineral production/trade); vector ids are shown on
each StatCan table page.

## Point-in-time mapping
WDS returns a **genuine per-observation `releaseTime`** → stored as `as_of`. This
is the best point-in-time source in Step 2: real revision vintages, not just a
dataset-refresh timestamp.

## Failure modes (loud)
- Non-list / empty payload → `AdapterError`.
- `status != "SUCCESS"` (e.g. `MATCH_NOT_FOUND`) → `AdapterError`.
- Missing `vectorDataPoint` → `AdapterError` (layout change).
- HTTP 429/5xx → retried; other non-200 → `AdapterError`.

## Limitations / next
- **`scalarFactorCode` is NOT applied** — the raw `value` is stored as returned
  (matches the common `stats_can` convention). When a real vector is added, verify
  the registry `unit` reflects the source's stated scale, or apply the factor here.
- `symbolCode`/`statusCode` flags (suppressed/NA) are not yet surfaced; suppressed
  points with null value are dropped by the base validator.

## Test
`pytest tests/test_statcan_adapter.py` — offline against
`tests/fixtures/*/statcan_v65201210.json`.
