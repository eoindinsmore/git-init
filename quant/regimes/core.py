"""Rule-based regime identification (spec §7).

v1 is deliberately **rule-based, not estimated**: every historical classification is
auditable, there is no estimation instability, and the state definitions are transparent.
State variables (VIX band, PMI level × 3m delta, USD vs 200d, …) each map a series to a
category via a trailing (point-in-time) rule; the regime is their combination. An HMM
comparison is a later robustness exhibit, not a replacement.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Categorizers — each maps a series to a per-date category (point-in-time)
# --------------------------------------------------------------------------- #
def band(series: pd.Series, *, thresholds: list[float], labels: list[str]) -> pd.Series:
    """Bucket a level into ordered bands. ``len(labels) == len(thresholds) + 1``.

    e.g. VIX thresholds [15, 25] labels ['low','mid','high']."""
    if len(labels) != len(thresholds) + 1:
        raise ValueError("need one more label than thresholds")
    edges = [-np.inf, *thresholds, np.inf]
    cat = pd.cut(series, bins=edges, labels=labels, right=False)
    return cat.astype("object")


def ma_trend(series: pd.Series, *, window: int = 200,
             labels: tuple[str, str] = ("down", "up")) -> pd.Series:
    """Above/below a trailing moving average (e.g. price vs 200d)."""
    ma = series.rolling(window, min_periods=max(3, window // 2)).mean()
    out = pd.Series(np.where(series >= ma, labels[1], labels[0]), index=series.index)
    return out.where(ma.notna())


def level_delta(
    series: pd.Series,
    *,
    level_threshold: float = 50.0,
    delta_periods: int = 3,
) -> pd.Series:
    """Diffusion-style state: level vs threshold × sign of the k-period change.

    For PMI: >50 & rising / >50 & falling / <50 & rising / <50 & falling."""
    above = series >= level_threshold
    rising = series.diff(delta_periods) > 0
    lvl = np.where(above, "exp", "contr")
    mom = np.where(rising, "rising", "falling")
    out = pd.Series([f"{a}_{m}" for a, m in zip(lvl, mom, strict=True)], index=series.index)
    valid = series.diff(delta_periods).notna()
    return out.where(valid)


# --------------------------------------------------------------------------- #
# Classification + analysis
# --------------------------------------------------------------------------- #
def classify(state_categories: dict[str, pd.Series], *, sep: str = " | ") -> pd.Series:
    """Combine per-state category series into one dated regime-label series.

    Aligned on the union of dates; a date with any missing state is left NaN (we don't
    guess an incomplete regime). The label is ``name=cat`` joined by ``sep``."""
    if not state_categories:
        raise ValueError("no state categories provided")
    frame = pd.DataFrame(state_categories).sort_index()
    complete = frame.dropna(how="any")
    labels = complete.apply(
        lambda row: sep.join(f"{k}={row[k]}" for k in complete.columns), axis=1
    )
    return labels.reindex(frame.index)


def transition_matrix(regimes: pd.Series, *, normalize: bool = True) -> pd.DataFrame:
    """Regime-to-regime transition counts (or row-normalized probabilities)."""
    r = regimes.dropna()
    pairs = pd.DataFrame({"from": r.shift(1), "to": r}).dropna()
    mat = pd.crosstab(pairs["from"], pairs["to"])
    if normalize:
        mat = mat.div(mat.sum(axis=1).replace(0, np.nan), axis=0)
    return mat


def conditional_performance(
    regimes: pd.Series,
    asset_returns: pd.Series,
    *,
    periods_per_year: int = 252,
) -> pd.DataFrame:
    """Return distribution of an asset conditional on the regime (spec §7).

    The regime known at t is matched to the return from t to t+1 (no look-ahead). Reports
    mean/vol/Sharpe (annualised), hit rate and **sample size** per regime — small-n and
    overlapping-data caveats are the reader's to weigh; n is shown so they can."""
    r = regimes.shift(1)  # regime as known before the return is earned
    df = pd.concat([r.rename("regime"), asset_returns.rename("ret")], axis=1,
                   sort=True).dropna()
    rows = []
    for regime, grp in df.groupby("regime"):
        ret = grp["ret"]
        sd = ret.std(ddof=1)
        rows.append({
            "regime": regime,
            "n": len(ret),
            "mean_ann": ret.mean() * periods_per_year,
            "vol_ann": sd * np.sqrt(periods_per_year),
            "sharpe_ann": (ret.mean() / sd * np.sqrt(periods_per_year)) if sd > 0 else np.nan,
            "hit_rate": float((ret > 0).mean()),
        })
    return pd.DataFrame(rows).sort_values("sharpe_ann", ascending=False).reset_index(drop=True)
