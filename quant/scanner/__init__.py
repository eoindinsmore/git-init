"""Outlier / dislocation scanner — daily idea-generation screen (spec §6)."""

from __future__ import annotations

from quant.scanner.core import (
    ScanResult,
    build_derived,
    percentile_rank,
    scan,
    zscore_series,
)
from quant.scanner.run import promote_flag, run_scan
from quant.scanner.spec import DerivedItem, UniverseSpec, load_named, load_universe

__all__ = [
    "DerivedItem",
    "ScanResult",
    "UniverseSpec",
    "build_derived",
    "load_named",
    "load_universe",
    "percentile_rank",
    "promote_flag",
    "run_scan",
    "scan",
    "zscore_series",
]
