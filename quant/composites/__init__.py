"""Composite indicators — aggregate many series into one Signal (spec §5)."""

from __future__ import annotations

from quant.composites.build import CompositeBuild, build_composite
from quant.composites.core import diffusion_index, pit_pca_first_component, zscore_composite
from quant.composites.spec import CompositeSpec, load_named, load_spec

__all__ = [
    "CompositeBuild",
    "CompositeSpec",
    "build_composite",
    "diffusion_index",
    "load_named",
    "load_spec",
    "pit_pca_first_component",
    "zscore_composite",
]
