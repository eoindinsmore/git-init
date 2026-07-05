"""Run all source discoveries and stage the combined candidate set for review.

    python -m discovery.run            # -> registry_candidates.xlsx

Each source contributes a sheet; rows default include=Y for the metals core and
include=N for opt-in macro / non-pullable leads.
"""

from __future__ import annotations

from pathlib import Path

from discovery.cftc import discover_cftc
from discovery.estat import discover_estat
from discovery.eurostat import discover_eurostat
from discovery.fred import discover_fred
from discovery.lme import discover_lme
from discovery.relevance import Candidate
from discovery.stage import stage_xlsx
from discovery.statcan import discover_statcan

OUT = Path("registry_candidates.xlsx")

# name -> callable; each returns list[Candidate]. Isolated so one failure is visible.
SOURCES = {
    "fred": discover_fred,
    "cftc": discover_cftc,
    "lme_cotr": discover_lme,
    "eurostat": discover_eurostat,
    "estat": discover_estat,
    "statcan": discover_statcan,
}


def run_all() -> list[Candidate]:
    all_cands: list[Candidate] = []
    for name, fn in SOURCES.items():
        try:
            cands = fn()
            inc = sum(1 for c in cands if c.include)
            print(f"  {name:10s} {len(cands):>4} candidates ({inc} include=Y)")
            all_cands.extend(cands)
        except Exception as e:  # noqa: BLE001 — one source failing must not block others
            print(f"  {name:10s} FAILED — {type(e).__name__}: {e}")
    return all_cands


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()
    cands = run_all()
    stage_xlsx(cands, OUT)
    inc = sum(1 for c in cands if c.include)
    print(f"\n{len(cands)} candidates ({inc} include=Y) -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
