"""Wire regime classification to the point-in-time store (spec §7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from quant import pit, store
from quant.regimes import core
from quant.regimes.spec import RegimeSpec, apply_state


@dataclass
class RegimeRun:
    regimes: pd.Series
    state_categories: dict[str, pd.Series] = field(default_factory=dict)
    used: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _levels(series_id, as_of, registry_dir, path) -> pd.Series:
    if as_of is None:
        f = store.get_series(series_id, as_of=None, path=path)
    else:
        f = pit.get_series_asof(series_id, as_of, registry_dir=registry_dir, path=path)
    if f.empty:
        return pd.Series(dtype=float)
    return pd.Series(f["value"].to_numpy(), index=pd.DatetimeIndex(f["date"]), name=series_id)


def classify_from_store(
    spec: RegimeSpec,
    *,
    as_of: str | pd.Timestamp | None = None,
    registry_dir: Path | None = None,
    path: Path = store.FACTS_PATH,
) -> RegimeRun:
    """Classify regimes from the stored state series. Missing states are reported;
    the regime uses only the states available (a partial-but-honest classification)."""
    cats: dict[str, pd.Series] = {}
    missing: list[str] = []
    for st in spec.states:
        s = _levels(st.series_id, as_of, registry_dir, path)
        if s.empty:
            missing.append(st.series_id)
        else:
            cats[st.name] = apply_state(st, s)
    if not cats:
        raise ValueError(f"regime spec '{spec.name}': no state series available in the store")
    regimes = core.classify(cats)
    return RegimeRun(regimes=regimes, state_categories=cats,
                     used=[s.name for s in spec.states if s.series_id not in missing],
                     missing=missing)
