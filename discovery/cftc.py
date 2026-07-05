"""CFTC COT discovery — enumerate metals markets × core disaggregated position
fields. The universe is small and fixed (COMEX lists only a few base-metals
markets), so this enumerates a curated market list rather than searching.
"""

from __future__ import annotations

from discovery.relevance import Candidate
from registry.loader import load_registry
from registry.schema import Category, MacroTheme

# (market LIKE pattern, metal tag). Copper is already in the registry (deduped).
MARKETS: list[tuple[str, str]] = [
    ("COPPER- #1%", "copper"),
    ("ALUMINUM - %", "aluminium"),
    ("COBALT - %", "cobalt"),
    ("GOLD - %", "gold"),        # macro / risk proxy
    ("SILVER - %", "silver"),    # macro / risk proxy
]

# (CFTC field, id slug, human label). swap short has a double underscore quirk.
FIELDS: list[tuple[str, str, str]] = [
    ("open_interest_all", "open_interest", "open interest (all)"),
    ("m_money_positions_long_all", "mm_long", "managed money long"),
    ("m_money_positions_short_all", "mm_short", "managed money short"),
    ("prod_merc_positions_long", "prod_long", "producer/merchant long"),
    ("prod_merc_positions_short", "prod_short", "producer/merchant short"),
    ("swap_positions_long_all", "swap_long", "swap dealer long"),
    ("swap__positions_short_all", "swap_short", "swap dealer short"),
    ("other_rept_positions_long", "other_long", "other reportables long"),
    ("other_rept_positions_short", "other_short", "other reportables short"),
]


def discover_cftc() -> list[Candidate]:
    existing = {s.series_id for s in load_registry().values()}
    out: list[Candidate] = []
    for pattern, metal in MARKETS:
        base = metal  # slug base
        for field, slug, label in FIELDS:
            sid = f"{base}_cot_{slug}"
            if sid in existing:
                continue
            out.append(
                Candidate(
                    series_id=sid,
                    source="cftc",
                    source_code=field,
                    name=f"COMEX {metal.capitalize()} COT — {label}",
                    unit="contracts",
                    frequency="W",
                    sa_status="NSA",
                    metal=metal if metal not in ("gold", "silver") else None,
                    country="US",
                    category=Category.POSITIONING.value,
                    macro_theme=MacroTheme.POSITIONING.value,
                    source_params={"market": pattern},
                    score=100.0,
                    reason=f"COMEX {metal} disaggregated COT",
                    include=True,
                )
            )
    return out
