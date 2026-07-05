"""Analysis Workbench — the guided six-step research flow (project step 4/6 UI).

One shared selection (target + drivers + frequency + window), set in the sidebar, threads
through all six steps: 1 Scatter → 2 Regression → 3 Decomposition (stacked area over time)
→ 4 Forecast → 5 Backtest (with regime filter) → 6 Trade recommendation. Each step reads
the point-in-time store and calls quant/ + models/ for the maths — the app does none.

The final step drafts a call into the append-only trade tracker (tracker.calls); the human
owns the call, the model only informs it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import models.evaluate as mevaluate  # noqa: E402
import models.strategy as mstrategy  # noqa: E402
from app import data_access as da  # noqa: E402
from app import theme  # noqa: E402
from app import toolkit_ui as ui  # noqa: E402
from models.forecast import run_forecast  # noqa: E402
from quant.decomp import (  # noqa: E402
    DRIFT,
    RESIDUAL,
    DecompSpec,
    DriverSpec,
    run_contribution_timeseries,
    run_decomposition,
)
from quant.decomp.core import _resample_freq, to_returns  # noqa: E402

theme.configure_page("Workbench")

ui.page_header(
    "Guided analysis",
    "Analysis Workbench",
    "Pick a target and its drivers once, then walk the six steps: see the relationship, "
    "fit it, decompose the price over time, forecast it, backtest it under a regime filter, "
    "and draft a trade call. Every number is computed in quant/ + models/.",
)


# --- Shared selection (sidebar) ---------------------------------------------------
ids = ui.series_with_data()
reg = da.registry()


def _label(sid: str) -> str:
    spec = reg.get(sid)
    return getattr(spec, "label", None) or getattr(spec, "name", None) or sid.replace("_", " ")


DEFAULT_TARGET = "copper_price_global" if "copper_price_global" in ids else ids[0]
DEFAULT_DRIVERS = [d for d in ["us_industrial_production", "copper_cot_mm_long"] if d in ids]

st.sidebar.markdown("### Selection")
target = st.sidebar.selectbox("Target (Y)", ids, index=ids.index(DEFAULT_TARGET), key="wb_target")
driver_opts = [s for s in ids if s != target]
drivers = st.sidebar.multiselect(
    "Drivers (X)", driver_opts,
    default=[d for d in DEFAULT_DRIVERS if d != target] or driver_opts[:2],
    key="wb_drivers",
)
frequency = st.sidebar.selectbox("Frequency", ["M", "W", "Q"], index=0, key="wb_freq")
est_window = st.sidebar.number_input("Estimation window (periods)", 24, 400, 60, step=6,
                                     key="wb_est")
st.sidebar.caption("Returns are log (additive over windows). Current-best view (as-of = latest).")

if not drivers:
    st.warning("Pick at least one driver in the sidebar to begin.")
    st.stop()


def _spec() -> DecompSpec:
    dspecs = [DriverSpec(series_id=d, label=_label(d), order=i) for i, d in enumerate(drivers)]
    return DecompSpec(target=target, target_label=_label(target), drivers=dspecs,
                      frequency=frequency, est_window=int(est_window), return_kind="log")


@st.cache_data(show_spinner=False)
def _returns_panel(target: str, drivers: tuple[str, ...], freq: str) -> pd.DataFrame:
    f = _resample_freq(freq)
    out = {}
    tf = da.get_series(target)
    ts = pd.Series(tf["value"].to_numpy(), index=pd.DatetimeIndex(tf["date"])).resample(f).last()
    out["__target__"] = to_returns(ts, "log")
    for d in drivers:
        df = da.get_series(d)
        s = pd.Series(df["value"].to_numpy(), index=pd.DatetimeIndex(df["date"])).resample(f).last()
        out[d] = to_returns(s, "log")
    panel = pd.DataFrame(out).dropna().reset_index(names="date")
    panel["year"] = panel["date"].dt.year.astype(str)
    return panel


@st.cache_data(show_spinner="Fitting the regression…")
def _decomp(target: str, drivers: tuple[str, ...], freq: str, est: int):
    spec = _spec()
    return run_decomposition(spec), run_contribution_timeseries(spec)


def _series(sid: str) -> pd.Series:
    df = da.get_series(sid)
    return pd.Series(df["value"].to_numpy(), index=pd.DatetimeIndex(df["date"]), name=sid)


def _levels_dicts(target: str, drivers: list[str]):
    """(target_levels, {driver_id: levels}) read from the point-in-time store."""
    return _series(target), {d: _series(d) for d in drivers}


@st.cache_data(show_spinner=False)
def _regimes_series() -> pd.Series | None:
    """Current-best global-macro regime path, or None if its state series aren't loaded."""
    try:
        from quant.regimes import classify_from_store, load_named
        run = classify_from_store(load_named("global_macro"))
        return run.regimes
    except Exception:  # noqa: BLE001 — regimes are optional context, never block the page
        return None


