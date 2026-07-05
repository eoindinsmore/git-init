# CME premium forward-curve data — access options (research findings)

**Question:** how to legitimately, freely capture the *full forward curve* (all
listed contract months) of CME aluminium premium futures — AUP (US Midwest, Platts)
and EDP (European duty-paid, Metal Bulletin/Fastmarkets) — for a daily
vintage-stamped capture job.

**Bottom line:** there is **no fully-free, ToS-permitted, automated daily feed** of
the full curve for these two contracts. CME has deliberately closed the free
automated paths. Our current job therefore captures the front-month only (yfinance,
ToS-clean). The full curve requires a paid/licensed source or manual capture.

## Why the website API is off-limits (not just a bot wall)
CME's terms **explicitly prohibit** automated retrieval: *"strictly prohibited from
… scripts, software, spiders, robots … to navigate, access, copy in bulk,
retrieve, harvest, index, search, or analyze any portion of the Website."*
Settlement prices are named "CME Data." **From 2024-01-08 CME deployed anti-scraping
technology** — that is the Akamai 403 we hit. So `CmeWS/mvc/Settlements/...` is
off-limits **by contract**, and we correctly do not evade it. Delayed settlements
are free to *view* (published after midnight CT) — but "view" ≠ licensed automated
download.
- Terms: https://www.cmegroup.com/trading/market-data-explanation-disclaimer.html
- Settlement FAQ: https://www.cmegroup.com/articles/faqs/access-to-cme-group-settlement-data-faq.html

## Options ranked

| Option | Free? | Automatable full curve? | Notes |
|---|---|---|---|
| **CME DataMine EoD (COMEX settlements)** | Paid (quote via CMEDataSales@) | ✅ REST API / daily files | The clean legit path. `datamine_python` wrapper. Covers all listed months. |
| **DataMine for Education** | 50% off (academic only) | ✅ | Cheapest licensed route **if** a university affiliation exists. |
| **Google Analytics Hub — settlements** | Paid (+ BigQuery query cost) | ✅ T+1 nightly | COMEX in scope. Query, don't scrape. |
| **Google RDW (reference data)** | ✅ Complimentary | ❌ no prices | Reference/instrument data only — contract specs, settlement *dates*, not values. |
| **Daily Bulletin Section 62 (metals PDF)** | ✅ to view | ❌ | Full curve, but FTP feed **removed**; PDFs now behind the same anti-scraping host. Manual only. |
| **DataMine free FTP samples** | ✅ | ❌ (static) | `ftp://ftp.cmegroup.com/datamine_sample_data/` — use to pre-build/test the EoD parser. |
| Nasdaq Data Link / Quandl | — | ❌ | Dead end: never carried these premium curves; `CHRIS` stale since ~2021. |
| TradingView / brokers | — | ❌ | Front-month quote only; ToS bars systematic export. |

## Recommendation
1. **If academic affiliation available:** DataMine for Education (50% off) →
   COMEX EoD/Settlements dataset → automate via DataMine REST API. Cleanest full
   legitimate path.
2. **Commercial:** quote from CMEDataSales@cmegroup.com for DataMine EoD COMEX
   settlements *or* Analytics Hub settlements (BigQuery). Pre-build the ingest +
   vintage-stamping pipeline against the **free FTP sample files** so a subscription
   starts paying off day one.
3. **Zero-budget:** keep the current yfinance front-month capture (running daily);
   optionally add manual periodic capture of the delayed website/Section-62 curve
   into `data/manual/` (human-driven, not scripted — within ToS).

## Impact on our build
- `adapters/premium.py` stays as the front-month capture (ToS-clean, running daily).
- A future `CmeDataMineAdapter` would slot in as the full-curve source once a license
  exists; the free FTP samples let us build its parser now without a subscription.
- The point-in-time store already handles vintage-stamped forward curves (store one
  row per contract-month per capture day) — no schema change needed to adopt DataMine
  later.

*Sources compiled 2026-07-05; DataMine/Analytics-Hub pricing is quote-based and
several CME pages are themselves behind the anti-scraping layer — confirm SKUs with
CME Data Sales directly.*
