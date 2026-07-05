# Handover — FRED adapter (Build Order Step 1)

## Purpose

Pull series from the St. Louis Fed **FRED** API into the point-in-time Parquet
fact table. First adapter on `BaseAdapter`; also the reference implementation for
the registry → adapter → store pipeline.

## Public interface

```python
from adapters.fred import FredAdapter

a = FredAdapter()                       # reads FRED_API_KEY from env/.env
n = a.run("us_industrial_production")   # fetch → parse → validate → store; returns rows written
```

- `FredAdapter(registry=None, api_key=None, observation_start="1990-01-01", manual_dir=None)`
  - `api_key` defaults to `os.getenv("FRED_API_KEY")` (rule #5 — never hard-coded).
  - `registry` defaults to the full loaded registry; inject a dict in tests.
- `run(series_id, path=FACTS_PATH) -> int` — orchestrated by `BaseAdapter`.
- Reads back via `quant.store.get_series(series_id, as_of=None)`.

## Data dependencies (registry series)

Declared in [`registry/fred.yaml`](../registry/fred.yaml):

| series_id | FRED code | unit | freq | category |
|---|---|---|---|---|
| `us_industrial_production` | `INDPRO` | Index 2017=100 | M | activity |
| `copper_price_global` | `PCOPPUSDM` | USD/metric ton | M | price_proxy |

`copper_price_global` is a **price proxy** (IMF reference average, not an exchange
price) and carries `caveats` — enforced by the schema.

## How it maps to the fact table

FRED gives each observation a `realtime_start` → stored as **`as_of`** (the vintage).
`last_updated` comes from the series-metadata endpoint. Missing values (`"."`) are
dropped. Identity columns (`series_id`, `source`, `frequency`, `unit`) are enriched
from the registry spec, not trusted from the payload.

## Failure modes (all loud — no silent staleness)

- Missing `FRED_API_KEY` → `AdapterError`.
- HTTP 429 / 5xx → `TransientFetchError`, retried with exponential backoff
  (4 attempts); still failing → falls back to `data/manual/fred/<code>.*` if present,
  else `AdapterError`.
- HTTP 4xx (bad key/params) → `AdapterError` immediately (not retried).
- Payload without `observations` key, or zero usable rows after parse → `AdapterError`
  (treated as a layout change).
- A value present but no `date`/`as_of` → `AdapterError` (point-in-time violation).
- Re-storing an existing vintage with a different value → `ValueError` from the store
  (`vintage conflict`); revisions must land under a new `as_of`.

## How to test

```
pip install -e ".[dev]"
pytest -q                     # offline: tests run against tests/fixtures/<date>/
ruff check .
```

Tests stub `fetch_raw` with the harvested fixture — **no network**. To refresh the
captured payloads: `python harvest_fixtures.py` (needs keys in `.env`).

## Known limitations / next steps

- Single-vintage pull: uses FRED's default realtime window, so we capture the
  *current* vintage each run rather than the full ALFRED revision history. Backfilling
  true vintages would add `realtime_start`/`realtime_end` sweep params — deferred until
  a backtest needs deep revision history.
- No incremental cursor yet; each run pulls from `observation_start`. The store dedups,
  so this is correct but not minimal. Fine at FRED's data sizes.
- `PCOPPUSDM` unit string assumes USD/metric ton — verify against FRED metadata if the
  proxy is used quantitatively.
