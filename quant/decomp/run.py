"""Wire a decomposition spec to the point-in-time store and run it.

Missing drivers (declared in the spec but not yet in the registry/store — our data
reality, see docs/quant_data_gaps.md) are dropped **loudly**: they are returned in
``missing`` so the caller/report can state exactly what was and wasn't available.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant import pit, store
from quant.decomp.core import DecompResult, decompose
from quant.decomp.spec import DecompSpec


@dataclass(frozen=True)
class DecompRun:
    result: DecompResult
    spec: DecompSpec
    used: list[str]  # driver series_ids actually available and used
    missing: list[str]  # declared but absent from the store (flagged, not hidden)
    as_of: pd.Timestamp | None


def _levels(series_id: str, as_of, registry_dir, path) -> pd.Series:
    if as_of is None:
        f = store.get_series(series_id, as_of=None, path=path)
    else:
        f = pit.get_series_asof(series_id, as_of, registry_dir=registry_dir, path=path)
    if f.empty:
        return pd.Series(dtype=float)
    return pd.Series(f["value"].to_numpy(), index=pd.DatetimeIndex(f["date"]), name=series_id)


def run_decomposition(
    spec: DecompSpec,
    *,
    as_of: str | pd.Timestamp | None = None,
    window: tuple | None = None,
    registry_dir: Path | None = None,
    path: Path = store.FACTS_PATH,
) -> DecompRun:
    """Fetch target + drivers (point-in-time if ``as_of`` given) and decompose.

    ``as_of=None`` uses the current-best view (the descriptive weekly desk product);
    pass an ``as_of`` for an honest historical reconstruction.
    """
    cutoff = pd.Timestamp(as_of) if as_of is not None else None
    target = _levels(spec.target, as_of, registry_dir, path)
    if target.empty:
        raise ValueError(f"target series '{spec.target}' has no data in the store")

    driver_levels: dict[str, pd.Series] = {}
    missing: list[str] = []
    for sid in spec.ordered_driver_ids:
        lv = _levels(sid, as_of, registry_dir, path)
        if lv.empty:
            missing.append(sid)
        else:
            driver_levels[sid] = lv

    used = [s for s in spec.ordered_driver_ids if s in driver_levels]
    result = decompose(
        target,
        driver_levels,
        order=used,
        frequency=spec.frequency,
        return_kind=spec.return_kind,
        est_window=spec.est_window,
        window=window,
    )
    return DecompRun(result=result, spec=spec, used=used, missing=missing, as_of=cutoff)