sel = (target, tuple(drivers), frequency, int(est_window))

t1, t2, t3, t4, t5, t6 = st.tabs([
    "1 · Scatter", "2 · Regression", "3 · Decomposition", "4 · Forecast",
    "5 · Backtest", "6 · Recommend",
])


# === STEP 1 · Scatter =============================================================
with t1:
    theme.title_block("The relationship", "Target return vs each driver return · coloured by year")
    panel = _returns_panel(target, tuple(drivers), frequency)
    if panel.empty or len(panel) < 5:
        st.info("Not enough overlapping history for these series at this frequency.")
    else:
        pick = st.selectbox("Driver to plot", drivers, format_func=_label, key="wb_sc_driver")
        st.altair_chart(
            ui.scatter_chart(
                panel, x=pick, y="__target__",
                x_title=f"{_label(pick)} — log return",
                y_title=f"{_label(target)} — log return",
                color="year", fit=True,
            ),
            use_container_width=True,
        )
        corr = panel[[pick, "__target__"]].corr().iloc[0, 1]
        st.caption(f"Pairwise correlation: {corr:+.2f} · n = {len(panel)} periods. "
                   "The fit line is a drawing aid; the trustworthy betas are in step 2.")
    theme.source_line("Source: quant.decomp.to_returns over the point-in-time store.")


# === STEP 2 · Regression ==========================================================
with t2:
    try:
        run, cts_run = _decomp(*sel)
    except ValueError as e:
        st.error(f"Regression could not be fit: {e}")
        st.stop()
    r = run.result
    theme.title_block("The fit", "Rolling HAC regression · residual labelled unexplained")
    c1, c2, c3 = st.columns(3)
    c1.metric("R²", f"{r.rsquared:.2f}")
    c2.metric("Observations", r.nobs)
    c3.metric("Drivers used", len(run.used))
    ui.missing_note(run.missing)
    st.markdown(
        f"<div class='chart-sub'>Orthogonalization order: "
        f"<b>{' → '.join(run.spec.label_of(s) for s in r.order) or '(none)'}</b></div>",
        unsafe_allow_html=True)
    beta_rows = []
    for nm in r.betas.index:
        lbl = "drift (const)" if nm == "const" else run.spec.label_of(nm)
        beta_rows.append({"driver": lbl, "β": round(float(r.betas[nm]), 3),
                          "t (HAC)": round(float(r.tvalues[nm]), 2),
                          "sign flips": int(r.sign_flips.get(nm, 0))})
    st.dataframe(beta_rows, use_container_width=True, hide_index=True)
    theme.source_line("Source: quant.decomp.run_decomposition · HAC (Newey–West) errors.")


# === STEP 3 · Decomposition (stacked area over time) ==============================
with t3:
    _, cts_run = _decomp(*sel)
    cs = cts_run.series
    theme.title_block("Why the price moved, over time",
                      "Cumulative contribution of each driver · drift and residual included")
    labels = {DRIFT: "drift", RESIDUAL: "unexplained",
              **{d: _label(d) for d in cts_run.used}}
    st.altair_chart(
        ui.stacked_contribution_area(cs.cumulative, labels=labels,
                                     residual_col=RESIDUAL, drift_col=DRIFT),
        use_container_width=True)
    recon_err = float((cs.reconstructed - cs.actual).abs().max())
    st.caption(f"Bands stack to the total move; the residual closes to the actual path "
               f"(reconstruction error {recon_err:.2e}, exact for log returns). "
               "Summed over the window these equal the step-2 contributions by construction.")
    theme.source_line("Source: quant.decomp.contribution_timeseries.")


