"""Composite-indicator engine (spec §5) — aggregate many series into one.

Three methods: diffusion index (% of components improving), coverage-weighted
z-score average, and the first principal component. The PCA is the delicate one:
**loadings are estimated point-in-time only** (expanding or rolling window ending at
each date), **sign-fixed** against a declared reference series, and **ragged edges**
(missing components on a date) are handled by reweighting onto the available
components. Full-sample PCA is look-ahead and is forbidden here (spec §5).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA


def diffusion_index(panel: pd.DataFrame) -> pd.Series:
    """Share of components improving (positive change) at each date, in [0, 100].

    Uses each component's own period-over-period change; components missing on a date
    are excluded from that date's denominator (ragged-edge safe)."""
    changes = panel.sort_index().diff()
    improving = (changes > 0).sum(axis=1)
    available = changes.notna().sum(axis=1)
    with np.errstate(invalid="ignore"):
        di = 100.0 * improving / available
    return di.where(available > 0)


def zscore_composite(
    panel: pd.DataFrame,
    *,
    window: int | None = None,
    weights: dict[str, float] | None = None,
) -> pd.Series:
    """Coverage-weighted average of per-component z-scores.

    Each component is z-scored (full-sample if ``window`` is None, else rolling — the
    rolling form is the point-in-time-safe choice). The composite at each date is the
    weighted mean over **available** components only, so ragged edges don't bias it.
    """
    panel = panel.sort_index()
    if window is None:
        z = (panel - panel.mean()) / panel.std(ddof=0)
    else:
        mean = panel.rolling(window, min_periods=max(3, window // 2)).mean()
        std = panel.rolling(window, min_periods=max(3, window // 2)).std(ddof=0)
        z = (panel - mean) / std.replace(0, np.nan)
    z = z.replace([np.inf, -np.inf], np.nan)

    if weights:
        w = pd.Series({c: weights.get(c, 0.0) for c in panel.columns}, dtype=float)
    else:
        w = pd.Series(1.0, index=panel.columns)
    # Weighted mean over available (non-NaN) components per date.
    mask = z.notna()
    wmat = mask.mul(w, axis=1)
    num = (z.fillna(0.0) * wmat).sum(axis=1)
    den = wmat.sum(axis=1)
    return (num / den.replace(0, np.nan)).dropna()


def pit_pca_first_component(
    panel: pd.DataFrame,
    *,
    reference: str,
    min_window: int,
    expanding: bool = True,
) -> pd.Series:
    """First-PC composite with **point-in-time** loadings (no look-ahead).

    For each date t, PCA is fitted on the window of history *ending at t* (expanding
    from ``min_window``, or a trailing window of ``min_window`` if ``expanding=False``),
    on the components standardized by that window's own mean/std. The first-component
    sign is fixed so it loads positively on ``reference``. The score at t is the latest
    standardized observation projected onto the loadings, reweighted onto whatever
    components are available at t (ragged-edge handling). Returns the composite series.
    """
    panel = panel.sort_index()
    n = len(panel)
    scores = pd.Series(index=panel.index, dtype=float)

    for i in range(min_window, n + 1):
        window = panel.iloc[:i] if expanding else panel.iloc[i - min_window : i]
        w = window.dropna(axis=1, how="all")
        if w.shape[1] < 1:
            continue
        mu = w.mean()
        sd = w.std(ddof=0).replace(0, np.nan)
        wz = (w - mu) / sd
        train = wz.dropna(axis=0, how="any")
        if train.shape[0] < 3 or train.shape[1] < 1:
            continue

        comp_cols = list(train.columns)
        load = PCA(n_components=1).fit(train.to_numpy()).components_[0]

        # Sign fix: positive loading on the reference (fallback: positive net loading).
        if reference in comp_cols:
            if load[comp_cols.index(reference)] < 0:
                load = -load
        elif load.sum() < 0:
            load = -load

        latest = wz.iloc[-1]
        avail = [c for c in comp_cols if pd.notna(latest[c])]
        if not avail:
            continue
        lvec = np.array([load[comp_cols.index(c)] for c in avail])
        norm = np.linalg.norm(lvec)
        if norm == 0:
            continue
        lvec = lvec / norm  # reweight onto available components
        scores.iloc[i - 1] = float(np.dot(latest[avail].to_numpy(), lvec))

    return scores.dropna()
