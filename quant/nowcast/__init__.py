"""Nowcasting via bridge equations, with a vintage record (spec §2)."""

from __future__ import annotations

from quant.nowcast.core import (
    BridgeModel,
    aggregate_over,
    mae,
    naive_benchmarks,
    period_bounds,
)
from quant.nowcast.evaluate import (
    accuracy_vs_information,
    benchmark_comparison,
    nowcast_evolution,
)
from quant.nowcast.run import NowcastSetup, fit_from_store, record_nowcast
from quant.nowcast.vintage import NowcastVintage, read_all, record

__all__ = [
    "BridgeModel",
    "NowcastSetup",
    "NowcastVintage",
    "accuracy_vs_information",
    "aggregate_over",
    "benchmark_comparison",
    "fit_from_store",
    "mae",
    "naive_benchmarks",
    "nowcast_evolution",
    "period_bounds",
    "read_all",
    "record",
    "record_nowcast",
]
