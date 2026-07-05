"""e-Stat discovery — enumerate metals-relevant product categories (cat02) within
known Japan IIP tables. An e-Stat "series" is one cat02 category selected from a
table's cube, so this fetches each table's CLASS_INF and keeps categories whose
Japanese label matches a metals keyword.
"""

from __future__ import annotations

import os

import requests

from discovery.relevance import Candidate
from registry.loader import load_registry
from registry.schema import Category, MacroTheme

_URL = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
_UA = {"User-Agent": "home-fund/0.1 (personal research)"}

# statsDataIds to mine for metals categories (extend as more IIP tables are found).
TABLES = ["0004033012"]

# Japanese metals keywords: nonferrous, copper, aluminium, metal, steel, zinc,
# nickel, lead, tin, wire/cable.
METALS_KW = ["非鉄", "銅", "アルミ", "金属", "鉄鋼", "亜鉛", "ニッケル", "鉛", "すず", "電線"]


def _class_obj(stats_data_id: str, app_id: str) -> list[dict]:
    r = requests.get(
        _URL,
        params={"appId": app_id, "statsDataId": stats_data_id, "limit": 1},
        headers=_UA,
        timeout=60,
    )
    r.raise_for_status()
    co = r.json()["GET_STATS_DATA"]["STATISTICAL_DATA"]["CLASS_INF"]["CLASS_OBJ"]
    return co if isinstance(co, list) else [co]


def discover_estat(app_id: str | None = None) -> list[Candidate]:
    key = app_id or os.getenv("ESTAT_APP_ID", "")
    if not key:
        raise RuntimeError("ESTAT_APP_ID is not set")

    # Semantic dedupe: skip (source_code, cat02) already declared.
    existing = {
        (s.source_code, s.selector.get("cat02"))
        for s in load_registry().values()
        if s.source == "estat"
    }

    out: list[Candidate] = []
    for table in TABLES:
        for co in _class_obj(table, key):
            if co.get("@id") != "cat02":
                continue
            cats = co["CLASS"]
            for cat in (cats if isinstance(cats, list) else [cats]):
                name = cat.get("@name", "")
                if not any(k in name for k in METALS_KW):
                    continue
                code = cat["@code"]
                if (table, code) in existing:
                    continue
                out.append(
                    Candidate(
                        series_id=f"jp_iip_{code}",
                        source="estat",
                        source_code=table,
                        name=f"Japan IIP — {name}",
                        unit="Index",
                        frequency="M",
                        sa_status="NSA",
                        metal=None,  # Japanese label; metal tagged on review
                        country="JP",
                        category=Category.ACTIVITY.value,
                        macro_theme=MacroTheme.ACTIVITY.value,
                        selector={"cat02": code},
                        score=70.0,
                        reason=f"e-Stat {table} cat02 {code}",
                        include=True,
                    )
                )
    return out
