"""Price-decomposition engine (spec §4) — "why did the price move".

Target returns are regressed on a declared driver set; the residual is explicitly
labelled unexplained/idiosyncratic. Correlated regressors are handled by
**sequential economic orthogonalization** in the spec's declared order (the
default policy): driver *k* is replaced by the part of it not already explained by
drivers 1..k-1, so contributions are additive and don't double-count shared
variation. The order is a modelling choice and is carried on the result so it can
be stated on the chart.

Returns are log by default so contributions sum exactly to the total log price
change over any window (ln P_b − ln P_a).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant import stats

DRIFT = "drift (const)"
RESIDUAL = "unexplained"

# Map registry/spec frequency codes (D/W/M/Q/A) to pandas 2.2 offset aliases.
# pandas 2.2 deprecated the bare 'M'/'Q'/'A' period aliases for resampling.
_PANDAS_FREQ = {"D": "D", "W": "W", "M": "ME", "Q": "QE", "A": "YE"}


def _resample_freq(code: str) -> str:
    """Accept either a registry code (M/Q/A) or a raw pandas alias (ME/W/D)."""
    return _PANDAS_FREQ.get(code, code)


@dataclass(frozen=True)
class DecompResult:
    betas: pd.Series  # coefficients on orthogonalized drivers (index incl. 'const')
    hac_se: pd.Series
    tvalues: pd.Series
    rsquared: float
    nobs: int
    order: list[str]  # driver series_ids in orthogonalization order
    contributions: pd.Series = field(repr=False)  # per driver + DRIFT, over the window
    residual: float = 0.0  # actual - sum(contributions)
    actual: float = 0.0  # total target return over the window
    window: tuple[pd.Timestamp, pd.Timestamp] | None = None
    rolling_betas: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    sign_flips: dict[str, int] = field(default_factory=dict)


def to_returns(levels: pd.Series, kind: str = "log") -> pd.Series:
    """Period returns from a level series. ``log`` returns are additive over windows."""
    levels = levels.astype(float)
    if kind == "log":
        return np.log(levels).diff()
    if kind == "pct":
        return levels.pct_change()
    raise ValueError("return_kind must be 'log' or 'pct'")


def orthogonalize(drivers: pd.DataFrame, order: list[str]) -> pd.DataFrame:
    """Sequential (Gram–Schmidt-style) residualization of ``drivers`` in ``order``.

    ``z_1 = x_1``; ``z_k`` = residual of ``x_k`` regressed on ``z_1..z_{k-1}`` (with
    an intercept). Estimated on the fully-aligned non-NaN sample. The returned frame
    has the same columns/index; the first driver is unchanged, later ones carry only
    their orthogonal (marginal) variation.
    """
    order = [c for c in order if c in drivers.columns]
    aligned = drivers[order].dropna()
    z = pd.DataFrame(index=aligned.index)
    for i, name in enumerate(order):
        x = aligned[name]
        if i == 0:
            z[name] = x
            continue
        prior = z[order[:i]]
        design = np.column_stack([np.ones(len(prior)), prior.to_numpy()])
        beta, *_ = np.linalg.lstsq(design, x.to_numpy(), rcond=None)
        z[name] = x.to_numpy() - design @ beta
    return z.reindex(drivers.index)


def _window_slice(returns: pd.Series, window: tuple | None) -> pd.Series:
    if window is None:
        return returns
    a, b = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    return returns[(returns.index >= a) & (returns.index <= b)]


def decompose(
    target_levels: pd.Series,
    driver_levels: dict[str, pd.Series],
    *,
    order: list[str],
    frequency: str = "W",
    return_kind: str = "log",
    est_window: int = 104,
    window: tuple | None = None,
) -> DecompResult:
    """Attribute a target's price change to its drivers over ``window``.

    ``target_levels`` / ``driver_levels`` are date-indexed level series (already
    point-in-time — fetch them via :func:`quant.pit.get_series_asof`). They are
    resampled to ``frequency`` (last obs), converted to returns, the drivers
    orthogonalized in ``order``, and a HAC-robust OLS fitted over the **trailing
    ``est_window``** observations. Contributions over ``window`` (default: the whole
    estimation sample) are ``beta_i * sum(z_i)``; the intercept becomes a
    ``DRIFT`` contribution and the leftover is ``RESIDUAL`` — so
    ``actual == sum(contributions) + residual`` exactly.
    """
    order = [c for c in order if c in driver_levels]
    if not order:
        raise ValueError("no drivers available to decompose against")

    # Resample to a common frequency and build the returns panel.
    freq = _resample_freq(frequency)
    tgt = target_levels.astype(float).resample(freq).last()
    y = to_returns(tgt, return_kind).rename("__target__")
    cols = {name: to_returns(driver_levels[name].astype(float).resample(freq).last(),
                             return_kind) for name in order}
    drivers_ret = pd.DataFrame(cols)

    z = orthogonalize(drivers_ret, order)
    panel = pd.concat([y, z], axis=1).dropna()
    if len(panel) < len(order) + 2:
        raise ValueError(
            f"not enough overlapping observations ({len(panel)}) to fit {len(order)} drivers"
        )

    # Trailing estimation window.
    est = panel.iloc[-est_window:] if est_window and len(panel) > est_window else panel
    yv = est["__target__"]
    Xv = est[order]
    res = stats.ols_hac(yv, Xv)

    # Contributions over the display window (default = estimation sample span).
    disp = _window_slice(z.loc[est.index], window)
    n = len(disp)
    contributions: dict[str, float] = {}
    const = float(res.params.get("const", 0.0))
    contributions[DRIFT] = const * n
    for name in order:
        beta = float(res.params.get(name, 0.0))
        contributions[name] = beta * float(disp[name].sum())

    actual = float(_window_slice(yv, window).sum())
    residual = actual - sum(contributions.values())
    contributions[RESIDUAL] = residual

    # Rolling betas (stability) on the orthogonalized drivers + sign-flip counts.
    roll = stats.rolling_ols(panel["__target__"], panel[order], window=est_window)
    sign_flips = {}
    for name in order:
        if name in roll.columns:
            s = np.sign(roll[name].dropna())
            sign_flips[name] = int((s.diff().fillna(0) != 0).sum())

    span = (disp.index.min(), disp.index.max()) if n else None
    return DecompResult(
        betas=res.params,
        hac_se=res.hac_se,
        tvalues=res.tvalues,
        rsquared=res.rsquared,
        nobs=res.nobs,
        order=order,
        contributions=pd.Series(contributions),
        residual=residual,
        actual=actual,
        window=span,
        rolling_betas=roll,
        sign_flips=sign_flips,
    )
