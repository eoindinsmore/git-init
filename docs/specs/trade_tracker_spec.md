# Trade Recommendation Tracker Specification — `tracker/`

Purpose: an append-only, tamper-evident log of trade calls, marked against the free
proxy price layer with point-in-time discipline, producing calibration and hit-rate
analytics and a one-page track-record PDF. This is the centrepiece of the buy-side
evidence package: **its credibility depends entirely on it being impossible to
quietly rewrite history.** Every design decision below serves that.

## 1. Core design: event-sourced, append-only

The tracker is an event log, not a table of editable rows. State is derived by
replaying events. Nothing is ever updated or deleted.

Storage: `tracker/events.jsonl` (one JSON event per line, append-only) as the source
of truth; a derived Parquet view rebuilt from it for analytics. Git-committed, so
history is doubly auditable.

### Event types
- `call.new` — a new recommendation (full payload, section 2)
- `call.amend` — analyst revises target/stop/thesis on an OPEN call. References
  `call_id`, carries only changed fields + reason. The original stands in the log.
- `call.close` — analyst closes at market (discretionary exit). Reason required.
- `call.correction` — fixes a data-entry error. References the erroneous event id,
  states what was wrong. Marked prominently in analytics (corrections are counted
  and reported — frequency of corrections is itself a reported statistic).
- System-generated on marking runs: `call.target_hit`, `call.stopped`, `call.expired`
  (horizon elapsed). Emitted by the marking engine, never by hand.

### Tamper evidence
Every event includes `prev_hash`: SHA-256 of the previous event line. The chain makes
retro-insertion or deletion detectable. A `verify` CLI command replays the file and
confirms chain integrity; the verification result is printed on the track-record PDF.

