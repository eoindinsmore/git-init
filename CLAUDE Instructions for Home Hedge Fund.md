# CLAUDE.md — home-fund

Personal commodities research platform ("home hedge fund"). Base metals, copper-weighted,
aluminium value-chain depth. Free/public data only. This repo doubles as portfolio
evidence for a buy-side move — code quality and provenance discipline matter.

## Hard constraints — never violate

1. **No licensed price data.** No LME, ICE, Bloomberg, Reuters, Platts, Fastmarkets, CRU,
   WBMS feeds. Free sources and proxies only (see Data sources).
2. **No employer material.** Never reference or adapt content from the owner's employer.
3. **No GPL code.** Never copy or closely adapt code from `pysystemtrade` (GPL-3.0) —
   reimplement concepts from scratch. Cuemacro libs (`findatapy`, `finmarketpy`,
   `chartpy`) are Apache 2.0: use/adapt freely, preserve attribution. Check and record
   any new third-party licence in `docs/third_party.md` before borrowing code.
4. **Point-in-time discipline.** Every observation carries `as_of`. Revisions are new
   rows, never overwrites. Backtests must not use data unavailable on decision date.
5. **Secrets in `.env` only.** Never hard-code keys, never print them, never commit them.
6. **Append-only trade tracker.** Call records are immutable; corrections are new
   records referencing the original.
7. **No ToS-violating scraping.** No adapters on Investing.com or similar aggregators.
   Government/statistical/exchange-published sources only.

## Architecture contracts (do not redesign without asking)

- **Fact table**: long-format Parquet, local `data/` (gitignored).
  Schema: `series_id | date | value | as_of | source | frequency | unit | last_updated`.
- **Registry**: every series declared in `registry/*.yaml` before first pull:
  series_id, source, source code, name, unit, frequency, sa status, default
  transformations, tags (metal, country, category). Price proxies must carry
  `category: price_proxy` and a `caveats` field; caveats auto-render on charts/PDFs.
- **Adapters**: subclass `BaseAdapter`. Required behaviour: retry/backoff, incremental
  update, schema validation, revision capture, **loud failure** (never silent
  staleness), manual-inbox fallback (`data/manual/`) for fragile sources.
- **Layering**: `app/` (Streamlit) contains zero analytics logic — it calls `quant/`
  and `models/` only.

## Repo layout

```
registry/  adapters/  data/  quant/  app/  tracker/  models/  reports/  docs/  tests/
```

## Coding standards

Python 3.11+. Type hints everywhere. `pydantic` for config/schemas. `pytest` for tests
(every adapter gets fixture-based tests; save one real raw payload per source into
`tests/fixtures/`). `ruff` for lint. Small modules, no cleverness without a comment.

## Workflow rules

- Non-trivial module: write a short spec (interface, inputs/outputs, failure modes)
  and get confirmation before implementing.
- After completing a module: write `docs/<module>_handover.md` — purpose, public
  interface, data dependencies (registry series), known limitations, how to test.
- When an external source misbehaves: capture the raw payload into fixtures, fail
  loudly, suggest a fallback. Do not paper over.
- Commit in small, reviewable increments with clear messages.

## Data sources (Step 1)

**API, key in .env**: FRED (`FRED_API_KEY`), e-Stat Japan (`ESTAT_APP_ID`),
INEGI Mexico, KOSIS Korea, Destatis GENESIS, data.gov.in (India).
**API, no key**: Eurostat dissemination API, StatCan WDS, CFTC COT
(Socrata, publicreporting.cftc.gov).
**No API — file parsers**: Cochilco (Chile copper, monthly Excel), MINEM (Peru,
monthly Excel), IAI (aluminium production CSV/XLS), ICSG/INSG/ILZSG (press-release
tables only; full data is paid). Parsers must detect layout changes (validate row
counts / expected headers) and fail loudly.
**Fragile**: NBS China — unofficial easyquery JSON endpoint; defensive parsing,
manual-inbox fallback. Taiwan (DGBAS/MOEA) — mixed; scheduled scrape with
change-detection where no API.

## Price-proxy layer (no licences)

- COMEX copper: yfinance `HG=F` daily; FRED/World Bank/IMF monthly for history.
- Aluminium: Westmetall free LME settlement table; yfinance `ALI=F` backup.
- **Physical premiums (priority theme)**: CME cash-settled AUP (US Midwest, settles to
  monthly avg of Platts assessment) and EDP (European duty-paid, Fastmarkets).
  (a) yfinance `AUP=F` — thin contract, prefer monthly aggregation;
  (b) expired-month final settlements == assessment monthly average → free
  reconstruction of premium history;
  (c) **daily capture of CME published settlements across all listed months** into the
  point-in-time layer → vintage-stamped premium forward-curve history. Time-sensitive:
  cannot be backfilled. Build early, run daily.
- Energy inputs: EIA API (`EIA_API_KEY`), Eurostat energy prices.
- All of the above: `category: price_proxy` + caveats in registry.

## Quant toolkit (Step 3)

OLS with Newey–West HAC errors as default (overlapping returns are the norm).
STL seasonal adjustment (X-13 if binary present); adjusted series stored back as
derived series with lineage. Rolling correlations + lead–lag scan. Walk-forward
split helpers and `get_series(series_id, as_of=...)` point-in-time retrieval.
Transformations (YoY, 3m/3m ann., z-scores) are registry-aware.

## Forecasting (Step 5)

Benchmarks first: random walk, seasonal RW, curve-implied where available. A model
must beat benchmarks out-of-sample to earn a place. **Forecast combination over model
selection** (inverse-MSE or equal weights; log weights over time). Regime identifier
is built to disconfirm the house view, not optimise classification. Every forecast
logged with as_of, horizon, model id.

## S&D models (Step 6)

Copper + aluminium. Production (Cochilco/MINEM/IAI/study groups) → refined output →
apparent demand (production + net trade − stock change) → balance. Demand via
IP-weighted end-use baskets. Annual/quarterly granularity — no false monthly precision.
Premium forecasting (regional balance, freight, duty, energy, stock geography) is a
first-class deliverable.

## Build order

1. Registry + BaseAdapter + FRED adapter + Parquet layer
2. Eurostat, StatCan, e-Stat adapters
3. CFTC COT + proxy layer **+ daily CME premium-settlement capture job (urgent)**
4. Quant toolkit core
5. Streamlit chart layer
6. Trade tracker (append-only JSON; expression types incl. regional premium;
   calibration + hit-rate analytics; one-page track-record PDF)
7. Remaining national-stats adapters
8. Cochilco/MINEM/IAI/study-group parsers
9. Seasonal adjustment, correlations, PDF reports (WeasyPrint)
10. Forecasting: benchmarks → pool → combination → regime identifier
11. S&D models
