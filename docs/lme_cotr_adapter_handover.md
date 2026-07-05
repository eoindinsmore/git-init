# Handover — LME COTR adapter (Build Order Step 3)

## Purpose
Capture the London Metal Exchange **Commitments of Traders** (MiFID II Article 58)
weekly positioning into the fact table. Complements the CFTC COMEX COT with an
LME-side, MiFID-classified view of the same metals.

## Charter note (why this is in-bounds)
Rule #1 bans licensed LME **price** feeds. This adapter takes only the **free MiFID II
positioning disclosure** — no price/settlement data — ruled in-bounds by the user as
exchange-published positioning (rule #7). Access is via the LME CDN, which serves the
XLSX files to plain requests (HTTP 200); the bot-protected HTML listing pages are never
scraped.

## Public interface
```python
from adapters.lme_cotr import LmeCotrAdapter
LmeCotrAdapter().run("copper_lme_inv_funds_long")   # -> rows written
```
One registry series per (category, side). `source_params`:
`folder` (CDN slug, e.g. `ca-copper`), `key` (filename key, e.g. `ca`),
`category` (MiFID class substring), `side` (`Long`/`Short`), `basis`
(`Total` default / `Risk Reducing` / `Other`), `weeks` (recent weeks to fetch, default 12).

## Data dependencies
[`registry/lme_cotr.yaml`](../registry/lme_cotr.yaml) — LME copper: Investment Funds
long/short and Commercial Undertakings long/short (category `positioning`).

## Point-in-time mapping (exact)
Each XLSX carries **both** dates, so no estimation is needed:
- `date`  = position date (prior **Friday** close, cell row 3)
- `as_of` = **publication timestamp** (cell row 4, tz-aware UTC → normalized) — the
  honest "known by". A backtest on the Friday snapshot cannot see the report until its
  (following-week) publication.

## URL scheme & robustness
`https://www.lme.com/-/media/files/data/cotrs/<folder>/mifid-weekly-cotr-report--<key>--<DDMMYYYY>.xlsx`
where `<DDMMYYYY>` is the publication day. Publication is normally **Tuesday** but
**shifts around UK bank holidays** (e.g. Wed 27 May 2026 after the spring bank holiday),
so the adapter probes Tue, then Wed/Mon/Thu per week and takes the first valid file.
HTTP 200 with a non-ZIP body (soft-404) is rejected via the `PK` magic-byte check.

## Failure modes (loud)
- Missing `folder`/`key` or `category`/`side` in `source_params` → `AdapterError`.
- No valid file in the whole window → `AdapterError` (or `TransientFetchError` if all
  failures were network-level, so retry kicks in).
- Category/side/basis or expected labels not found in the sheet → `AdapterError`
  (treats it as a layout change).

## Known limitations / next
- **Filename scheme evolved.** Only the current `.xlsx` era (≈ from 2026-05-19) is
  auto-fetched. Earlier files are `.xls` (legacy binary, not openpyxl-readable) or use
  2020-era `DD-mon-YYYY.xlsx` naming. Deep history is **not** silently included.
- **Backfill path:** drop historic current-format `.xlsx` files into
  `data/manual/lme_cotr/` — `load_manual` reads them all as a fallback. A one-off
  bulk backfill (via the page's full file list) can be scripted later if deep LME
  history is needed.
- Only copper wired; other metals just need registry rows with the right `folder`/`key`
  (AH aluminium, ZS zinc, NI nickel, PB lead, SN tin — confirm each folder slug).
- Should run **weekly** (like CFTC); can share the premium job's scheduling pattern.

## Test
`pytest tests/test_lme_cotr_adapter.py` — offline against the real captured XLSX
`tests/fixtures/*/lme_cotr_copper_30062026.xlsx`, including a lookahead-safety assertion.
