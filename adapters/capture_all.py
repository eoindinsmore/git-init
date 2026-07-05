"""Bulk capture — pull every registry series through its adapter.

    python -m adapters.capture_all            # all sources
    python -m adapters.capture_all fred cftc  # only the named sources

Isolates per-series failures (one bad series never stops the rest) and prints a
summary. The store is append-only + idempotent, so this is safe to re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path

from adapters import premium
from adapters.cftc import CftcAdapter
from adapters.estat import EstatAdapter
from adapters.eurostat import EurostatAdapter
from adapters.fred import FredAdapter
from adapters.lme_cotr import LmeCotrAdapter
from adapters.statcan import StatCanAdapter
from quant import store
from registry.loader import load_registry

# Registry source key -> adapter class. 'premium' is handled specially below.
_ADAPTERS = {
    "fred": FredAdapter,
    "eurostat": EurostatAdapter,
    "statcan": StatCanAdapter,
    "estat": EstatAdapter,
    "cftc": CftcAdapter,
    "lme_cotr": LmeCotrAdapter,
}


def run(sources: list[str] | None = None, path: Path = store.FACTS_PATH) -> dict[str, int]:
    """Pull all registry series (optionally filtered to ``sources``). Returns {series_id: rows}."""
    registry = load_registry()
    want = set(sources) if sources else None
    instances: dict[str, object] = {}
    written: dict[str, int] = {}

    # premium series use a bespoke capture job, not a BaseAdapter.
    if want is None or "premium" in want:
        try:
            written.update(premium.run_all(path=path))
        except Exception as e:  # noqa: BLE001
            print(f"  !! premium: FAILED — {type(e).__name__}: {e}")

    for series_id, spec in registry.items():
        if spec.source == "premium" or spec.source not in _ADAPTERS:
            continue
        if want is not None and spec.source not in want:
            continue
        adapter = instances.setdefault(spec.source, _ADAPTERS[spec.source]())
        try:
            written[series_id] = adapter.run(series_id, path=path)
        except Exception as e:  # noqa: BLE001 — isolate per-series failures
            written[series_id] = -1
            print(f"  !! {series_id} ({spec.source}): {type(e).__name__}: {str(e)[:80]}")
    return written


def main(argv: list[str]) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    sources = argv[1:] or None
    result = run(sources)
    ok = {k: v for k, v in result.items() if v >= 0}
    failed = [k for k, v in result.items() if v < 0]
    by_src: dict[str, int] = {}
    reg = load_registry()
    for sid, n in ok.items():
        src = reg[sid].source if sid in reg else "premium"
        by_src[src] = by_src.get(src, 0) + n
    print("\nrows written by source:")
    for src, n in sorted(by_src.items()):
        print(f"  {src:10s} {n}")
    print(f"total: {sum(ok.values())} rows across {len(ok)} series; {len(failed)} failed")
    if failed:
        print(f"failed: {', '.join(failed[:20])}{' ...' if len(failed) > 20 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
