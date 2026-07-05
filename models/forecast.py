"""Short-term price forecast from the driver regression (spec: forecast_model).

Given the fitted driver→target relationship and an assumption about where the drivers
go, project the target forward with an honest uncertainty band. Step 4 of the Analysis
Workbench.

**Design note / deviation from the draft spec (logged for review):** the forecast fits a
plain OLS of target returns on the *raw* (non-orthogonalized) driver returns — "total"
betas — rather than reusing the decomposition's orthogonalized betas. This is deliberate
and statistically correct: forecasting needs the marginal effect of an *observable*
driver move (``dy/dx_k``), whereas the decomposition uses orthogonalized betas so its
contributions are additive. Same data, same window as the decomposition, so the two stay
consistent; only the coefficient basis differs, and it is stated on every output.

**Hard boundary (tracker spec §6):** model forecasts are NOT trade calls. This module
writes nothing to the tracker; a human call may cite a forecast, but the human owns it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats as spstats

from quant import stats
from quant.decomp.core import _resample_freq, to_returns

HOLD_LAST = "hold_last"
MOMENTUM = "momentum"
SCENARIO = "scenario"
ASSUMPTIONS = frozenset({HOLD_LAST, MOMENTUM, SCENARIO})


@dataclass(frozen=True)
class Forecast:
    """A short-horizon forecast path with an uncertainty band, in level units.

    ``path`` is indexed by future date with columns ``[point, lo, hi]``. ``notes`` carries
    the caveats stamped on every output (assumption used, interval understatement, etc.)."""

    path: pd.DataFrame = field(repr=False)
    horizon_periods: int
    frequency: str
    conf: float
    driver_assumption: str
    resid_std: float
    last_level: float
    last_date: pd.Timestamp
    as_of: pd.Timestamp | None
    basis: str
    betas: pd.Series = field(default_factory=lambda: pd.Series(dtype=float), repr=False)
    expected_period_return: float = 0.0
    notes: list[str] = field(default_factory=list)


def _expected_driver_returns(
    driver_rets: pd.DataFrame,
    order: list[str],
    assumption: str,
    driver_paths: dict[str, float] | None,
) -> dict[str, float]:
    """Per-period expected return for each driver under the chosen assumption."""
    if assumption == HOLD_LAST:
        return {k: 0.0 for k in order}
    if assumption == MOMENTUM:
        return {k: float(driver_rets[k].mean()) for k in order}
    if assumption == SCENARIO:
        if not driver_paths:
            raise ValueError("driver_assumption='scenario' requires driver_paths")
        missing = [k for k in order if k not in driver_paths]
        if missing:
            raise ValueError(f"scenario is missing a path for driver(s): {missing}")
        return {k: float(driver_paths[k]) for k in order}
    raise ValueError(f"driver_assumption must be one of {sorted(ASSUMPTIONS)}")


def forecast(
    target_levels: pd.Series,
    driver_levels: dict[str, pd.Series],
    *,
    order: list[str],
    horizon_periods: int,
    frequency: str = "W",
    return_kind: str = "log",
    est_window: int = 104,
    driver_assumption: str = HOLD_LAST,
    driver_paths: dict[str, float] | None = None,
    conf: float = 0.80,
    as_of: pd.Timestamp | None = None,
    basis: str = "",
    extra_notes: list[str] | None = None,
) -> Forecast:
    """Extrapolate the driver regression ``horizon_periods`` ahead.

    Fits ``y ~ const + Σ b_k x_k`` (raw driver returns) over the trailing ``est_window``,
    forms the expected per-period target return from the assumed driver path, and rolls it
    forward onto the last level. The band is ``point · exp(± z·resid_std·√k)`` (log) — it
    widens with √horizon and *ignores* parameter and driver-path uncertainty, which is
    stamped in ``notes`` rather than hidden.
    """
    if horizon_periods <= 0:
        raise ValueError("horizon_periods must be >= 1")
    if not 0 < conf < 1:
        raise ValueError("conf must be in (0, 1)")
    order = [c for c in order if c in driver_levels]
    if not order:
        raise ValueError("no drivers available to forecast from")

    freq = _resample_freq(frequency)
    tgt = target_levels.astype(float).resample(freq).last()
    y = to_returns(tgt, return_kind).rename("__y__")
    driver_rets = pd.DataFrame(
        {k: to_returns(driver_levels[k].astype(float).resample(freq).last(), return_kind)
         for k in order}
    )
    panel = pd.concat([y, driver_rets], axis=1).dropna()
    if len(panel) < len(order) + 2:
        raise ValueError(
            f"not enough overlapping observations ({len(panel)}) to fit {len(order)} drivers"
        )
    est = panel.iloc[-est_window:] if est_window and len(panel) > est_window else panel

    res = stats.ols_hac(est["__y__"], est[order])
    resid_std = float(res.resid.std(ddof=1))
    const = float(res.params.get("const", 0.0))

    e_drivers = _expected_driver_returns(est[order], order, driver_assumption, driver_paths)
    mu = const + sum(float(res.params.get(k, 0.0)) * e_drivers[k] for k in order)

    last_level = float(tgt.dropna().iloc[-1])
    last_date = pd.Timestamp(tgt.dropna().index[-1])
    future = pd.date_range(last_date, periods=horizon_periods + 1, freq=freq)[1:]
    k = np.arange(1, horizon_periods + 1)

    z = float(spstats.norm.ppf(0.5 + conf / 2.0))
    half = z * resid_std * np.sqrt(k)
    if return_kind == "log":
        point = last_level * np.exp(mu * k)
        lo = point * np.exp(-half)
        hi = point * np.exp(half)
    else:  # pct — compounding is approximate; band applied multiplicatively as an approx
        point = last_level * np.power(1.0 + mu, k)
        lo = point * (1.0 - half)
        hi = point * (1.0 + half)

    path = pd.DataFrame({"point": point, "lo": lo, "hi": hi}, index=future)

    notes = [
        f"driver assumption: {driver_assumption}"
        + ("" if driver_assumption != HOLD_LAST else " (drift-only — drivers NOT modelled)"),
        f"{int(conf * 100)}% band = point·exp(±z·σ·√k); ignores parameter and "
        "driver-path uncertainty (understated).",
        "forecast uses total (non-orthogonalized) betas; the decomposition uses "
        "orthogonalized betas — coefficients differ by construction.",
    ]
    if return_kind != "log":
        notes.append("pct returns: level compounding is approximate.")
    notes.extend(extra_notes or [])

    return Forecast(
        path=path,
        horizon_periods=horizon_periods,
        frequency=frequency,
        conf=conf,
        driver_assumption=driver_assumption,
        resid_std=resid_std,
        last_level=last_level,
        last_date=last_date,
        as_of=as_of,
        basis=basis,
        betas=res.params,
        expected_period_return=float(mu),
        notes=notes,
    )


def run_forecast(
    spec,
    *,
    horizon_periods: int,
    driver_assumption: str = HOLD_LAST,
    driver_paths: dict[str, float] | None = None,
    conf: float = 0.80,
    as_of=None,
    registry_dir=None,
    path=None,
) -> Forecast:
    """Fetch a decomposition spec's target + drivers (point-in-time if ``as_of`` given)
    and forecast — the runner the app calls. Reuses the decomposition's data fetch so the
    forecast is built on identical series."""
    from quant import store
    from quant.decomp.run import fetch_levels

    store_path = path if path is not None else store.FACTS_PATH
    target, driver_levels, used, missing = fetch_levels(
        spec, as_of=as_of, registry_dir=registry_dir, path=store_path
    )
    extra = ([f"declared but absent, dropped from the fit: {', '.join(missing)}."]
             if missing else None)
    return forecast(
        target,
        driver_levels,
        order=used,
        horizon_periods=horizon_periods,
        frequency=spec.frequency,
        return_kind=spec.return_kind,
        est_window=spec.est_window,
        driver_assumption=driver_assumption,
        driver_paths=driver_paths,
        conf=conf,
        as_of=pd.Timestamp(as_of) if as_of is not None else None,
        basis=f"{spec.target} ~ {' + '.join(used)}",
        extra_notes=extra,
    )
