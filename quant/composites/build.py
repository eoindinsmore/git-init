"""Build a composite `Signal` from a spec and the point-in-time store (spec §5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from quant import pit, store
from quant.composites import core
from quant.composites.spec import CompositeSpec
from quant.signal import Signal, worst_case_lag


@dataclass(frozen=True)
class CompositeBuild:
    signal: Signal
    used: list[str]
    missing: list[str]
    method: str


def _panel(components, as_of, registry_dir, path) -> pd.DataFrame:
    cols = {}
    for sid in components:
        if as_of is None:
            f = store.get_series(sid, as_of=None, path=path)
        else:
            f = pit.get_series_asof(sid, as_of, registry_dir=registry_dir, path=path)
        if not f.empty:
            cols[sid] = pd.Series(
                f["value"].to_numpy(), index=pd.DatetimeIndex(f["date"]), name=sid
            )
    return pd.DataFrame(cols).sort_index()


def build_composite(
    spec: CompositeSpec,
    *,
    as_of: str | pd.Timestamp | None = None,
    registry: dict | None = None,
    registry_dir: Path | None = None,
    path: Path = store.FACTS_PATH,
    created_as_of: date | None = None,
) -> CompositeBuild:
    """Compute the composite by its method and wrap it as a `Signal`.

    Missing components (declared but absent from the store) are dropped and reported.
    The composite's publication lag is the worst case across the components actually
    used (a composite is only as timely as its slowest input)."""
    panel = _panel(spec.components, as_of, registry_dir, path)
    used = list(panel.columns)
    missing = [c for c in spec.components if c not in used]
    if not used:
        raise ValueError(f"composite '{spec.composite_id}': no components available in store")

    if spec.method == "diffusion":
        values = core.diffusion_index(panel)
    elif spec.method == "zscore":
        values = core.zscore_composite(panel, window=spec.window)
    else:  # pca
        ref = spec.reference or used[0]
        values = core.pit_pca_first_component(
            panel, reference=ref, min_window=spec.min_window, expanding=spec.expanding
        )
    values = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(values.index),
                       name=spec.composite_id)

    lag = 0
    if registry is not None:
        try:
            lag = worst_case_lag(used, registry)
        except KeyError:
            lag = 0

    signal = Signal(
        signal_id=spec.composite_id,
        values=values,
        direction_convention=spec.direction_convention or f"high = elevated {spec.label}",
        target=spec.target or spec.label,
        provenance=used,
        construction=f"{spec.method} composite of {len(used)} components"
                     + (f" (PCA sign-fixed to {spec.reference or used[0]}, "
                        "point-in-time loadings)" if spec.method == "pca" else ""),
        publication_lag_days=lag,
        created_as_of=created_as_of or date.today(),
    )
    return CompositeBuild(signal=signal, used=used, missing=missing, method=spec.method)
