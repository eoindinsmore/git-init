# Quant toolkit — data-gap register

The toolkit machinery is built and tested, but several modules declare drivers/inputs
the registry doesn't yet provide. Listing them here **is** the "report what isn't wired
yet" discipline the spec §9 checklist rewards — the modules drop missing series *loudly*
(reported in each run's `.missing`), never silently.

Legend for "how to fill": **FRED-now** = a free FRED series addable today via the existing
FRED adapter (registry entry + pull); **adapter** = needs a new/己planned adapter;
**paid/manual** = no free feed, manual-inbox or paid source.

| Series id (declared) | Used by | What it is | How to fill |
|---|---|---|---|
| `usd_broad_index` | decomp (copper, aluminium), regimes | Broad trade-weighted USD | **FRED-now** — `DTWEXBGS` |
| `us_10y_real_yield` | decomp (copper, aluminium) | US 10y TIPS real yield | **FRED-now** — `DFII10` |
| `vix_index` | regimes | CBOE VIX | **FRED-now** — `VIXCLS` |
| `energy_input_composite` | decomp, composites | Energy input cost composite | **adapter** — EIA API (charter energy step) → then a `quant/composites` PCA |
| `china_activity_composite` | decomp (aluminium), composites | China activity proxy | **adapter** — NBS (fragile) / proxies, then a composite |
| `global_mfg_pmi` | regimes | Global manufacturing PMI (>50/<50 × 3m Δ) | **paid/manual** — S&P Global/ISM proprietary; use regional-Fed-survey proxy or manual inbox |
| CME premium **forward-curve** slopes | scanner | Full-curve premium term structure | **paid/manual** — front-month only today (see `docs/cme_premium_data_options.md`); needs paid DataMine or manual capture |
| slow-release nowcast targets (global IP, China aluminium demand proxy, regional apparent demand) | nowcast | Low-freq targets with faster indicators | **adapter** — national-stats / study-group parsers (project steps 7–8, 11) |

## Quick wins (addable now, no new adapter code)
`usd_broad_index` (DTWEXBGS), `us_10y_real_yield` (DFII10), and `vix_index` (VIXCLS) are
free FRED series. Adding three registry entries and running the FRED adapter would light
up the decomposition driver set and the regime state variables immediately. Deferred here
only to keep the toolkit build (this change) separate from data-ingestion changes.

## What runs fully today (no gaps)
- **Decomposition** on `us_industrial_production` + `copper_cot_mm_long` (copper spec).
- **Scanner** on premiums + copper price + full CFTC COT (raw + derived spreads/ratios).
- **Indicator lab** on any stored target/candidate set.
- **Composites** — `positioning_copper` PCA on CFTC COT (481 points).
- **Backtester** on any Signal + stored instrument.
- **Nowcast** machinery on any stored target + higher-freq indicator.
- **Regimes** on any stored state series (demoed on a copper-price trend regime).
