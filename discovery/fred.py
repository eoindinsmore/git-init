"""FRED discovery — query the FRED series/search API across the charter theme,
dedupe, auto-fill metadata + tags, and rank by relevance/popularity.

FRED's search endpoint already ranks by relevance and exposes a popularity score,
so "most relevant" is largely native; we search a curated query set spanning the
copper/aluminium research themes and merge the results.
"""

from __future__ import annotations

import os

import requests

from discovery.relevance import Candidate, classify, default_caveat, detect_metal
from registry.loader import load_registry
from registry.schema import MacroTheme

_SEARCH = "https://api.stlouisfed.org/fred/series/search"
_TIMEOUT = 60
_UA = {"User-Agent": "home-fund/0.1 (personal research)"}

# Frequencies/SA values we can represent (schema is D/W/M/Q/A, SA/NSA).
_FREQ_OK = {"D", "W", "M", "Q", "A"}

# (query text, macro_theme hint) — the charter relevance taxonomy for FRED.
QUERIES: list[tuple[str, str]] = [
    ("copper price", MacroTheme.COMMODITIES.value),
    ("aluminum price", MacroTheme.COMMODITIES.value),
    ("zinc price", MacroTheme.COMMODITIES.value),
    ("nickel price", MacroTheme.COMMODITIES.value),
    ("lead metal price", MacroTheme.COMMODITIES.value),
    ("tin price", MacroTheme.COMMODITIES.value),
    ("iron ore price", MacroTheme.COMMODITIES.value),
    ("global price metals", MacroTheme.COMMODITIES.value),
    ("producer price index metals", MacroTheme.COMMODITIES.value),
    ("producer price primary metal", MacroTheme.COMMODITIES.value),
    ("industrial production", MacroTheme.ACTIVITY.value),
    ("industrial production primary metals", MacroTheme.ACTIVITY.value),
    ("capacity utilization", MacroTheme.ACTIVITY.value),
    ("industrial production mining", MacroTheme.ACTIVITY.value),
    ("manufacturing new orders", MacroTheme.ACTIVITY.value),
    ("housing starts", MacroTheme.ACTIVITY.value),
    ("construction spending", MacroTheme.ACTIVITY.value),
    ("motor vehicle assemblies", MacroTheme.ACTIVITY.value),
    ("durable goods orders", MacroTheme.ACTIVITY.value),
    ("trade weighted us dollar", MacroTheme.RATES.value),
    ("10-year treasury real yield", MacroTheme.RATES.value),
    ("breakeven inflation", MacroTheme.RATES.value),
    ("consumer price index", MacroTheme.INFLATION.value),
    ("henry hub natural gas price", MacroTheme.ENERGY.value),
    ("electricity price industrial", MacroTheme.ENERGY.value),
    ("crude oil price", MacroTheme.ENERGY.value),
    ("china industrial production", MacroTheme.ACTIVITY.value),
    ("copper inventories stocks", MacroTheme.COMMODITIES.value),
]


def _search(query: str, api_key: str, limit: int) -> list[dict]:
    r = requests.get(
        _SEARCH,
        params={
            "search_text": query,
            "api_key": api_key,
            "file_type": "json",
            "limit": limit,
            "order_by": "search_rank",
            "sort_order": "desc",
        },
        headers=_UA,
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("seriess", [])


def discover_fred(
    limit_per_query: int = 30,
    min_popularity: int = 20,
    api_key: str | None = None,
) -> list[Candidate]:
    """Discover charter-relevant FRED series, excluding ones already in the registry."""
    key = api_key or os.getenv("FRED_API_KEY", "")
    if not key:
        raise RuntimeError("FRED_API_KEY is not set")

    # Skip FRED codes already declared (match on source_code for source == fred).
    existing = {
        s.source_code.upper()
        for s in load_registry().values()
        if s.source == "fred"
    }

    seen: dict[str, Candidate] = {}
    for query, theme_hint in QUERIES:
        for s in _search(query, key, limit_per_query):
            fid = s.get("id", "")
            if not fid or fid.upper() in existing or fid in seen:
                continue
            freq = (s.get("frequency_short") or "").strip()
            if freq not in _FREQ_OK:
                continue  # semiannual/biweekly etc. not representable
            pop = int(s.get("popularity") or 0)
            if pop < min_popularity:
                continue
            title = s.get("title", "")
            units = s.get("units_short") or s.get("units") or "units"
            sa_short = (s.get("seasonal_adjustment_short") or "NSA").upper()
            sa = "SA" if sa_short.startswith("SA") else "NSA"
            category, theme, is_proxy = classify(title, units, theme_hint)
            caveats = default_caveat("fred", title, freq) if is_proxy else ""
            metal = detect_metal(title)
            # Theme-weighted relevance: a copper platform values metals-specific
            # series above generic macro of the same popularity.
            score = float(pop)
            if metal:
                score += 60
            if theme in ("commodities", "energy", "activity"):
                score += 25
            # Metals core is auto-included; generic macro is opt-in on review.
            include = bool(metal) or theme in ("commodities", "energy", "activity")
            seen[fid] = Candidate(
                series_id=f"fred_{fid.lower()}",
                source="fred",
                source_code=fid,
                name=title,
                unit=units,
                frequency=freq,
                sa_status=sa,
                metal=metal,
                country=None,
                category=category,
                macro_theme=theme,
                caveats=caveats,
                score=score,
                reason=f"matched '{query}', popularity {pop}",
                include=include,
            )
    return sorted(seen.values(), key=lambda c: c.score, reverse=True)