# === STEP 4 · Forecast ============================================================
with t4:
    theme.title_block("Short-term forecast", "The regression extrapolated · honest band")
    cc1, cc2, cc3 = st.columns(3)
    horizon = cc1.number_input("Horizon (periods)", 1, 36, 6, key="wb_h")
    assumption = cc2.selectbox("Driver path", ["hold_last", "momentum", "scenario"],
                               key="wb_assume")
    conf = cc3.slider("Confidence band", 0.50, 0.95, 0.80, step=0.05, key="wb_conf")
    driver_paths = None
    if assumption == "scenario":
        st.caption("Assumed per-period return for each driver (fraction, e.g. 0.01 = +1%/period):")
        cols = st.columns(max(1, len(drivers)))
        driver_paths = {}
        for i, d in enumerate(drivers):
            driver_paths[d] = cols[i % len(cols)].number_input(
                _label(d), -0.20, 0.20, 0.0, step=0.005, format="%.3f", key=f"wb_sc_{d}")
    try:
        fc = run_forecast(_spec(), horizon_periods=int(horizon), driver_assumption=assumption,
                          driver_paths=driver_paths, conf=conf)
        hist = da.get_series(target).rename(columns={"value": "value"})
        hist = hist[["date", "value"]].tail(max(24, int(est_window)))
        st.altair_chart(ui.forecast_chart(hist, fc.path, y_unit=_label(target)),
                        use_container_width=True)
        m1, m2, m3 = st.columns(3)
        m1.metric("Expected return / period", f"{fc.expected_period_return:+.3%}")
        m2.metric(f"Point ({horizon}p)", f"{fc.path['point'].iloc[-1]:,.2f}")
        m3.metric("Residual σ / period", f"{fc.resid_std:.4f}")
        for note in fc.notes:
            st.caption(f"· {note}")
    except ValueError as e:
        st.error(f"Forecast failed: {e}")
    theme.source_line("Source: models.forecast.run_forecast (total, non-orthogonalized betas).")


# === STEP 5 · Backtest with regime filter =========================================
with t5:
    theme.title_block("Would it have worked?",
                      "Walk-forward skill vs a random walk · sign-following P&L · regime filter")
    min_train = max(24, int(est_window))
    tgt_lv, drv_lv = _levels_dicts(target, drivers)
    try:
        skill = mevaluate.walk_forward_skill(
            tgt_lv, drv_lv, order=list(drivers), frequency=frequency,
            est_window=int(est_window), min_train=min_train, driver_assumption="momentum")
    except ValueError as e:
        st.info(f"Not enough history to evaluate skill: {e}")
        skill = None

    if skill and skill["n"] > 0:
        s1, s2, s3 = st.columns(3)
        s1.metric("OOS R² vs random walk", f"{skill['oos_r2_vs_rw']:+.3f}")
        s2.metric("MAE (model)", f"{skill['mae']:.4f}")
        s3.metric("Sample (n)", skill["n"])
        if skill["oos_r2_vs_rw"] <= 0:
            st.caption("⚠ The model does not beat a random walk out of sample here — "
                       "treat any backtest P&L below with scepticism.")

    # Regime filter
    regimes = _regimes_series()
    allowed = None
    if regimes is not None and not regimes.empty:
        opts = sorted(regimes.dropna().unique().tolist())
        allowed = st.multiselect("Trade only in these regimes (empty = all)", opts,
                                 default=[], key="wb_regimes")
        st.caption(f"Current regime: **{regimes.dropna().iloc[-1]}**"
                   if len(regimes.dropna()) else "Current regime: —")
    cost = st.slider("Cost (bps per turnover)", 0, 100, 10, step=5, key="wb_cost")
    try:
        res = mstrategy.backtest_regression(
            tgt_lv, drv_lv, order=list(drivers), frequency=frequency,
            est_window=int(est_window), min_train=min_train, driver_assumption="momentum",
            cost_bps=float(cost), regimes=regimes, allowed_regimes=allowed or None)
        eq = ui.signal_frame(res.equity)
        st.altair_chart(ui.area_chart(eq, y_unit="cum. return"), use_container_width=True)
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Cumulative", f"{res.cumulative_return:+.3f}")
        b2.metric("Sharpe (ann)", f"{res.sharpe_ann:.2f}")
        b3.metric("Hit rate", f"{res.hit_rate:.0%}" if res.hit_rate == res.hit_rate else "—")
        b4.metric("Bootstrap p", f"{res.bootstrap_pvalue:.2f}")
        st.caption(f"Sign-following, {res.periods_in_market} periods in market"
                   + (" · regime-filtered." if res.regime_filtered else "."))
    except ValueError as e:
        st.info(f"Backtest unavailable: {e}")
    theme.source_line("Source: models.evaluate + models.strategy · costs on turnover.")


