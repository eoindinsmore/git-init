"""Eurostat discovery — curated enumeration of metals-relevant industrial
production series (dataset sts_inpr_m) across metals NACE sectors × major EU
economies. A Eurostat "series" is one dimension-filtered slice of a dataset, so
this enumerates verified NACE × geo combinations rather than searching.
"""

from __future__ import annotations

from discovery.relevance import Candidate
from registry.loader import load_registry
from registry.schema import Category, MacroTheme

# (NACE code, id slug, label) — verified to return data in sts_inpr_m.
NACE: list[tuple[str, str, str]] = [
    ("B-D", "ip_total", "industry (mining+manufacturing+energy)"),
    ("C", "ip_mfg", "manufacturing"),
    ("C24", "ip_basic_metals", "basic metals (NACE C24)"),
    ("C25", "ip_fab_metal", "fabricated metal products (NACE C25)"),
    ("C245", "ip_casting", "casting of metals (NACE C245)"),
]
# (geo code, country slug) — major metal-consuming EU economies + aggregate.
GEO: list[tuple[str, str]] = [
    ("EU27_2020", "eu"),
    ("DE", "de"),
    ("FR", "fr"),
    ("IT", "it"),
    ("ES", "es"),
    ("PL", "pl"),
]


def discover_eurostat() -> list[Candidate]:
    existing = {s.series_id for s in load_registry().values()}
    out: list[Candidate] = []
    for nace, nace_slug, nace_label in NACE:
        metal = "metals" if nace in ("C24", "C245") else None
        for geo, country in GEO:
            sid = f"{country}_{nace_slug}"
            if sid in existing:
                continue
            out.append(
                Candidate(
                    series_id=sid,
                    source="eurostat",
                    source_code="sts_inpr_m",
                    name=f"{geo} industrial production — {nace_label} (SCA)",
                    unit="Index 2021=100",
                    frequency="M",
                    sa_status="SA",
                    metal=metal,
                    country=geo if geo != "EU27_2020" else "EU",
                    category=Category.ACTIVITY.value,
                    macro_theme=MacroTheme.ACTIVITY.value,
                    source_params={
                        "geo": geo, "nace_r2": nace, "s_adj": "SCA", "unit": "I21",
                    },
                    score=90.0 if metal else 60.0,  # metals sectors ranked higher
                    reason=f"sts_inpr_m {nace} {geo}",
                    include=True,
                )
            )
    return out
