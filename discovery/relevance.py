"""Shared relevance vocabulary + auto-tagging for discovered series.

Auto-tagging is heuristic and deliberately conservative: it proposes
metal / macro_theme / category from a series title, and everything is reviewed
by a human before it enters the registry. Borderline items are flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from registry.schema import Category, MacroTheme

# Metal keyword -> canonical metal tag (aluminium spelling normalized).
_METALS = {
    "copper": "copper",
    "aluminum": "aluminium",
    "aluminium": "aluminium",
    "zinc": "zinc",
    "nickel": "nickel",
    "lead": "lead",
    "tin": "tin",
    "steel": "steel",
    "iron ore": "iron_ore",
    "cobalt": "cobalt",
}


@dataclass
class Candidate:
    """A discovered series proposed for the registry, pending human approval."""

    series_id: str
    source: str
    source_code: str
    name: str
    unit: str
    frequency: str
    sa_status: str
    metal: str | None
    country: str | None
    category: str
    macro_theme: str
    caveats: str = ""
    source_params: dict[str, str] = field(default_factory=dict)
    selector: dict[str, str] = field(default_factory=dict)
    # review aids (not registry fields):
    score: float = 0.0
    reason: str = ""
    include: bool = True


def detect_metal(title: str) -> str | None:
    """Match a metal name as a whole word (so 'disconTINued' does not match 'tin')."""
    t = title.lower()
    for kw, canon in _METALS.items():
        if re.search(rf"\b{re.escape(kw)}\b", t):
            return canon
    return None


def classify(title: str, units: str, theme_hint: str) -> tuple[str, str, bool]:
    """Return (category, macro_theme, is_price_proxy) from a title/units + a hint.

    ``theme_hint`` is the macro_theme of the search query that surfaced the series;
    title keywords refine it. The bool flags price-level series that need caveats.
    """
    t = title.lower()
    u = (units or "").lower()

    price_level = ("$ per" in u or "per metric ton" in u or "per pound" in u
                   or "global price of" in t or "spot price" in t)
    metal = detect_metal(title)

    if price_level and metal:
        return Category.PRICE_PROXY.value, MacroTheme.COMMODITIES.value, True
    if any(k in t for k in ("natural gas", "electricity", "crude oil", "petroleum",
                            "energy price")):
        return Category.ENERGY.value, MacroTheme.ENERGY.value, False
    if any(k in t for k in ("industrial production", "capacity utilization",
                            "manufacturing", "mining", "output", "iip")):
        return Category.ACTIVITY.value, MacroTheme.ACTIVITY.value, False
    if any(k in t for k in ("housing", "construction", "vehicle", "new orders",
                            "durable goods", "sales", "starts", "permits")):
        return Category.DEMAND.value, MacroTheme.ACTIVITY.value, False
    if any(k in t for k in ("import", "export", "trade balance")):
        return Category.TRADE.value, MacroTheme.ACTIVITY.value, False
    if any(k in t for k in ("dollar", "exchange rate", "treasury", "yield",
                            "interest rate", "breakeven", "real rate")):
        return Category.OTHER.value, MacroTheme.RATES.value, False
    if any(k in t for k in ("consumer price", "producer price", "inflation", "cpi", "ppi")):
        theme = MacroTheme.COMMODITIES.value if metal else MacroTheme.INFLATION.value
        return Category.OTHER.value, theme, False
    # Fall back to the query's theme hint.
    return Category.OTHER.value, theme_hint, False


def default_caveat(source: str, name: str, frequency: str) -> str:
    return (
        f"{source.upper()} reference series ('{name}'), {frequency} frequency — a "
        "free public proxy, NOT a licensed exchange settlement. Verify basis before "
        "quantitative use; may be a monthly/quarterly average with no intramonth detail."
    )
