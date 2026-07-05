# Handover — Streamlit dashboard (Build Order Step 5)

## Purpose
The reader-facing chart layer over the point-in-time fact table. Browse the registry,
plot any series **point-in-time**, switch between growth/level transforms, and inspect
positioning and data coverage. Styled to the project `DESIGN.md` (WSJ / Dona Wong
information-graphics principles).

## Charter compliance (layering)
`app/` contains **zero analytics**. It only:
- **reads** the store — `quant.store.get_series(series_id, as_of=...)` (point-in-time)
  and descriptive coverage from `read_facts()` (reading the store is not analytics);
- **reads** the registry — `registry.loader.load_registry()`;
- **calls** `quant.transforms.apply(...)` for every growth/level/MA view.

All maths (YoY, MoM, 3MMA, differences) lives in **`quant/transforms.py`** — a focused
slice of the step-4 quant toolkit pulled forward because the transform toggle requires
it. The app never computes a rate or a difference itself. Even "net positioning"
(long − short) is deliberately **not** shown, to avoid arithmetic in the app.

## How to run
```
.venv/Scripts/python -m streamlit run app/Home.py
```
Optional deps installed via `pip install -e .[app]` (`streamlit`, `altair`). A ready
launch config lives at `.claude/launch.json` (name `dashboard`, port 8521).

## Public structure
```
app/
  theme.py         WSJ colour tokens, page CSS, Altair builders. Black axes + outside
                   ticks, span-aware date format, highlighted last obs (marker + value).
  data_access.py   read-only: registry(), get_series(), coverage_table(), region_for()
  controls.py      filter_bar (2 button rows), month date-range (left panel), transform
                   picker — all wire to quant.transforms; no maths here.
  Home.py          CHART DASHBOARD — grid of tiles (3 across), each in its default view.
  pages/
    1_Chart_Focus.py   single series in depth: dropdown + transform menu + point-in-time
    2_Positioning.py   COMEX (CFTC) vs LME (MiFID II) copper COT, raw long/short
    3_Coverage.py      per-series rows / date span / latest as_of / staleness
```

### Layout (both dashboard & focus)
- **Two button rows across the top** (`st.segmented_control`, single-select, leading
  "All"): row 1 = **Region** (Global + North America / Europe / Asia / Latin America,
  derived from `tags.country`); row 2 = **Category** (the `macro_theme` buckets).
- **Left panel = date range**, months back: 3 / 12 / 24 / 48 / 120 / Max.
- **Dashboard** tiles show each series' *default* transform (registry). **Focus** adds
  the full transform menu + a point-in-time `as_of` control (left panel).

### Chart styling (`theme.py`)
- **Axes:** black domain line (`INK`) with **outside tick marks**; hairline horizontal
  grid only (no vertical grid).
- **Last observation highlighted:** filled marker + value label at the final point.
- **Date-format is frequency- and span-aware** (`theme.date_format`): annual → `YYYY`;
  monthly/quarterly → `MMM-YY`; daily/weekly → `DD-MMM` for a ≤~1-year window, else
  `MMM-YY` (so a year-less `DD-MMM` never repeats ambiguously across Januaries). Narrow
  grid tiles also thin ticks (`x_tick_count=4`) to avoid label collisions.

## Transforms (`quant.transforms`)
Menu: **Level, YoY %, MoM %, MoM levels, YoY levels, 3MMA YoY %, 3MMA MoM %,
3MMA levels MoM**. Frequency-aware via positional lags `k` = periods/year
(M:12, Q:4, W:52, D:252, A:1); "MoM" is period-over-period at the series' **native**
frequency (user chose native-frequency semantics — no hidden resampling). Daily/weekly
series therefore default to **Level**. Divide-by-zero → NaN (never `inf`). Transforms
run on the **full** point-in-time history, then the page clips to the display horizon,
so YoY near the window's left edge still uses real prior-year data.

Per-series **default** view comes from the registry `transformations` field
(`transforms.default_kind`): `[yoy]` → YoY %, empty/unknown → Level.

## Registry change (architecture contract — was confirmed with the user)
Added an **independent** `macro_theme` tag to `registry/schema.py` (new `MacroTheme`
enum: activity / inflation / rates / commodities / positioning / energy / other).
`category` is unchanged and still drives price-proxy caveat behaviour; `macro_theme`
is the reader-facing dashboard bucket. All 16 series tagged (activity 4, commodities 3,
positioning 9). **Inflation** and **Rates** are declared but empty until CPI / policy-rate
adapters land (steps 7+). Region is derived in-app from `tags.country` (no schema field).

## Data dependencies
All 16 registry series. Charts show whatever is in `data/facts.parquet`; price proxies
(`copper_price_global`, the two Al premiums) auto-render their `caveats` block.

## Known limitations / next
- **Statement titles.** DESIGN.md wants takeaway titles ("Inflation cooled to 2.4%").
  We use the series `name` (descriptive) — a real takeaway needs analysis, which is
  quant's job, not the app's. Revisit once the quant toolkit can supply a headline.
- **LME COTR history is sparse** (current `.xlsx` era only — see
  `lme_cotr_adapter_handover.md`), so LME positioning lines are short.
- **Inflation/Rates themes empty** until those adapters exist.
- **CFTC x-axis can look cramped** when few weeks are in-store; fills in as history grows.
- **No caching invalidation UI** — `data_access._facts()` is `st.cache_data`; restart or
  rerun after an adapter writes new data.
- Direct labels can overlap when two multi-line series sit close (LME long/short).

## Test
- `pytest tests/test_transforms.py` — transform maths (lags, MA-first, div-by-zero, defaults).
- `pytest` — full suite still green (registry schema change is additive/backward-compatible).
- App smoke: `streamlit run app/Home.py` (or the `dashboard` launch config); Chart
  Dashboard / Chart Focus / Positioning / Coverage render against the live store.
