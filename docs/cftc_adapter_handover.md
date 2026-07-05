# Handover — CFTC COT adapter (Build Order Step 3)

## Purpose
Pull CFTC Commitments of Traders (disaggregated futures-only) positioning into the
fact table via the Socrata public API (no key).

## Public interface
```python
from adapters.cftc import CftcAdapter
CftcAdapter().run("copper_cot_mm_long")   # -> rows written
```
One registry series per COT field: `source_code` = the CFTC column name;
`source_params.market` = market filter (e.g. `COPPER%`). Optional
`source_params`: `dataset` (default `72hh-3qpy`), `limit` (default 520), `where`
(raw SoQL override).

## Data dependencies
[`registry/cftc.yaml`](../registry/cftc.yaml) — COMEX copper: open interest,
managed-money long/short, producer/merchant long/short (category `positioning`).

## Point-in-time mapping (important)
COT is a **Tuesday** snapshot **published the following Friday**. The adapter sets
`as_of = report_date + 3 days` (the publication date) so backtests cannot see
positioning 3 days early. `store.get_series(..., as_of=report_date)` correctly
excludes a report until its Friday publication.

## Failure modes (loud)
- No `market`/`where` in `source_params` → `AdapterError`.
- Non-list payload (e.g. Socrata error object) → `AdapterError`.
- `source_code` field absent from every row (bad field/market) → `AdapterError`.
- HTTP 429/5xx → retried; other non-200 → `AdapterError`.

## Limitations / next
- `as_of` uses a fixed +3-day lag, not an actual per-report publication timestamp
  (the dataset doesn't expose one). Correct for normal weeks; holiday-shifted
  releases could be off by a day.
- Only disaggregated futures-only report wired; TFF / legacy / combined reports
  would be new datasets + series.
- Net positioning, %-of-OI, z-scores are derived transforms → build in `quant/`,
  not here (registry `transformations` will carry defaults).

## Test
`pytest tests/test_cftc_adapter.py` — offline against
`tests/fixtures/*/cftc_disagg_copper.json`, including a lookahead-safety assertion.
