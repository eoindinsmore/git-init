"""StatCan discovery — surface metals-relevant cubes (tables) by keyword.

Our StatCan adapter pulls by *vector* id, but StatCan offers no vector keyword
search; a vector is one coordinate within a multi-dimensional cube. So this
discovers relevant *cubes* from getAllCubesListLite and emits them as reference
leads (include=N): the user opens the cube's StatCan page, copies the specific
vector id, and adds it via the workbook. This avoids inventing vector ids.
"""

from __future__ import annotations

import requests

from discovery.relevance import Candidate
from registry.schema import Category, MacroTheme

_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getAllCubesListLite"
_UA = {"User-Agent": "home-fund/0.1 (personal research)"}

# Keywords in cube titles worth surfacing for a base-metals platform.
KEYWORDS = [
    "copper", "aluminum", "aluminium", "zinc", "nickel", "lead", "mineral",
    "metal ore", "smelter", "primary metal", "mining", "metal manufacturing",
]


def discover_statcan() -> list[Candidate]:
    r = requests.get(_URL, headers=_UA, timeout=90)
    r.raise_for_status()
    cubes = r.json()

    out: list[Candidate] = []
    seen: set[str] = set()
    for cube in cubes:
        title = (cube.get("cubeTitleEn") or "").strip()
        pid = str(cube.get("productId", ""))
        if not title or not pid or pid in seen:
            continue
        tl = title.lower()
        if not any(k in tl for k in KEYWORDS):
            continue
        seen.add(pid)
        out.append(
            Candidate(
                series_id=f"ca_cube_{pid}",
                source="statcan",
                source_code=pid,  # productId, NOT a vector — lead only
                name=f"[CUBE LEAD] {title}",
                unit="units",
                frequency="M",
                sa_status="NSA",
                metal=None,
                country="CA",
                category=Category.ACTIVITY.value,
                macro_theme=MacroTheme.ACTIVITY.value,
                score=40.0,
                reason=(
                    f"StatCan cube {pid} — open the table, copy a vector id, add it "
                    "via the workbook (source_code = vectorId)"
                ),
                include=False,  # not directly pullable; needs a vector
            )
        )
    return sorted(out, key=lambda c: c.name)
