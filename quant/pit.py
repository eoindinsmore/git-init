"""Publication-lag-aware point-in-time retrieval (spec §0.2).

``quant.store.get_series`` answers *which vintage* of a value existed on a date
(the latest revision with ``as_of <= cutoff``). That is necessary but **not
sufficient** for honest research: when history is backfilled in one pass every
row gets the same ``as_of`` (today), so the vintage filter alone would happily
hand a backtest the March value on 1 April — even though, in reality, a series
with a 45-day release lag would not have published March until mid-May.

This module closes that gap by *also* applying the registry's
``publication_lag_days``: an observation dated period-end ``T`` is only knowable
from ``T + lag`` onward. Anything feeding a backtest, lead-lag test or nowcast
must read through here, never through ``store.get_series`` directly.

Layering: ``store.py`` stays pure (no registry import). This is the thin
composition layer that joins the store's vintage logic to the registry's lag
metadata.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant import store
from registry.loader import get_spec


def get_series_asof(
    series_id: str,
    as_of: str | pd.Timestamp,
    *,
    publication_lag_days: int | None = None,
    registry_dir: Path | None = None,
    path: Path = store.FACTS_PATH,
) -> pd.DataFrame:
    """Point-in-time series reconstructing public availability from the release lag.

    Returns ``[date, value]`` for ``series_id`` as it would have been *publicly
    known* on ``as_of``: the current-best estimate of each observation, keeping
    only those already released — rows where ``date + publication_lag_days <= as_of``.

    Why lag rather than the store's vintage cutoff: our histories are largely
    *backfilled* in one pass, so every row shares a single ``as_of`` (the day we
    loaded it). The store's vintage filter (``as_of_col <= cutoff``) would then
    return nothing for any past decision date — it cannot reconstruct historical
    availability. Publication lag can: an observation dated period-end ``D`` first
    became public at ``D + lag``. This is the honest PIT mechanism for backfilled
    data and is exactly the situation spec §0.2 describes.

    Revision caveat: this uses the *latest* vintage of each date (revisions folded
    in), so it does not un-wind data revisions. When true intraday vintages are
    captured and revision-accurate PIT matters, use ``store.get_series(as_of=...)``
    directly (strict vintage) — the two tools are complementary.

    ``publication_lag_days`` defaults to the registry value for the series (the
    honest choice); pass an explicit value only in tests or for what-if analysis.
    """
    cutoff = pd.Timestamp(as_of)
    # Current-best (latest vintage per date). Vintage cutoff is deliberately NOT
    # applied here — see docstring; availability is reconstructed from the lag.
    frame = store.get_series(series_id, as_of=None, path=path)

    if publication_lag_days is None:
        spec = get_spec(series_id, registry_dir=registry_dir)
        publication_lag_days = int(spec.publication_lag_days)
    if publication_lag_days < 0:
        raise ValueError("publication_lag_days must be >= 0")

    if frame.empty:
        return frame

    release_date = frame["date"] + pd.Timedelta(days=publication_lag_days)
    released = frame[release_date <= cutoff]
    return released.reset_index(drop=True)


def get_panel_asof(
    series_ids: list[str],
    as_of: str | pd.Timestamp,
    *,
    registry_dir: Path | None = None,
    path: Path = store.FACTS_PATH,
) -> pd.DataFrame:
    """A wide, date-indexed panel of several series, each point-in-time to ``as_of``.

    Columns are ``series_ids`` (order preserved); the index is the union of dates.
    Ragged edges (different last-available date per series, from differing lags)
    are left as ``NaN`` — the caller decides how to handle them (this is exactly
    the ragged-edge situation nowcasting and composites must reason about).
    """
    cols: dict[str, pd.Series] = {}
    for sid in series_ids:
        f = get_series_asof(sid, as_of, registry_dir=registry_dir, path=path)
        cols[sid] = pd.Series(f["value"].to_numpy(), index=pd.DatetimeIndex(f["date"]), name=sid)
    panel = pd.DataFrame(cols)
    return panel.sort_index()
