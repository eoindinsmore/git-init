"""Forecasting models (project step 4/7). Separate namespace from the analyst trade
tracker: model forecasts are NOT trade calls (tracker spec §6)."""

from __future__ import annotations

from models.evaluate import walk_forward_predictions, walk_forward_skill
from models.forecast import (
    ASSUMPTIONS,
    HOLD_LAST,
    MOMENTUM,
    SCENARIO,
    Forecast,
    run_forecast,
)
from models.strategy import StrategyResult, backtest_regression

# NB: the pure core `forecast()` is intentionally NOT re-exported here — doing so would
# shadow the `models.forecast` submodule. Import it as `from models.forecast import forecast`.

__all__ = [
    "ASSUMPTIONS",
    "HOLD_LAST",
    "MOMENTUM",
    "SCENARIO",
    "Forecast",
    "StrategyResult",
    "backtest_regression",
    "run_forecast",
    "walk_forward_predictions",
    "walk_forward_skill",
]
