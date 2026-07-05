"""Shared statistics core — the correct, tested math every quant module reuses.

Design rule (spec + CLAUDE.md §Quant toolkit): overlapping returns are the norm,
so OLS with **Newey–West HAC** standard errors is the *default*, not an option.
Multiple-testing discipline (Benjamini–Hochberg FDR) and honest out-of-sample
evaluation (Campbell–Thompson, Diebold–Mariano) live here too, so no downstream
module re-implements them subtly differently.

We lean on ``statsmodels`` / ``scipy`` (BSD-3, charter-compliant) for the
numerically fragile pieces rather than hand-rolling them.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats


# --------------------------------------------------------------------------- #
# OLS with HAC (Newey–West) errors
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OLSResult:
    """Result of a HAC-robust OLS fit. ``params``/``tvalues`` etc. are indexed by
    regressor name (``const`` first when an intercept is added)."""

    params: pd.Series
    hac_se: pd.Series
    tvalues: pd.Series
    pvalues: pd.Series
    rsquared: float
    nobs: int
    maxlags: int
    resid: pd.Series = field(repr=False)


def _hac_maxlags(n: int) -> int:
    """Default Newey–West bandwidth: the common ``floor(4*(n/100)^(2/9))`` rule."""
    return int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))


def ols_hac(
    y: pd.Series,
    X: pd.DataFrame | pd.Series,
    *,
    maxlags: int | None = None,
    add_const: bool = True,
) -> OLSResult:
    """OLS of ``y`` on ``X`` with Newey–West HAC standard errors.

    Rows with any NaN in ``y`` or ``X`` are dropped pairwise (aligned on index
    first). ``maxlags`` defaults to the ``floor(4*(n/100)^(2/9))`` rule. Raises
    ``ValueError`` if fewer observations than regressors remain.
    """
    X = X.to_frame() if isinstance(X, pd.Series) else X
    df = pd.concat([y.rename("__y__"), X], axis=1).dropna()
    if df.empty:
        raise ValueError("no overlapping non-NaN observations between y and X")
    yv = df["__y__"]
    Xv = df.drop(columns="__y__")
    if add_const:
        Xv = sm.add_constant(Xv, has_constant="add")
    if len(df) <= Xv.shape[1]:
        raise ValueError(f"need more observations ({len(df)}) than regressors ({Xv.shape[1]})")

    lags = _hac_maxlags(len(df)) if maxlags is None else maxlags
    fit = sm.OLS(yv.to_numpy(), Xv.to_numpy()).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags, "use_correction": True}
    )
    names = list(Xv.columns)
    idx = pd.Index(names)
    resid = pd.Series(fit.resid, index=df.index, name="resid")
    return OLSResult(
        params=pd.Series(fit.params, index=idx),
        hac_se=pd.Series(fit.bse, index=idx),
        tvalues=pd.Series(fit.tvalues, index=idx),
        pvalues=pd.Series(fit.pvalues, index=idx),
        rsquared=float(fit.rsquared),
        nobs=int(fit.nobs),
        maxlags=lags,
        resid=resid,
    )


def rolling_ols(
    y: pd.Series,
    X: pd.DataFrame | pd.Series,
    *,
    window: int,
    add_const: bool = True,
) -> pd.DataFrame:
    """Rolling-window OLS betas — a time series of coefficients (one row per date).

    Plain (non-HAC) betas: this is for *stability* inspection (do signs flip?),
    not inference. Each row is the fit over the trailing ``window`` observations
    ending at that date; the first ``window-1`` rows are NaN. Columns are the
    regressor names (incl. ``const``).
    """
    X = X.to_frame() if isinstance(X, pd.Series) else X
    df = pd.concat([y.rename("__y__"), X], axis=1)
    cols = (["const"] if add_const else []) + list(X.columns)
    out = pd.DataFrame(index=df.index, columns=cols, dtype=float)
    for i in range(window - 1, len(df)):
        chunk = df.iloc[i - window + 1 : i + 1].dropna()
        if len(chunk) <= len(cols):
            continue
        yv = chunk["__y__"]
        Xv = chunk.drop(columns="__y__")
        if add_const:
            Xv = sm.add_constant(Xv, has_constant="add")
        beta = np.linalg.lstsq(Xv.to_numpy(), yv.to_numpy(), rcond=None)[0]
        out.iloc[i] = beta
    return out


# --------------------------------------------------------------------------- #
# Multiple-testing control
# --------------------------------------------------------------------------- #
def benjamini_hochberg(pvalues: pd.Series, q: float = 0.10) -> pd.DataFrame:
    """Benjamini–Hochberg FDR control across a family of tests.

    Returns a frame aligned to ``pvalues.index`` with columns ``pvalue``,
    ``qvalue`` (BH-adjusted, monotone) and ``reject`` (bool at level ``q``). The
    indicator lab runs this across the whole candidate×lag grid — raw t-stats
    never promote an indicator on their own (spec §1).
    """
    if not 0 < q < 1:
        raise ValueError("q must be in (0, 1)")
    p = pd.to_numeric(pvalues, errors="coerce")
    valid = p.dropna().sort_values()
    m = len(valid)
    if m == 0:
        return pd.DataFrame({"pvalue": p, "qvalue": np.nan, "reject": False})

    ranks = np.arange(1, m + 1)
    # BH-adjusted q-values: enforce monotonicity from the largest p downward.
    raw_q = valid.to_numpy() * m / ranks
    qvals = np.minimum.accumulate(raw_q[::-1])[::-1].clip(max=1.0)
    qseries = pd.Series(qvals, index=valid.index)

    # Reject the k smallest where p(k) <= (k/m) q; reject all ranks up to the max such k.
    below = valid.to_numpy() <= (ranks / m) * q
    kmax = np.max(np.where(below)[0]) + 1 if below.any() else 0
    reject_idx = set(valid.index[:kmax])

    out = pd.DataFrame(index=p.index)
    out["pvalue"] = p
    out["qvalue"] = qseries.reindex(p.index)
    out["reject"] = [idx in reject_idx for idx in p.index]
    return out


# --------------------------------------------------------------------------- #
# Out-of-sample evaluation
# --------------------------------------------------------------------------- #
def campbell_thompson_oos_r2(actual: pd.Series, forecast: pd.Series, benchmark: pd.Series) -> float:
    """Out-of-sample R^2 vs a benchmark forecast (Campbell–Thompson 2008).

    ``1 - SSE(forecast)/SSE(benchmark)``. Positive means the forecast beats the
    benchmark (e.g. the prevailing mean / no-indicator model) out of sample.
    """
    df = pd.concat(
        [actual.rename("a"), forecast.rename("f"), benchmark.rename("b")], axis=1
    ).dropna()
    if df.empty:
        raise ValueError("no overlapping observations")
    sse_f = float(((df["a"] - df["f"]) ** 2).sum())
    sse_b = float(((df["a"] - df["b"]) ** 2).sum())
    if sse_b == 0:
        raise ValueError("benchmark SSE is zero; R^2 undefined")
    return 1.0 - sse_f / sse_b


def diebold_mariano(
    actual: pd.Series,
    f1: pd.Series,
    f2: pd.Series,
    *,
    h: int = 1,
    loss: str = "mse",
) -> tuple[float, float]:
    """Diebold–Mariano test that ``f1`` and ``f2`` have equal forecast accuracy.

    Returns ``(dm_stat, pvalue)`` two-sided. Negative ``dm_stat`` favours ``f1``
    (lower loss). Uses the Harvey–Leybourne–Newbold small-sample correction and a
    ``t(n-1)`` reference distribution. ``loss`` is ``"mse"`` or ``"mae"``.
    """
    df = pd.concat(
        [actual.rename("a"), f1.rename("f1"), f2.rename("f2")], axis=1
    ).dropna()
    n = len(df)
    if n < 3:
        raise ValueError("need at least 3 overlapping observations")
    e1 = df["a"] - df["f1"]
    e2 = df["a"] - df["f2"]
    if loss == "mse":
        d = e1**2 - e2**2
    elif loss == "mae":
        d = e1.abs() - e2.abs()
    else:
        raise ValueError("loss must be 'mse' or 'mae'")

    dbar = float(d.mean())
    # Long-run variance of d with (h-1) autocovariances.
    gamma0 = float(((d - dbar) ** 2).mean())
    lrv = gamma0
    for k in range(1, h):
        cov = float(((d.iloc[k:].to_numpy() - dbar) * (d.iloc[:-k].to_numpy() - dbar)).mean())
        lrv += 2 * cov
    if lrv <= 0:
        raise ValueError("non-positive long-run variance; cannot form DM statistic")
    dm = dbar / np.sqrt(lrv / n)
    # Harvey–Leybourne–Newbold correction.
    corr = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_hln = dm * corr
    pval = 2 * float(stats.t.sf(abs(dm_hln), df=n - 1))
    return dm_hln, pval


# --------------------------------------------------------------------------- #
# Backtest honesty
# --------------------------------------------------------------------------- #
def block_bootstrap_pvalue(
    returns: pd.Series,
    *,
    block: int = 20,
    n_boot: int = 2000,
    seed: int = 0,
) -> float:
    """One-sided bootstrap p-value that mean(returns) <= 0.

    Circular block bootstrap (block length ``block``) preserves autocorrelation in
    strategy returns. Returns the fraction of resampled means <= 0 — small means
    the positive mean is unlikely to be luck. Deterministic given ``seed`` (tests
    and reproducibility; no ``Math.random`` surprises).
    """
    r = pd.to_numeric(returns, errors="coerce").dropna().to_numpy()
    n = len(r)
    if n < block:
        raise ValueError(f"series shorter ({n}) than block length ({block})")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    obs_mean = r.mean()
    if obs_mean <= 0:
        return 1.0
    count = 0
    for _ in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel() % n
        sample = r[idx[:n]]
        if sample.mean() <= 0:
            count += 1
    return count / n_boot


def deflated_sharpe(
    sharpe: float,
    *,
    n_obs: int,
    n_trials: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Deflated Sharpe ratio (Bailey–López de Prado): P(true SR > 0) after adjusting
    for the number of strategy variants tried.

    ``sharpe`` is the (per-observation) realised SR. Multiple testing inflates the
    best observed SR, so the benchmark it must beat rises with ``n_trials``. Returns
    a probability in [0, 1]; low values mean the SR is likely a multiple-testing
    artifact. Records why ``n_variants_tried`` belongs on the scorecard (spec §3).
    """
    if n_obs < 2:
        raise ValueError("need n_obs >= 2")
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    # Expected maximum of n_trials standard normals (variance of SR estimates ~1).
    euler = 0.5772156649
    e_max = (1 - euler) * stats.norm.ppf(1 - 1.0 / n_trials) + euler * stats.norm.ppf(
        1 - 1.0 / (n_trials * np.e)
    )
    sr0 = e_max  # deflated benchmark SR (variance of trial SRs assumed ~1)
    # Standard error of the SR estimator under non-normal returns.
    denom = np.sqrt(1 - skew * sharpe + (kurtosis - 1) / 4.0 * sharpe**2)
    if denom <= 0:
        return float("nan")
    z = (sharpe - sr0) * np.sqrt(n_obs - 1) / denom
    return float(stats.norm.cdf(z))


