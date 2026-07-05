"""Rule-based regime identification + consumption hooks (spec §7)."""

from __future__ import annotations

from quant.regimes.core import (
    band,
    classify,
    conditional_performance,
    level_delta,
    ma_trend,
    transition_matrix,
)
from quant.regimes.hooks import (
    combination_weights,
    inverse_mse_weights,
    regime_banner,
    sizing_multiplier,
)
from quant.regimes.run import RegimeRun, classify_from_store
from quant.regimes.spec import RegimeSpec, StateVarSpec, apply_state, load_named, load_spec

__all__ = [
    "RegimeRun",
    "RegimeSpec",
    "StateVarSpec",
    "apply_state",
    "band",
    "classify",
    "classify_from_store",
    "combination_weights",
    "conditional_performance",
    "inverse_mse_weights",
    "level_delta",
    "load_named",
    "load_spec",
    "ma_trend",
    "regime_banner",
    "sizing_multiplier",
    "transition_matrix",
]