# === STEP 6 · Trade recommendation ================================================
with t6:
    theme.title_block("Draft a trade call", "Pre-filled from the analysis · you own the call")
    from tracker import calls as tcalls  # noqa: E402

    last_mark = tcalls.latest_mark(target)
    if last_mark is None:
        st.error(f"{target} has no mark in the store; it cannot be a tracker instrument.")
        st.stop()

    # Pre-fill from the forecast direction if available.
    try:
        fc6 = run_forecast(_spec(), horizon_periods=int(st.session_state.get("wb_h", 6)),
                           driver_assumption="momentum")
        implied_long = fc6.expected_period_return >= 0
        pt = float(fc6.path["point"].iloc[-1])
    except Exception:  # noqa: BLE001
        implied_long, pt = True, last_mark * 1.05

    st.caption(f"Last mark: **{last_mark:,.2f}** · model-implied direction: "
               f"**{'long' if implied_long else 'short'}**")
    with st.form("wb_call"):
        c1, c2, c3 = st.columns(3)
        direction = c1.selectbox("Direction", ["long", "short"],
                                 index=0 if implied_long else 1)
        metal = c2.text_input("Metal", value=target.split("_")[0])
        horizon_days = c3.number_input("Horizon (days)", 5, 365, 60)
        c4, c5, c6 = st.columns(3)
        default_tgt = max(pt, last_mark * 1.05) if implied_long else min(pt, last_mark * 0.95)
        default_stop = last_mark * 0.97 if implied_long else last_mark * 1.03
        tgt_price = c4.number_input("Target", value=round(float(default_tgt), 2))
        stop_price = c5.number_input("Stop", value=round(float(default_stop), 2))
        confidence = c6.slider("Confidence", 0.05, 0.95, 0.55, step=0.05)
        thesis = st.text_area(
            "Thesis (min 20 chars)",
            value=(f"{'Long' if implied_long else 'Short'} {_label(target)} on the driver "
                   f"regression ({', '.join(_label(d) for d in drivers)}); "
                   "see Workbench decomposition + forecast."))
        submitted = st.form_submit_button("Log call →")
    if submitted:
        try:
            call = tcalls.new_call(
                instrument=target, expression="outright", metal=metal, direction=direction,
                target=float(tgt_price), stop=float(stop_price), horizon_days=int(horizon_days),
                confidence=float(confidence), thesis=thesis)
            st.success(f"Logged call `{call.call_id[:8]}` ({direction} {metal}). "
                       f"Regime at entry: {call.regime_at_entry or '—'}.")
        except Exception as e:  # noqa: BLE001 — surface the validation message
            st.error(f"Rejected: {e}")

    frame = tcalls.calls_frame()
    if not frame.empty:
        theme.title_block("Open & recent calls", "Append-only · newest first")
        cols = [c for c in ["call_id", "instrument", "direction", "status", "target", "stop",
                            "confidence", "pnl_R", "regime_at_entry"] if c in frame.columns]
        st.dataframe(frame[cols].head(15), use_container_width=True, hide_index=True)
    theme.source_line("Source: tracker.calls (append-only event log, hash-chained).")
