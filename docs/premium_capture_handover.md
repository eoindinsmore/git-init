# Handover — Premium capture job (Build Order Step 3, priority theme)

## Purpose
Daily, vintage-stamped capture of aluminium physical premiums into the fact table.
The charter's headline source (CME daily settlements across **all listed contract
months** → full forward curve) is behind Akamai bot protection and **must not be
scraped** (rule #7). This job captures the ToS-clean **front-month continuous**
premium from yfinance instead, run daily so we accumulate history yfinance's rolling
window cannot backfill.

## Public interface
```python
from adapters import premium
premium.run_all()                       # capture all registry source=='premium' series
premium.capture_series(spec, cap_date)  # one series
python -m adapters.premium              # CLI entry point for the daily job
```

## Data dependencies
[`registry/premiums.yaml`](../registry/premiums.yaml), both `category: price_proxy`
(caveats enforced):

| series_id | ticker | unit |
|---|---|---|
| `aluminium_premium_mw_us` | `AUP=F` | USD/lb |
| `aluminium_premium_eu_dp` | `EDP=F` | USD/metric ton |

## Vintage discipline (the core logic — `plan_rows`)
- **Newly seen** date → stored with `as_of = observation date` (honest floor; seeds
  history on first run).
- **Changed** value for an existing date → revision, kept as a NEW row with
  `as_of = capture_date`.
- **Unchanged** date → skipped (idempotent; safe to run repeatedly).

Append-only; the store never overwrites. Point-in-time retrieval via
`store.get_series(series_id, as_of=...)` returns the value known on a given day.

## Failure modes (loud)
- yfinance missing/empty → `PremiumCaptureError`.
- No `source: premium` series in registry → `PremiumCaptureError`.

## Known limitations / next
- **Front-month only** — NOT the premium forward curve. The term structure (charter
  option c) needs a legitimate CME source; a research task is tracking free/official
  channels (CME DataMine, cloud marketplaces). See `docs/cme_premium_data_options.md`
  (pending).
- Thin contracts (volume 0–7): expect gaps/stale quotes. `frequency: D` but real
  cadence is irregular.
- yfinance is an unofficial dependency; if it breaks, the job fails loudly and no
  stale data is written.

## Scheduling
Time-sensitive — run **daily** (cannot be backfilled). Entry point:
`python -m adapters.premium` (loads `.env`, captures all premium series). Wire to a
scheduled task / cron; a run writing 0 rows on a non-trading day is expected.

## Test
`pytest tests/test_premium_capture.py` — vintage logic offline + real fixture parse
against `tests/fixtures/*/yf_AUP_midwest_premium.csv`.
