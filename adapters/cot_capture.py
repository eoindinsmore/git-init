"""Weekly COT capture job — runs every registry positioning series that comes
from a weekly Commitments-of-Traders source (CFTC COMEX + LME MiFID II).

CFTC releases Friday (Tuesday snapshot); LME publishes Tuesday (Friday snapshot).
A single weekly run after both are out captures the latest of each; the store
dedups, so re-runs are cheap and safe.

Entry point for the scheduled task:  python -m adapters.cot_capture
"""

from __future__ import annotations

from pathlib import Path

from adapters.cftc import CftcAdapter
from adapters.lme_cotr import LmeCotrAdapter
from quant import store
from registry.loader import load_registry

# Registry source key -> adapter class for weekly COT sources.
_ADAPTERS = {
    "cftc": CftcAdapter,
    "lme_cotr": LmeCotrAdapter,
}


def run_all(path: Path = store.FACTS_PATH) -> dict[str, int]:
    """Capture every registry series from a weekly COT source. Returns {series_id: rows}."""
    registry = load_registry()
    instances: dict[str, object] = {}
    written: dict[str, int] = {}
    for series_id, spec in registry.items():
        if spec.source not in _ADAPTERS:
            continue
        adapter = instances.setdefault(spec.source, _ADAPTERS[spec.source]())
        try:
            written[series_id] = adapter.run(series_id, path=path)
        except Exception as e:  # noqa: BLE001 — one bad series must not stop the rest
            written[series_id] = -1
            print(f"  !! {series_id}: FAILED — {type(e).__name__}: {e}")
    return written


def main() -> int:
    result = run_all()
    ok = {k: v for k, v in result.items() if v >= 0}
    failed = [k for k, v in result.items() if v < 0]
    for sid, n in ok.items():
        print(f"  {sid}: {n} row(s)")
    print(f"weekly COT capture complete — {sum(ok.values())} new row(s) across {len(ok)} series")
    if failed:
        print(f"{len(failed)} series FAILED: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    raise SystemExit(main())
