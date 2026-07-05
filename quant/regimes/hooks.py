"""Regime consumption hooks (spec §7) — a regime model must *do* something.

Three mandatory consumers:
(a) regime-conditional forecast-combination weights;
(b) a sizing-multiplier suggestion surfaced to the trade tracker;
(c) a regime banner payload for dashboards / PDF reports.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def inverse_mse_weights(mse_by_model: dict[str, float]) -> dict[str, float]:
    """Inverse-MSE combination weights (normalized). Zero/near-zero MSE dominates."""
    inv = {m: (1.0 / e if e and e > 0 else np.inf) for m, e in mse_by_model.items()}
    if any(np.isinf(v) for v in inv.values()):
        winners = [m for m, v in inv.items() if np.isinf(v)]
        return {m: (1.0 / len(winners) if m in winners else 0.0) for m in mse_by_model}
    total = sum(inv.values())
    if total == 0:
        n = len(inv)
        return {m: 1.0 / n for m in inv}
    return {m: v / total for m, v in inv.items()}


def combination_weights(
    regime: str, mse_by_regime_model: dict[str, dict[str, float]]
) -> dict[str, float]:
    """Forecast-combination weights **conditional on the current regime**.

    ``mse_by_regime_model[regime][model] = out-of-sample MSE in that regime``. Falls back
    to equal weights if the regime is unseen."""
    if regime not in mse_by_regime_model or not mse_by_regime_model[regime]:
        models = {m for d in mse_by_regime_model.values() for m in d}
        return {m: 1.0 / len(models) for m in models} if models else {}
    return inverse_mse_weights(mse_by_regime_model[regime])


def sizing_multiplier(
    regime: str, mapping: dict[str, float], *, default: float = 1.0
) -> float:
    """Suggested position-sizing multiplier for the current regime (for the tracker).

    e.g. dial risk down in a high-VIX / contracting regime. Unmapped regimes -> ``default``."""
    return float(mapping.get(regime, default))


def regime_banner(regimes: pd.Series, *, as_of=None) -> dict:
    """Banner payload for dashboards/reports: the current regime and its components."""
    r = regimes.dropna()
    if r.empty:
        return {"as_of": None, "regime": None, "components": {}}
    if as_of is not None:
        r = r[r.index <= pd.Timestamp(as_of)]
        if r.empty:
            return {"as_of": None, "regime": None, "components": {}}
    label = r.iloc[-1]
    components = dict(
        part.split("=", 1) for part in str(label).split(" | ") if "=" in part
    )
    return {"as_of": r.index[-1], "regime": label, "components": components}
