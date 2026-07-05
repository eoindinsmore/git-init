"""Price decomposition — "why did the price move" attribution (spec §4)."""

from __future__ import annotations

from quant.decomp.core import (
    DRIFT,
    RESIDUAL,
    ContributionSeries,
    DecompResult,
    contribution_timeseries,
    decompose,
    orthogonalize,
    to_returns,
)
from quant.decomp.report import contributions_frame, render_html
from quant.decomp.run import (
    ContributionTSRun,
    DecompRun,
    run_contribution_timeseries,
    run_decomposition,
)
from quant.decomp.spec import DecompSpec, DriverSpec, load_named, load_spec

__all__ = [
    "DRIFT",
    "RESIDUAL",
    "ContributionSeries",
    "ContributionTSRun",
    "DecompResult",
    "DecompRun",
    "DecompSpec",
    "DriverSpec",
    "contribution_timeseries",
    "contributions_frame",
    "decompose",
    "load_named",
    "load_spec",
    "orthogonalize",
    "render_html",
    "run_contribution_timeseries",
    "run_decomposition",
    "to_returns",
]
