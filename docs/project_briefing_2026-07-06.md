# Home Hedge Fund — Project Briefing (for a fresh Claude chat)

*A self-contained context document, current as of 2026-07-06. Paste this into a new Claude chat to bring it up to speed on the project.*

---

## 1. What this is

A personal **commodities-research platform** ("home hedge fund") — base metals, copper-weighted, with aluminium value-chain depth. It doubles as a **buy-side portfolio evidence package**, so code quality and data-provenance discipline matter as much as the analytics.

Repo: `C:\Users\eoind\Home_HF` (cloned from github.com/eoindinsmore/git-init). Python 3.11+, venv at `.venv`.

## 2. Hard constraints (never violate)

- **Free/public data only.** No licensed price feeds (no LME/ICE/Bloomberg/Reuters/Platts/Fastmarkets/CRU/WBMS). Gov/statistical/exchange sources only; no ToS-violating scraping.
- **No employer material. No GPL code** (never copy pysystemtrade — reimplement; cuemacro Apache-2.0 is OK with attribution).
- **Point-in-time discipline**: every observation carries an `as_of`; revisions are *new rows*, never overwrites.
- **Append-only trade tracker**: history must be impossible to quietly rewrite (that is the credibility of the evidence package).
- Secrets in `.env` only.

The full charter lives in the repo at `CLAUDE Instructions for Home Hedge Fund.md`.

## 3. Stack & architecture

- **Data**: long-format Parquet fact table in gitignored `data/facts.parquet`, schema `series_id|date|value|as_of|source|frequency|unit|last_updated`. ~296 series loaded.
- **Registry** (`registry/`): pydantic `SeriesSpec` per series (YAML source of truth) + an Excel control workbook (`registry_workbook.py`) for two-way sync.
- **Adapters** (`adapters/`): subclass `BaseAdapter` (retry/backoff, incremental, schema validation, revision capture, loud failure). FRED / Eurostat / StatCan / e-Stat / CFTC / LME-COTR / premium (yfinance).
- **`quant/`**: the analytics engine (see §4).
- **`models/`**: forecasting models (new; separate namespace from the tracker).
- **`tracker/`**: the append-only trade-call log.
- **`app/`**: Streamlit UI. **Zero-analytics rule** — `app/` does NO maths; it reads the store + registry and calls `quant/` + `models/`. WSJ/Dona-Wong visual theme (see `DESIGN.md`).

**Layering rule to preserve: analytics live in `quant/` + `models/`; `app/` only presents.**

## 4. What's built (modules)

**`quant/`** (spec `docs/specs/quant_toolkit_spec_v2.md`):
- `signal.py` (Signal abstraction — the one interface every module emits), `pit.py` (lag-aware point-in-time reconstruction), `stats.py` (OLS-HAC default, BH-FDR, Campbell-Thompson OOS-R², Diebold-Mariano, block bootstrap, deflated Sharpe, Mahalanobis, walk-forward splits), `scorecard.py`, `transforms.py`.
- `decomp/` (price attribution; rolling regression, sequential economic orthogonalization, additive contributions; **new**: `contribution_timeseries()` for stacked-area over time), `scanner/` (z-score + Mahalanobis dislocation screen; **new**: `mahalanobis_timeseries()`), `indicators/` (5-gate leading-indicator lab), `composites/` (diffusion/zscore/PIT-PCA), `backtest/` (reimplemented Carver forecast-capping, vol targeting, costs, deflated-Sharpe honesty), `nowcast/` (bridge equations, ragged-edge), `regimes/` (rule-based classify + consumption hooks).

**`models/`** (new, project step 4):
- `forecast.py` — extrapolates the driver regression under `hold_last`/`momentum`/`scenario` driver paths, honest √k band.
- `evaluate.py` — walk-forward one-step predictions + OOS-R² skill vs random walk.
- `strategy.py` — sign-following backtest with an optional regime filter + bootstrap p-value.

**`tracker/`** (spec `docs/specs/trade_tracker_spec.md`): event-sourced, **hash-chained**, append-only call log; anti-backdating invariants; marking engine (next-close entry, stop precedence, R-multiples); hit-rate/calibration/P&L analytics; CLI + Streamlit page + one-page track-record report.

**`app/`** (Streamlit): `Home.py` (chart dashboard) + pages. **New**: `0_Workbench.py` — a guided six-step Analysis Workbench (scatter → regression → stacked-area decomposition → forecast → regime-filtered backtest → trade-call draft) driven by one shared sidebar selection. `4_Scanner.py` redesigned into a visual dislocation map + per-item inspect card. `11_Trade_Tracker.py` for the tracker.

## 5. Current state (as of 2026-07-06)

- All work is on branch **`quant-toolkit`**, pushed to `origin`. **A PR into `main` is being opened** (22 commits ahead: toolkit + tracker + Workbench).
- Tests green (`.venv/Scripts/python -m pytest`), `ruff check` clean.
- Run the app: `.venv/Scripts/python -m streamlit run app/Home.py` (deps `pip install -e .[app]`).

## 6. Open items / next steps

- **Data gaps** (`docs/quant_data_gaps.md`): several declared decomposition drivers aren't in the store yet. Free FRED quick-wins that would materially improve the Workbench: broad USD `DTWEXBGS`, 10y real yield `DFII10`, VIX `VIXCLS`. Regime filter needs the global-macro state series loaded.
- The two Workbench engine specs (`docs/specs/decomp_timeseries_spec.md`, `docs/specs/forecast_model_spec.md`) were implemented but **not yet human-reviewed**.
- The 7 original toolkit pages aren't structurally demoted in the nav (a `st.navigation` restructure).
- `models.forecast` refits "total" betas rather than reusing the decomposition's orthogonalized fit (documented deviation — attribution vs forecasting need different bases).
- Publication-lag metadata on ~280 bulk-loaded series still defaults to 0 (fix per-source).

## 7. Working conventions

- Non-trivial module → write a short spec (interface/inputs/outputs/failure modes), get sign-off, THEN implement; after a module → write `docs/<module>_handover.md`.
- Tests are offline, fixture-based per adapter.
- See `docs/workbench_handover.md` for the most recent (Workbench) handover.
