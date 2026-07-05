"""Dislocation-scanner engine (spec §6).

Univariate: rolling z-scores of levels and of returns over several windows, plus
percentile rank vs own history. Multivariate: Mahalanobis distance of the latest
joint move vector — flags "this *combination* is unusual" even when no single series
is individually extreme. Output is a ranked table the app renders and the tracker
hook promotes from.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats as spstats

from quant import stats


def zscore_series(s: pd.Series, window: int) -> pd.Series:
    """Rolling z-score: (x − rolling_mean) / rolling_std over the trailing window."""
    s = s.astype(float)
    mean = s.rolling(window, min_periods=max(3, window // 2)).mean()
    std = s.rolling(window, min_periods=max(3, window // 2)).std(ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (s - mean) / std
    return z.replace([np.inf, -np.inf], np.nan)


def percentile_rank(s: pd.Series, window: int) -> pd.Series:
    """Rolling percentile rank (0–100) of each point within its trailing window."""
    s = s.astype(float)

    def _rank(x: np.ndarray) -> float:
        return 100.0 * (x < x[-1]).mean() + 50.0 * (x == x[-1]).mean() / len(x)

    return s.rolling(window, min_periods=max(3, window // 2)).apply(_rank, raw=True)


def build_derived(levels: dict[str, pd.Series], derived) -> dict[str, pd.Series]:
    """Construct declared ratio/spread series from raw level series (aligned)."""
    out: dict[str, pd.Series] = {}
    for d in derived:
        a_id, b_id = d.legs
        if a_id not in levels or b_id not in levels:
            continue  # a leg is missing; skip loudly-ish (caller reports coverage)
        a, b = levels[a_id].align(levels[b_id], join="inner")
        if d.kind == "ratio":
            with np.errstate(divide="ignore", invalid="ignore"):
                s = (a / b).replace([np.inf, -np.inf], np.nan)
        elif d.kind == "spread":
            s = a - b
        else:
            raise ValueError(f"derived '{d.id}': unknown kind {d.kind!r}")
        out[d.id] = s.dropna()
    return out


@dataclass(frozen=True)
class ScanResult:
    table: pd.DataFrame = field(repr=False)  # one row per item, ranked by |z|
    mahalanobis: float | None  # joint dislocation distance for the latest move
    mahalanobis_pvalue: float | None  # chi-square tail prob (df = set size)
    mahalanobis_set: list[str] = field(default_factory=list)
    as_of: pd.Timestamp | None = None
    coverage: dict[str, int] = field(default_factory=dict)  # item -> obs available


def _returns(s: pd.Series) -> pd.Series:
    return s.astype(float).pct_change()


def scan(
    levels: dict[str, pd.Series],
    *,
    windows: list[int],
    z_threshold: float = 2.0,
    mahalanobis_set: list[str] | None = None,
) -> ScanResult:
    """Run the screen over a dict of item_id → level series.

    For each item computes, at its latest observation: level z-scores and return
    z-scores over each window, and a percentile rank over the longest window. The
    headline ``abs_z`` is the max magnitude across those. ``new_flag`` marks items
    that crossed ``z_threshold`` at the latest step (were below at the prior step).
    """
    windows = sorted(windows)
    rows = []
    coverage = {}
    for item, s in levels.items():
        s = s.dropna().sort_index()
        coverage[item] = len(s)
        if len(s) < max(6, windows[0]):
            continue
        rets = _returns(s)
        row = {"item": item, "value": float(s.iloc[-1]), "date": s.index[-1]}
        zvals = []
        crossed_now = crossed_prev = False
        for w in windows:
            zl = zscore_series(s, w)
            zr = zscore_series(rets, w)
            row[f"z_level_{w}"] = float(zl.iloc[-1]) if pd.notna(zl.iloc[-1]) else np.nan
            row[f"z_ret_{w}"] = float(zr.iloc[-1]) if pd.notna(zr.iloc[-1]) else np.nan
            for zser in (zl, zr):
                if pd.notna(zser.iloc[-1]):
                    zvals.append(abs(float(zser.iloc[-1])))
                    if abs(float(zser.iloc[-1])) >= z_threshold:
                        crossed_now = True
                    if len(zser) >= 2 and pd.notna(zser.iloc[-2]) and abs(
                        float(zser.iloc[-2])
                    ) >= z_threshold:
                        crossed_prev = True
        row[f"pct_rank_{windows[-1]}"] = float(
            percentile_rank(s, windows[-1]).iloc[-1]
        ) if len(s) >= windows[-1] else np.nan
        row["abs_z"] = max(zvals) if zvals else np.nan
        row["flag"] = bool(crossed_now)
        row["new_flag"] = bool(crossed_now and not crossed_prev)
        rows.append(row)

    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values("abs_z", ascending=False, na_position="last").reset_index(
            drop=True
        )

    mahal, pval = _mahalanobis_scan(levels, mahalanobis_set)
    as_of = table["date"].max() if not table.empty else None
    return ScanResult(
        table=table,
        mahalanobis=mahal,
        mahalanobis_pvalue=pval,
        mahalanobis_set=list(mahalanobis_set or []),
        as_of=as_of,
        coverage=coverage,
    )


def mahalanobis_timeseries(
    levels: dict[str, pd.Series],
    mahalanobis_set: list[str],
    *,
    window: int = 104,
) -> pd.Series:
    """Rolling joint-dislocation distance over time (the multivariate screen as a chart).

    For each date from ``window`` onward, the Mahalanobis distance of that date's joint
    return vector vs the mean/covariance of the **trailing ``window``** observations. A
    spike marks a date on which the *combination* of moves was unusual even if no single
    series was individually extreme. Empty when fewer than two series or too little history.
    """
    cols = {m: _returns(levels[m]) for m in mahalanobis_set if m in levels}
    if len(cols) < 2:
        return pd.Series(dtype=float)
    panel = pd.DataFrame(cols).dropna()
    if len(panel) < window + 2:
        return pd.Series(dtype=float)
    arr = panel.to_numpy()
    out: dict = {}
    for i in range(window, len(panel)):
        hist = arr[i - window : i]
        d = stats.mahalanobis(arr[i], hist.mean(axis=0), np.cov(hist, rowvar=False))
        out[panel.index[i]] = d
    return pd.Series(out, name="mahalanobis")


def _mahalanobis_scan(levels, mahalanobis_set) -> tuple[float | None, float | None]:
    if not mahalanobis_set:
        return None, None
    cols = {m: _returns(levels[m]) for m in mahalanobis_set if m in levels}
    if len(cols) < 2:
        return None, None
    panel = pd.DataFrame(cols).dropna()
    if len(panel) < len(cols) + 5:
        return None, None
    latest = panel.iloc[-1].to_numpy()
    hist = panel.iloc[:-1]
    d = stats.mahalanobis(latest, hist.mean().to_numpy(), np.cov(hist.to_numpy(), rowvar=False))
    # Under joint normality, d^2 ~ chi-square with df = number of series.
    pval = float(spstats.chi2.sf(d**2, df=panel.shape[1]))
    return float(d), pval
