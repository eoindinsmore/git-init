"""Leading-indicator lab with FDR gates (spec §1)."""

from __future__ import annotations

from quant.indicators.core import (
    GateOutcome,
    economic_significance,
    lead_lag_scan,
    oos_confirm,
    stability,
)
from quant.indicators.lab import CandidateEval, LabConfig, run_lab
from quant.indicators.run import run_lab_from_store

__all__ = [
    "CandidateEval",
    "GateOutcome",
    "LabConfig",
    "economic_significance",
    "lead_lag_scan",
    "oos_confirm",
    "run_lab",
    "run_lab_from_store",
    "stability",
]