# --------------------------------------------------------------------------- #
# Multivariate dislocation
# --------------------------------------------------------------------------- #
def mahalanobis(vec: np.ndarray, mean: np.ndarray, cov: np.ndarray) -> float:
    """Mahalanobis distance of ``vec`` from ``mean`` given covariance ``cov``.

    The scanner's multivariate flag: how unusual is *today's* joint move, even when
    no single series is individually extreme (spec §6). Uses a pseudo-inverse so a
    near-singular covariance degrades gracefully rather than raising.
    """
    vec = np.asarray(vec, dtype=float)
    mean = np.asarray(mean, dtype=float)
    delta = vec - mean
    vi = np.linalg.pinv(np.asarray(cov, dtype=float))
    d2 = float(delta @ vi @ delta)
    return float(np.sqrt(max(d2, 0.0)))


# --------------------------------------------------------------------------- #
# Walk-forward splits
# --------------------------------------------------------------------------- #
def walk_forward_splits(
    index: pd.Index,
    *,
    min_train: int,
    test_size: int = 1,
    expanding: bool = True,
) -> Iterator[tuple[pd.Index, pd.Index]]:
    """Yield ``(train_index, test_index)`` pairs for point-in-time evaluation.

    ``expanding=True`` grows the training window (anchored); ``False`` uses a
    rolling window of ``min_train``. Every split's test block is strictly *after*
    its train block — no look-ahead. Used by the indicator lab (OOS gate) and the
    backtester.
    """
    n = len(index)
    if min_train < 1 or test_size < 1:
        raise ValueError("min_train and test_size must be >= 1")
    start = min_train
    while start < n:
        stop = min(start + test_size, n)
        train = index[start - min_train : start] if not expanding else index[:start]
        test = index[start:stop]
        yield train, test
        start = stop
