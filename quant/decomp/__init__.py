"""Price decomposition — "why did the price move" attribution (spec §4)."""

from __future__ import annotations

from quant.decomp.core import DRIFT, RESIDUAL, DecompResult, decompose, orthogonalize, to_returns
from quant.decomp.report import contributions_frame, render_html
from quant.decomp.run import DecompRun, run_decomposition
from quant.decomp.spec import DecompSpec, DriverSpec, load_named, load_spec

__all__ = [
    "DRIFT",
    "RESIDUAL",
    "DecompResult",
    "DecompRun",
    "DecompSpec",
    "DriverSpec",
    "contributions_frame",
    "decompose",
    "load_named",
    "load_spec",
    "orthogonalize",
    "render_html",
    "run_decomposition",
    "to_returns",
]
