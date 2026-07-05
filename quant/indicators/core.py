"""Leading-indicator lab — find AND honestly validate leading indicators (spec §1).

Five sequential gates; a candidate must pass **all** to be promoted:

1. Scan        — lead-lag HAC regression of candidate(t−k) on target(t), k=0..K,
                 on a training window only.
2. FDR         — Benjamini–Hochberg across the whole candidate×lag grid. Raw
                 t-stats never promote; q-values do.
3. OOS         — walk-forward predictive regression on the holdout; require a
                 positive Campbell–Thompson OOS R² vs the prevailing-mean benchmark.
4. Economic    — a simple signal→position rule must beat the benchmark net of
                 assumed costs. (Lightweight P&L here; replaced by the real
                 backtester in Phase 5 — see indicators.economic.)
5. Stability   — rolling-window beta sign-flip check.

Promoted candidates become Signals with scorecards; **rejected candidates get a
scorecard too** — the graveyard (docs/scorecards/rejected/) is the credibility story.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant import stats


# --------------------------------------------------------------------------- #
# Gate 1 — lead-lag scan
# --------------------------------------------------------------------------- #
def lead_lag_scan(
    target: pd.Series,
    candidate: pd.Series,
    *,
    max_lag: int,
    add_const: bool = True,
) -> pd.DataFrame:
    """Regress ``target(t)`` on ``candidate(t−k)`` for k = 0..max_lag (HAC errors).

    Returns a frame indexed by ``lag`` with columns ``beta``, ``t_hac``, ``pvalue``,
    ``rsquared``, ``nobs``. A positive lag means the candidate *leads* the target.
    """
    rows = []
    for k in range(max_lag + 1):
        shifted = candidate.shift(k)
        df = pd.concat([target.rename("y"), shifted.rename("x")], axis=1).dropna()
        if len(df) < 10:
            rows.append({"lag": k, "beta": np.nan, "t_hac": np.nan,
                         "pvalue": np.nan, "rsquared": np.nan, "nobs": len(df)})
            continue
        res = stats.ols_hac(df["y"], df["x"], add_const=add_const)
        rows.append({
            "lag": k,
            "beta": float(res.params.get("x", np.nan)),
            "t_hac": float(res.tvalues.get("x", np.nan)),
            "pvalue": float(res.pvalues.get("x", np.nan)),
            "rsquared": res.rsquared,
            "nobs": res.nobs,
        })
    return pd.DataFrame(rows).set_index("lag")


# --------------------------------------------------------------------------- #
# Gate 3 — out-of-sample confirmation
# --------------------------------------------------------------------------- #
def oos_confirm(
    target: pd.Series,
    candidate: pd.Series,
    *,
    lag: int,
    min_train: int,
    test_size: int = 1,
) -> dict:
    """Walk-forward predictive regression on a holdout vs the prevailing-mean benchmark.

    At each split, fit ``target ~ candidate(lag)`` on the training window, predict the
    test block, and compare to the benchmark forecast (the training-window mean of the
    target). Returns Campbell–Thompson OOS R² and the forecast/benchmark/actual series.
    """
    df = pd.concat(
        [target.rename("y"), candidate.shift(lag).rename("x")], axis=1
    ).dropna()
    if len(df) <= min_train + test_size:
        return {"oos_r2": np.nan, "n_test": 0, "actual": pd.Series(dtype=float),
                "forecast": pd.Series(dtype=float), "benchmark": pd.Series(dtype=float)}

    actual, forecast, benchmark = [], [], []
    idx_used = []
    for train_idx, test_idx in stats.walk_forward_splits(
        df.index, min_train=min_train, test_size=test_size, expanding=True
    ):
        tr = df.loc[train_idx]
        if tr["x"].std(ddof=1) == 0 or len(tr) < 5:
            continue
        res = stats.ols_hac(tr["y"], tr["x"])
        a = float(res.params.get("const", 0.0))
        b = float(res.params.get("x", 0.0))
        for t in test_idx:
            forecast.append(a + b * df.loc[t, "x"])
            benchmark.append(float(tr["y"].mean()))
            actual.append(float(df.loc[t, "y"]))
            idx_used.append(t)

    if not actual:
        return {"oos_r2": np.nan, "n_test": 0, "actual": pd.Series(dtype=float),
                "forecast": pd.Series(dtype=float), "benchmark": pd.Series(dtype=float)}
    a_s = pd.Series(actual, index=idx_used)
    f_s = pd.Series(forecast, index=idx_used)
    b_s = pd.Series(benchmark, index=idx_used)
    oos_r2 = stats.campbell_thompson_oos_r2(a_s, f_s, b_s)
    return {"oos_r2": oos_r2, "n_test": len(a_s), "actual": a_s,
            "forecast": f_s, "benchmark": b_s}


# --------------------------------------------------------------------------- #
# Gate 4 — economic significance (lightweight; Phase-5 backtester replaces this)
# --------------------------------------------------------------------------- #
def economic_significance(
    target: pd.Series,
    candidate: pd.Series,
    *,
    lag: int,
    beta_sign: float,
    cost_per_turnover: float = 0.0,
    z_window: int = 52,
) -> dict:
    """A simple z-scored signal→position rule; returns net Sharpe and mean P&L.

    STUB: intentionally minimal. Phase 5's backtester (vol-targeted sizing, proper
    cost model, deflated Sharpe) supersedes this; the indicator lab will call it
    then. Here we only need a coarse "does trading it make money net of costs?".
    """
    x = candidate.shift(lag)
    z = (x - x.rolling(z_window, min_periods=z_window // 2).mean()) / x.rolling(
        z_window, min_periods=z_window // 2
    ).std(ddof=1)
    position = np.sign(beta_sign) * z.clip(-2, 2)
    df = pd.concat([target.rename("y"), position.rename("pos")], axis=1).dropna()
    if len(df) < 10:
        return {"sharpe_net": np.nan, "mean_pnl_net": np.nan, "n": len(df)}
    turnover = df["pos"].diff().abs().fillna(0.0)
    pnl = df["pos"] * df["y"] - cost_per_turnover * turnover
    sd = pnl.std(ddof=1)
    sharpe = float(pnl.mean() / sd) if sd > 0 else np.nan
    return {"sharpe_net": sharpe, "mean_pnl_net": float(pnl.mean()), "n": len(df)}


# --------------------------------------------------------------------------- #
# Gate 5 — stability
# --------------------------------------------------------------------------- #
def stability(target: pd.Series, candidate: pd.Series, *, lag: int, window: int) -> dict:
    """Rolling-beta sign-flip check. Returns flip count and the dominant-sign share."""
    df = pd.concat(
        [target.rename("y"), candidate.shift(lag).rename("x")], axis=1
    ).dropna()
    if len(df) < window + 2:
        return {"sign_flips": np.nan, "dominant_share": np.nan}
    betas = stats.rolling_ols(df["y"], df["x"], window=window)["x"].dropna()
    if betas.empty:
        return {"sign_flips": np.nan, "dominant_share": np.nan}
    signs = np.sign(betas)
    flips = int((signs.diff().fillna(0) != 0).sum())
    dominant = float(max((signs > 0).mean(), (signs < 0).mean()))
    return {"sign_flips": flips, "dominant_share": dominant}


@dataclass(frozen=True)
class GateOutcome:
    passed: bool
    detail: dict = field(default_factory=dict)