### Anti-backdating invariants (enforced in code, tested)
- `created_at` is set by the system clock at write time, never accepted from input.
- The marking engine refuses to mark a call using any price data with a date earlier
  than `created_at` (no retroactive entries at yesterday's better level).
- Entry is marked at the **next available close after `created_at`** — never the
  same-day close if the call was logged after that close, never the decision-moment
  price. Conservative by construction; document this convention on all outputs.
- Closed/expired/stopped calls are frozen; `call.amend` on a non-open call is rejected.

## 2. `call.new` payload (pydantic model, validate hard)

```python
class TradeCall(BaseModel):
    call_id: str                    # uuid
    created_at: datetime            # system-set, UTC
    instrument: str                 # registry series_id(s) it is marked against
    expression: Literal[
        "outright",                 # single proxy series
        "time_spread",              # near vs deferred (needs curve data)
        "regional_premium",         # AUP / EDP series
        "cross_product_rv",         # ratio/spread of two series (e.g. Cu vs Al)
        "arb_proxy",                # e.g. SHFE/LME ratio where data permits
    ]
    metal: str                      # tag from registry vocabulary
    direction: Literal["long", "short"]
    entry_basis: str                # "next_close" (only option v1; field exists
                                    #  so the convention is explicit in every record)
    target: float                   # in units of the marked series
    stop: float
    horizon_days: int               # calendar days to expiry of the call
    confidence: float               # stated P(target before stop within horizon),
                                    # 0.05–0.95, forced granularity of 0.05
    size_R: float = 1.0             # risk units; sizing suggestion may come from
                                    # regime module but analyst decides
    thesis: str                     # required, min length enforced; the reasoning
    catalysts: list[str] = []
    source_scan_id: str | None      # link back to scanner flag if promoted from it
    regime_at_entry: str | None     # stamped automatically from regime module
    prev_hash: str
```

Validation rules: target/stop must be on the correct side of the last available mark
for the stated direction; horizon 5–365 days; instrument must exist in registry and
have `category: price_proxy` or a real data series; reject otherwise with a clear
message.

## 3. Marking engine (`tracker/marking.py`)

Runs daily (or on demand). For every OPEN call:

1. Pull the marked series **as of the marking date** via `get_series(..., as_of=...)`.
2. Determine entry price if not yet set (first close after `created_at`).
3. Check stop and target against the day's mark. Both touched intra-period is
   unknowable with close-only data → **worst-case convention: stop takes precedence.**
   Document on outputs. (Close-only marking is a stated limitation, not a bug.)
4. Horizon elapsed → `call.expired`, P&L at final mark.
5. Compute running P&L in two parallel units:
   - **R-multiples**: (mark − entry)/(entry − stop), sign-adjusted. Primary unit —
     honest across instruments of wildly different volatility and units.
   - **Proxy notional**: vol-targeted position (target risk per call configurable,
     e.g. 50bp of a nominal book) using trailing realized vol of the marked series.
     Enables portfolio-style equity curve. Label clearly as proxy terms everywhere.

Expression-type specifics:
- `time_spread`: marked series is a constructed spread from the point-in-time curve
  capture (CME premium curve, COMEX copper chain). If curve data is missing for a
  date, carry last mark and flag; never interpolate silently.
- `cross_product_rv` / `arb_proxy`: marked series is a declared ratio/spread of two
  registry series; construction stored in the registry like any derived series.
- Data-unavailable expressions must be rejected at `call.new` time, not fail at
  marking time.

## 4. Analytics (`tracker/analytics.py`)

All statistics computed from the derived Parquet view; every table shows sample size.

- **Hit rate** (target before stop within horizon) by: expression, metal, horizon
  bucket, direction, regime-at-entry, confidence bucket.
- **Calibration**: stated confidence vs. realized frequency per confidence bucket;
  reliability diagram; **Brier score** overall and by bucket. This chart is the
  single most important exhibit in the package.
- **P&L**: cumulative R and proxy-notional equity curve; avg win/loss in R; expectancy
  per call; max drawdown in R; time-under-water.
- **Process stats** (reported, deliberately): number of amends per call, number of
  corrections, average thesis length, % of calls originating from scanner flags,
  discretionary-close frequency and their counterfactual outcome (what would have
  happened if held to plan — honesty exhibit).
- Small-sample honesty: wherever n < 20, print n and suppress percentage-only
  displays; no smoothing that hides sparsity.

## 5. Outputs

- **Streamlit page**: open calls with live marks; closed-call table with filters;
  calibration and equity charts; process stats.
- **One-page track-record PDF** (WeasyPrint): headline stats, calibration diagram,
  equity curve in R, hit-rate matrix, marking conventions box (next-close entry,
  stop-precedence, close-only limitation, proxy-data caveat), hash-chain verification
  line, generation timestamp. This page is what gets handed across a table — it must
  be self-explanatory and self-caveating.

## 6. Integration hooks

- **Scanner → tracker**: scanner "promote" action creates a pre-filled DRAFT payload
  (instrument, scan reference). Draft is local UI state only — nothing enters
  `events.jsonl` until the analyst completes thesis/levels/confidence and submits.
- **Regime module**: stamps `regime_at_entry` automatically; may display a sizing
  suggestion; never auto-sets `size_R`.
- **Forecast platform**: model-generated forecasts are NOT tracker calls. Keep
  namespaces separate (model performance tracker vs. analyst call tracker). A call
  may cite a model in its thesis; the human owns the call.

## 7. CLI (thin wrapper, `tracker/cli.py`)

`new` (interactive prompts with validation), `amend`, `close`, `mark` (run marking),
`verify` (hash chain), `report` (render PDF). Streamlit uses the same underlying
functions; no logic in the CLI layer.

## 8. Tests that must exist before the module is "done"

- Append-only enforced: any code path that rewrites `events.jsonl` fails tests.
- Hash-chain verification catches an edited/deleted/inserted line (fixture with a
  tampered file).
- Backdating rejected; same-day-close entry rejected; wrong-side target/stop rejected.
- Marking respects `as_of` (fixture where a revision changes history — the mark must
  use the vintage, not the revised value).
- Stop-precedence convention applied when both levels touched.
- Calibration math verified against a hand-computed fixture.

## 9. Build order

1. Event log + hash chain + pydantic models + `verify`
2. Marking engine for `outright` and `regional_premium` (the two live-data-ready
   expressions) + R-multiple P&L
3. Analytics core: hit rates + calibration + equity curve
4. CLI + Streamlit page
5. PDF one-pager
6. Remaining expression types as their data feeds mature; vol-targeted notional P&L;
   scanner and regime hooks

Start logging real calls the moment step 2 works. The track record starts on the day
of the first `call.new`, and its age is itself part of its value.
