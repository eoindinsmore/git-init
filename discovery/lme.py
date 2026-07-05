"""LME COTR discovery — enumerate base metals × MiFID II categories × sides.

The universe is fixed: 6 base metals (CDN folder slugs verified) × 4 MiFID
classifications × {Long, Short}, Total basis. Enumerates directly.
"""

from __future__ import annotations

from discovery.relevance import Candidate
from registry.loader import load_registry
from registry.schema import Category, MacroTheme

# (folder slug, filename key, metal tag) — all verified present on the LME CDN.
METALS: list[tuple[str, str, str]] = [
    ("ca-copper", "ca", "copper"),
    ("ah-aluminium", "ah", "aluminium"),
    ("zs-zinc", "zs", "zinc"),
    ("ni-nickel", "ni", "nickel"),
    ("pb-lead", "pb", "lead"),
    ("sn-tin", "sn", "tin"),
]

# (category substring for the sheet, id slug, human label)
CATEGORIES: list[tuple[str, str, str]] = [
    ("Investment Funds", "inv_funds", "Investment Funds"),
    ("Commercial Undertaking", "commercial", "Commercial Undertakings"),
    ("Investment Firms", "inv_firms", "Investment Firms/credit institutions"),
    ("Other Financial", "other_fin", "Other Financial Institutions"),
]
SIDES = [("Long", "long"), ("Short", "short")]


def discover_lme() -> list[Candidate]:
    existing = {s.series_id for s in load_registry().values()}
    out: list[Candidate] = []
    for folder, key, metal in METALS:
        for cat_sub, cat_slug, cat_label in CATEGORIES:
            for side, side_slug in SIDES:
                sid = f"{metal}_lme_{cat_slug}_{side_slug}"
                if sid in existing:
                    continue
                out.append(
                    Candidate(
                        series_id=sid,
                        source="lme_cotr",
                        source_code=key,
                        name=f"LME {metal.capitalize()} COTR — {cat_label} {side.lower()} (total)",
                        unit="lots",
                        frequency="W",
                        sa_status="NSA",
                        metal=metal,
                        country="GB",
                        category=Category.POSITIONING.value,
                        macro_theme=MacroTheme.POSITIONING.value,
                        source_params={
                            "folder": folder, "key": key,
                            "category": cat_sub, "side": side, "basis": "Total",
                        },
                        score=100.0,
                        reason=f"LME {metal} MiFID II COTR",
                        include=True,
                    )
                )
    return out
