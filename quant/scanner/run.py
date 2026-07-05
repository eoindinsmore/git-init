"""Wire the scanner universe to the store, and the screen→thesis tracker hook.

``run_scan`` builds the item level-series (raw + derived) from the point-in-time
store and runs the screen. ``promote_flag`` is the one-click step (spec §6): it turns
a flagged scan row into a *draft* hypothesis in the append-only tracker, pre-filling
the instrument and a link back to the scan, and leaving mean-revert-vs-momentum
(direction) to the analyst.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from quant import pit, store
from quant.scanner.core import ScanResult, build_derived, scan
from quant.scanner.spec import UniverseSpec
from tracker import store as tracker_store
from tracker.schema import Direction, Hypothesis, Status


def _levels(series_id: str, as_of, registry_dir, path) -> pd.Series:
    if as_of is None:
        f = store.get_series(series_id, as_of=None, path=path)
    else:
        f = pit.get_series_asof(series_id, as_of, registry_dir=registry_dir, path=path)
    if f.empty:
        return pd.Series(dtype=float)
    return pd.Series(f["value"].to_numpy(), index=pd.DatetimeIndex(f["date"]), name=series_id)


def run_scan(
    spec: UniverseSpec,
    *,
    as_of: str | pd.Timestamp | None = None,
    registry_dir: Path | None = None,
    path: Path = store.FACTS_PATH,
) -> ScanResult:
    """Fetch the universe (point-in-time if ``as_of`` given), build derived items, scan."""
    raw = {sid: _levels(sid, as_of, registry_dir, path) for sid in spec.series}
    raw = {k: v for k, v in raw.items() if not v.empty}
    derived = build_derived(raw, spec.derived)
    levels = {**raw, **derived}
    return scan(
        levels,
        windows=spec.windows,
        z_threshold=spec.z_threshold,
        mahalanobis_set=spec.mahalanobis_set,
    )


def promote_flag(
    result: ScanResult,
    item: str,
    *,
    created_as_of: datetime | None = None,
    direction: Direction = Direction.UNDECIDED,
    path: Path = tracker_store.TRACKER_PATH,
) -> Hypothesis:
    """Promote a scanned item to a draft hypothesis in the append-only tracker.

    Pre-fills instrument, a scan back-reference, and a thesis stub from the row's
    z-stats. Direction defaults to ``undecided`` — the analyst decides mean-revert
    vs momentum (spec §6). Returns the appended (immutable) record.
    """
    if result.table.empty or item not in set(result.table["item"]):
        raise ValueError(f"item '{item}' is not in the scan table")
    row = result.table.set_index("item").loc[item]
    stamp = created_as_of or datetime.now()
    as_of_date = pd.Timestamp(row["date"]).date()
    hyp_id = f"{item}-{as_of_date:%Y%m%d}"
    abs_z = float(row.get("abs_z", float("nan")))
    thesis = (
        f"Auto-drafted from dislocation scan on {as_of_date}: |z|={abs_z:.2f}"
        f"{' (new flag)' if bool(row.get('new_flag')) else ''}. "
        "Analyst to decide mean-revert vs momentum and size."
    )
    h = Hypothesis(
        hypothesis_id=hyp_id,
        created_as_of=stamp,
        instrument=item,
        direction=direction,
        thesis=thesis,
        source="scanner",
        scan_ref=f"scan:{item}@{as_of_date}",
        status=Status.DRAFT,
    )
    tracker_store.append(h, path=path)
    return h
