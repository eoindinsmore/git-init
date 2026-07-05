"""Thin CLI over the tracker (spec §7).

``new`` / ``amend`` / ``close`` / ``mark`` / ``verify`` / ``report`` — every one is a
wrapper around the same functions the Streamlit page calls. There is deliberately **no
business logic here**: the CLI only parses arguments, prompts for anything missing, and
prints results. Run as ``python -m tracker.cli <cmd>``.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from tracker import analytics, calls, marking
from tracker import events as ev
from tracker.calls import CallError
from tracker.events import LIVE_EXPRESSIONS


def _prompt(label: str, current: str | None) -> str:
    if current is not None:
        return current
    return input(f"{label}: ").strip()


def _cmd_new(a: argparse.Namespace) -> int:
    interactive = sys.stdin.isatty()
    try:
        kw = dict(
            instrument=_prompt("instrument (registry series_id)", a.instrument),
            expression=_prompt(f"expression {sorted(e.value for e in LIVE_EXPRESSIONS)}",
                               a.expression),
            metal=_prompt("metal", a.metal),
            direction=_prompt("direction (long/short)", a.direction),
            target=float(_prompt("target", a.target)),
            stop=float(_prompt("stop", a.stop)),
            horizon_days=int(_prompt("horizon_days (5–365)", a.horizon)),
            confidence=float(_prompt("confidence (0.05–0.95, 0.05 grid)", a.confidence)),
            thesis=_prompt("thesis (≥20 chars)", a.thesis),
            size_R=a.size_R,
        )
    except (EOFError, KeyboardInterrupt):
        print("\naborted.")
        return 1
    if not interactive and any(v is None for v in (a.instrument, a.target, a.stop)):
        print("error: non-interactive use needs --instrument/--target/--stop at minimum",
              file=sys.stderr)
        return 2
    try:
        call = calls.new_call(**kw)
    except (CallError, ValueError) as e:
        print(f"rejected: {e}", file=sys.stderr)
        return 1
    print(f"logged call.new  call_id={call.call_id}")
    print(f"  regime_at_entry: {call.regime_at_entry or '—'}")
    print(f"  chain head: {ev.head_hash()[:12]}…")
    return 0


def _cmd_amend(a: argparse.Namespace) -> int:
    try:
        e = calls.amend(
            a.call_id, reason=a.reason, target=a.target, stop=a.stop,
            thesis=a.thesis, horizon_days=a.horizon,
        )
    except CallError as err:
        print(f"rejected: {err}", file=sys.stderr)
        return 1
    print(f"logged call.amend  event_id={e.event_id}")
    return 0


def _cmd_close(a: argparse.Namespace) -> int:
    try:
        e = calls.close(a.call_id, reason=a.reason)
    except CallError as err:
        print(f"rejected: {err}", file=sys.stderr)
        return 1
    print(f"logged call.close  event_id={e.event_id}")
    return 0


def _cmd_mark(a: argparse.Namespace) -> int:
    emitted = marking.mark_open_calls(a.as_of)
    if not emitted:
        print("no calls resolved.")
        return 0
    for e in emitted:
        print(f"  {e.event_type.value:16s} call={e.call_id[:8]}  "
              f"exit={e.exit_price:g}  R={e.pnl_R:+.2f}")
    print(f"{len(emitted)} call(s) resolved.")
    return 0


def _cmd_verify(_a: argparse.Namespace) -> int:
    res = ev.verify(ev.EVENTS_PATH)  # read the attribute at call time (redirectable)
    print(res.summary())
    return 0 if res.ok else 1


def _cmd_report(a: argparse.Namespace) -> int:
    from tracker import report

    out = a.out or f"track_record_{date.today():%Y%m%d}.html"
    view = analytics.build_view(as_of=a.as_of)
    path = report.render(view, out_path=out, as_of=a.as_of)
    print(f"wrote {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tracker", description="Trade recommendation tracker CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="log a new recommendation (call.new)")
    for f in ("instrument", "expression", "metal", "direction", "target", "stop",
              "confidence", "thesis"):
        n.add_argument(f"--{f}")
    n.add_argument("--horizon", help="horizon in days")
    n.add_argument("--size-R", type=float, default=1.0, dest="size_R")
    n.set_defaults(func=_cmd_new)

    am = sub.add_parser("amend", help="revise an open call (call.amend)")
    am.add_argument("--call-id", required=True, dest="call_id")
    am.add_argument("--reason", required=True)
    am.add_argument("--target", type=float)
    am.add_argument("--stop", type=float)
    am.add_argument("--thesis")
    am.add_argument("--horizon", type=int)
    am.set_defaults(func=_cmd_amend)

    cl = sub.add_parser("close", help="discretionary close (call.close)")
    cl.add_argument("--call-id", required=True, dest="call_id")
    cl.add_argument("--reason", required=True)
    cl.set_defaults(func=_cmd_close)

    mk = sub.add_parser("mark", help="run the marking engine")
    mk.add_argument("--as-of", dest="as_of")
    mk.set_defaults(func=_cmd_mark)

    vf = sub.add_parser("verify", help="verify the hash chain")
    vf.set_defaults(func=_cmd_verify)

    rp = sub.add_parser("report", help="render the one-page track record")
    rp.add_argument("--as-of", dest="as_of")
    rp.add_argument("--out", help="output path (.html or .pdf)")
    rp.set_defaults(func=_cmd_report)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
