# Handover — e-Stat adapter (Build Order Step 2)

## Purpose
Pull Japan official statistics via the e-Stat `getStatsData` API into the fact
table. e-Stat returns a multi-dimensional cube; this adapter extracts one series.

## Public interface
```python
from adapters.estat import EstatAdapter
EstatAdapter().run("jp_iip_diecast")   # appId from ESTAT_APP_ID; -> rows written
```
`source_code` = `statsDataId`; `selector` pins non-time dimensions to one series
(e.g. `{"cat02": "2021010010"}`). `source_params.limit` caps rows (default 100000).

## Data dependencies
[`registry/estat.yaml`](../registry/estat.yaml): `jp_iip_diecast`
(statsDataId `0004033012`, cat02 `2021010010` = die-casting, steel/non-ferrous).

Find statsDataIds and category codes from the `getStatsList` catalogue fixture
(`tests/fixtures/*/estat_statslist_iip.json`).

## Point-in-time mapping
No per-observation vintage. `TABLE_INF.UPDATED_DATE` → `as_of`/`last_updated`.
Time codes decoded via `CLASS_INF` (`@name` like `202401` → 2024-01-01), not by
hard-coding e-Stat's numeric time encoding.

## Failure modes (loud)
- `RESULT.STATUS != 0` (e.g. bad appId) → `AdapterError` with e-Stat's message.
- Selector references a non-existent dimension → `AdapterError`.
- Selection leaves duplicate dates (selector doesn't isolate one series) →
  `AdapterError` (pin more dimensions).
- Missing `GET_STATS_DATA`/`RESULT` keys → `AdapterError` (layout change).

## Limitations / next
- **Each statsDataId is often a single-year table** (e.g. `0004033012` is 2024 only,
  12 obs). A continuous series requires unioning multiple yearly tables under one
  `series_id`, or a different multi-year table. Deferred until a continuous JP series
  is needed — the store already dedups across pulls.
- Only `cat02`+`time` cubes exercised; multi-dim selectors are supported but untested
  beyond one dimension.

## Test
`pytest tests/test_estat_adapter.py` — offline against
`tests/fixtures/*/estat_statsdata_0004033012.json`.
