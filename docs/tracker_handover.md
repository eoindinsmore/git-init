# Trade recommendation tracker — handover

Implements `docs/specs/trade_tracker_spec.md` (project step 6). An append-only,
tamper-evident, event-sourced log of trade calls, marked against the free proxy price
layer with point-in-time discipline, producing calibration/hit-rate/P&L analytics and a
one-page track-record artifact. Built on branch `quant-toolkit` in five phases (one
commit each), on top of — not replacing — the scanner `Hypothesis` seed.

## Two layers, kept separate
- **Scanner draft seed** — `tracker/schema.py` (`Hypothesis`) + `tracker/store.py`
  (`data/hypotheses.jsonl`). A dislocation scan *promotes* a draft here; a draft is not a
  call. Untouched by this build (the scanner still imports it).
- **Committed call log** — the event-sourced layer below. A draft becomes a committed
  call only when an analyst supplies levels/thesis/confidence and logs a `call.new`.

## Modules (`tracker/`)
- **`events.py`** — the source of truth. Seven pydantic event types (`call.new`,
  `call.amend`, `call.close`, `call.correction`, and marking-only `call.target_hit` /
  `call.stopped` / `call.expired`). Append-only JSONL at **`tracker/events.jsonl`**
  (git-committed — doubly auditable). SHA-256 `prev_hash` chain over the **raw stored
  lines**; `verify()` replays and pinpoints any edit/deletion/insertion by line index.
  `NewCall` carries the full §2 payload with hard field validation (horizon 5–365,
  confidence on the 0.05 grid, thesis ≥20 chars).
- **`state.py`** — `replay(events) → {call_id: CallState}`, a pure fold. Live prices are
  deliberately *not* derived here (they depend on data outside the log).
- **`pricing.py`** — pure marking maths: next-close entry (never same-day),
  anti-backdating, R-multiple, stop-precedence / first-touch resolution, horizon expiry.
- **`calls.py`** — the only sanctioned authoring path: `new_call` / `amend` / `close` /
  `correct`. `created_at` is stamped from the system clock (never from input); tests inject
  a clock via the private `_now` hook. Data-dependent validation (instrument exists + has
  data, target/stop on the correct side of the last mark, expression is live) lives here.
  amend/close are refused on frozen (resolved) calls.
- **`marking.py`** — `mark_open_calls(as_of)` marks every OPEN call **vintage-strict**
  (`store.get_series(as_of=...)`, so a later revision can't rewrite a hit) and emits one
  terminal system event per resolution with entry/exit/pnl frozen. Idempotent. Only
  `outright` + `regional_premium` are markable (single registry series); other expressions
  are rejected at `call.new`.
- **`analytics.py`** — one derived `build_view` (row per call: facts + resolution + live
  marks), then `hit_rate` (by any dimension), `calibration` (Brier + reliability table;
  market resolutions only), `pnl_summary` (cumulative-R equity, expectancy, drawdown, time
  under water), `process_stats` (amends, corrections, thesis length, % from scanner, and
  the discretionary-close **counterfactual** honesty exhibit). Small samples (n<20) carry
  a `sparse` flag so presentation suppresses bare percentages.
- **`report.py`** — self-contained one-page HTML (inline-SVG calibration diagram + equity
  curve, headline metrics, hit-rate matrix, marking-conventions box, hash-chain
  verification line, timestamp). `render(..., out_path=...)`: `.pdf` uses WeasyPrint when
  installed, else degrades to `.html` so a report is always produced.
- **`cli.py`** — `python -m tracker.cli {new,amend,close,mark,verify,report}`; thin wrapper,
  no business logic.

## App
- **`app/pages/11_Trade_Tracker.py`** — verify line, new-call form, run-marking button,
  open calls with live unrealized R, resolved-call log with filters, calibration diagram +
  Brier, R equity curve, process stats + counterfactual, and an HTML track-record download.
  Zero analytics in the app — every number comes from `tracker/`. Verified rendering live.

## Conventions baked in (stated on every output)
Next-close entry · anti-backdating · stop precedence · close-only marking · free-proxy
prices · calibration/hit-rate exclude discretionary closes · n<20 → counts not percentages.

## Tests (all offline, fixture-based)
`test_tracker_events.py` (append-only, hash-chain tamper detection, validation),
`test_tracker_marking.py` (target/stop/expiry, next-close, R-multiples, **§8 vintage vs
revision**, idempotency), `test_tracker_analytics.py` (**Brier hand-computed**, hit rate,
P&L math, closes excluded, end-to-end view), `test_tracker_report.py` (sections, chain
line, PDF→HTML fallback, empty view), `test_tracker_cli.py` (parser + verify). Full suite
green, ruff clean.

## Deferred (spec §9 step 6 — as data feeds mature)
`time_spread` / `cross_product_rv` / `arb_proxy` expressions (need curve/derived series;
rejected at entry until then); vol-targeted **proxy-notional** P&L (only R-multiples so
far); the scanner→`call.new` draft-promotion UI hook; regime state series so
`regime_at_entry` stops being blank (VIX/PMI/USD not yet in the store — see
`docs/quant_data_gaps.md`).

## First real call
The track record starts on the day of the first `call.new`, and its age is part of its
value — so `tracker/events.jsonl` is intentionally absent until the analyst logs one
(via the app form or `python -m tracker.cli new`).
