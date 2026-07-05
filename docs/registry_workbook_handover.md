# Handover — registry control workbook (`registry_workbook.py`)

## Purpose
An Excel control surface over the series registry, so new series and default-view
changes can be managed in a spreadsheet instead of hand-editing YAML. The registry
`*.yaml` files remain the **single source of truth** (charter); the workbook is a
convenience layer that mirrors them and writes reviewed edits back.

## The workbook — `registry_control.xlsx` (committed to `main`)
Three tabs:
1. **Series** — every registry series, one row, with an editable **`default_transformation`**
   column (dropdown of the transform menu). Other columns mirror the registry.
2. **New Series** — an input template (same columns + `source_params` / `selector`) with
   validation dropdowns for frequency / sa_status / category / macro_theme / transform.
   Add a row per new series here.
3. **Coverage** — identical to the dashboard's Coverage tab (rows, date span, latest
   `as_of`, staleness), computed from the store.

## Two commands
```
python registry_workbook.py build      # (default) registry + store -> workbook
python registry_workbook.py sync        # workbook edits -> registry/*.yaml
```

- **`build`** rewrites Tabs 1 & 3 from the registry/store and **preserves** pending
  New Series input (Tab 2). It never writes to YAML — safe to run any time.
- **`sync`** writes reviewed edits back into `registry/*.yaml`:
  - changed **default transforms** on the Series tab → the series' `transformations`
    field (written inline, e.g. `[yoy_pct]`);
  - each **New Series** row → validated through `SeriesSpec`, then appended to
    `registry/<source>.yaml`. Rows that fail validation (or duplicate an existing id)
    stay on the New Series tab with the reason; valid ones move to the Series tab.
  - YAML **comments and flow-style are preserved** (ruamel round-trip); unicode (em
    dashes in names) is written UTF-8 intact.

## Weekly automation
Windows Task **`HomeFund-WeeklyWorkbook`** runs `jobs/run_workbook_build.bat` every
**Saturday 09:00** (after `HomeFund-WeeklyCOT` at 08:00, so coverage is fresh). It runs
**`build` only** — the workbook stays current without ever touching YAML unattended.
Logs to `data/workbook_build.log`. `sync` is always a deliberate, manual step.

## The full "add a series" loop
1. Add a row on the **New Series** tab (or edit a default on the **Series** tab).
2. `python registry_workbook.py sync` → writes to `registry/<source>.yaml`.
3. **Review the git diff.**
4. Pull the data: run the adapter, e.g. `FredAdapter().run("us_cpi")` (or
   `python -m adapters.cot_capture` for COT sources).
5. Refresh the dashboard (restart) — the new series appears, filed under its
   `macro_theme` (Category button) and region.

## Dependencies
`openpyxl` (already a core dep) for the workbook; **`ruamel.yaml`** for comment-safe
write-back — installed via the `tools` extra: `pip install -e .[tools]`. `build` needs
only openpyxl; `sync` needs ruamel.

## Known limitations / next
- **Region map is duplicated** in `registry_workbook.py` (`_REGION_BY_COUNTRY`) to keep
  the tool free of a Streamlit import — keep it in sync with `app/data_access.py`.
- Only the **`default_transformation`** column syncs back from the Series tab; editing
  other Series-tab columns is ignored by `sync` (edit those in YAML, or via a new
  New-Series row). New `metal`/`country`/`macro_theme` values on appended series must be
  valid enum members or the row is rejected loudly.
- `source_params` / `selector` on the New Series tab use `key=value;key=value` syntax.
- Appended series get **block-style** `tags:`; if added to a flow-style file
  (`cftc.yaml`), styles will be mixed (valid, just cosmetic — visible in the diff).
- The weekly task does not `git commit`; you review and commit the workbook + any YAML.

## Test
`pytest tests/test_registry_workbook.py` — pure helpers, comment-preserving transform
edits, new-series append (validity + comment preservation), 3-tab build, New-Series
preservation on rebuild, and a full **sync round-trip** (edit default + add valid &
invalid series) against a temp registry.
