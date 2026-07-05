"""Wire the indicator lab to the point-in-time store.

Fetches target + candidate series, resamples to a common frequency, optionally
differences them to stationarity, and runs :func:`quant.indicators.lab.run_lab`.
Candidates absent from the store are skipped and reported.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from quant import pit, store
from quant.indicators.lab import CandidateEval, LabConfig, run_lab

_PANDAS_FREQ = {"D": "D", "W": "W", "M": "ME", "Q": "QE", "A": "YE"}


def _levels(series_id, as_of, registry_dir, path) -> pd.Series:
    if as_of is None:
        f = store.get_series(series_id, as_of=None, path=path)
    else:
        f = pit.get_series_asof(series_id, as_of, registry_dir=registry_dir, path=path)
    if f.empty:
        return pd.Series(dtype=float)
    return pd.Series(f["value"].to_numpy(), index=pd.DatetimeIndex(f["date"]), name=series_id)


def _prep(s: pd.Series, freq: str, difference: bool) -> pd.Series:
    s = s.resample(_PANDAS_FREQ.get(freq, freq)).last()
    if difference:
        s = s.diff()
    return s.replace([np.inf, -np.inf], np.nan)


def run_lab_from_store(
    target_id: str,
    candidate_ids: list[str],
    *,
    freq: str = "M",
    difference: bool = True,
    as_of: str | pd.Timestamp | None = None,
    config: LabConfig | None = None,
    registry: dict | None = None,
    write_scorecards: bool = False,
    registry_dir: Path | None = None,
    path: Path = store.FACTS_PATH,
    created_as_of: date | None = None,
) -> tuple[list[CandidateEval], list[str]]:
    """Run the lab over stored series. Returns ``(evaluations, missing_candidate_ids)``.

    ``difference=True`` first-differences target and candidates (a common way to make
    trending macro/price series stationary before a lead-lag regression).
    """
    target = _levels(target_id, as_of, registry_dir, path)
    if target.empty:
        raise ValueError(f"target '{target_id}' has no data in the store")
    target = _prep(target, freq, difference)

    candidates: dict[str, pd.Series] = {}
    missing: list[str] = []
    for cid in candidate_ids:
        lv = _levels(cid, as_of, registry_dir, path)
        if lv.empty:
            missing.append(cid)
        else:
            candidates[cid] = _prep(lv, freq, difference)

    evals = run_lab(
        target_id, target, candidates, config=config, registry=registry,
        write_scorecards=write_scorecards, created_as_of=created_as_of,
    )
    return evals, missing
