"""Wire nowcasting to the point-in-time store (spec §2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from quant import pit, store
from quant.nowcast.core import BridgeModel
from quant.nowcast.vintage import VINTAGE_PATH, NowcastVintage, record


@dataclass
class NowcastSetup:
    model: BridgeModel
    target: pd.Series
    indicator_data: dict[str, pd.Series]
    used: list[str]
    missing: list[str]


def _levels(series_id, as_of, registry_dir, path) -> pd.Series:
    if as_of is None:
        f = store.get_series(series_id, as_of=None, path=path)
    else:
        f = pit.get_series_asof(series_id, as_of, registry_dir=registry_dir, path=path)
    if f.empty:
        return pd.Series(dtype=float)
    return pd.Series(f["value"].to_numpy(), index=pd.DatetimeIndex(f["date"]), name=series_id)


def fit_from_store(
    target_id: str,
    indicator_ids: list[str],
    *,
    agg: str = "mean",
    as_of: str | pd.Timestamp | None = None,
    registry_dir: Path | None = None,
    path: Path = store.FACTS_PATH,
) -> NowcastSetup:
    """Fetch target + indicators and fit the bridge. Missing indicators are reported."""
    target = _levels(target_id, as_of, registry_dir, path)
    if target.empty:
        raise ValueError(f"target '{target_id}' has no data in the store")

    indicator_data: dict[str, pd.Series] = {}
    missing: list[str] = []
    for iid in indicator_ids:
        s = _levels(iid, as_of, registry_dir, path)
        if s.empty:
            missing.append(iid)
        else:
            indicator_data[iid] = s
    used = list(indicator_data)
    model = BridgeModel(indicators=used, agg=agg).fit(target, indicator_data)
    return NowcastSetup(model=model, target=target, indicator_data=indicator_data,
                        used=used, missing=missing)


def record_nowcast(
    setup: NowcastSetup,
    target_id: str,
    *,
    period_start,
    period_end,
    as_of: date,
    path: Path = VINTAGE_PATH,
) -> NowcastVintage:
    """Compute and append a nowcast vintage for one period at one as_of."""
    av = {k: v[v.index <= pd.Timestamp(as_of)] for k, v in setup.indicator_data.items()}
    value, se, n = setup.model.predict_period(av, pd.Timestamp(period_start),
                                              pd.Timestamp(period_end))
    v = NowcastVintage(
        target_id=target_id, target_period=pd.Timestamp(period_end).date(),
        as_of=as_of, value=value, se=se, n_inputs=n,
    )
    record(v, path=path)
    return v
