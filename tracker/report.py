"""One-page track-record report (spec §5) — the page that gets handed across a table.

It must be self-explanatory and self-caveating: headline stats, the calibration diagram
(the headline exhibit), the R equity curve, a hit-rate matrix, the marking-conventions
box, the **hash-chain verification line**, and a generation timestamp — all on one page.

Rendered as fully self-contained HTML (inline SVG charts, no external assets), mirroring
:mod:`quant.scorecard`. A PDF is produced with WeasyPrint when it is installed (the
optional ``[report]`` extra); otherwise the HTML is written and its path returned, so the
report is always available even where WeasyPrint's native deps are not (e.g. Windows).
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from tracker import analytics
from tracker import events as ev

# --- Inline SVG charts (no external assets) ---------------------------------------

def _reliability_svg(rel: pd.DataFrame, brier: float | None, n: int) -> str:
    """Reliability diagram: realized frequency vs. stated confidence, 45° = perfect."""
    W = H = 240
    pad = 30
    span = W - 2 * pad

    def x(c):  # confidence 0..1 → px
        return pad + c * span

    def y(f):  # frequency 0..1 → px (inverted)
        return H - pad - f * span

    if rel.empty or n == 0:
        return _empty_svg(W, H, "no market-resolved calls yet")

    diag = f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(1)}" y2="{y(1)}" ' \
           'stroke="#8A857B" stroke-width="1" stroke-dasharray="4 3"/>'
    frame = (
        f'<rect x="{pad}" y="{pad}" width="{span}" height="{span}" fill="none" '
        'stroke="#1A1A17" stroke-width="1"/>'
    )
    pts = []
    nmax = max(rel["n"]) if len(rel) else 1
    for _, r in rel.iterrows():
        radius = 3 + 6 * (r["n"] / nmax)
        pts.append(
            f'<circle cx="{x(r["mean_confidence"]):.1f}" cy="{y(r["realized_freq"]):.1f}" '
            f'r="{radius:.1f}" fill="#0B4F6C" fill-opacity="0.8"/>'
        )
    labels = (
        f'<text x="{pad}" y="{H - 8}" font-size="9" fill="#55514A">0</text>'
        f'<text x="{W - pad - 6}" y="{H - 8}" font-size="9" fill="#55514A">1</text>'
        f'<text x="6" y="{pad + 6}" font-size="9" fill="#55514A">1</text>'
        f'<text x="{pad}" y="{H - 16}" font-size="10" fill="#55514A" '
        f'transform="translate(0,0)">stated confidence →</text>'
    )
    brier_txt = "" if brier is None else \
        f'<text x="{W - pad}" y="{pad + 12}" font-size="10" fill="#1A1A17" ' \
        f'text-anchor="end">Brier {brier:.3f} (n={n})</text>'
    return (
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'xmlns="http://www.w3.org/2000/svg">{frame}{diag}{"".join(pts)}{labels}{brier_txt}</svg>'
    )


def _equity_svg(equity: pd.DataFrame) -> str:
    """Cumulative-R equity curve as a simple polyline with a zero baseline."""
    W, H, pad = 300, 200, 26
    if equity.empty or len(equity) < 1:
        return _empty_svg(W, H, "no resolved calls yet")

    vals = equity["value"].to_numpy()
    lo, hi = min(0.0, float(vals.min())), max(0.0, float(vals.max()))
    rng = (hi - lo) or 1.0
    n = len(vals)

    def px(i):
        return pad + (i / max(n - 1, 1)) * (W - 2 * pad)

    def py(v):
        return H - pad - ((v - lo) / rng) * (H - 2 * pad)

    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(vals))
    zero = (
        f'<line x1="{pad}" y1="{py(0):.1f}" x2="{W - pad}" y2="{py(0):.1f}" '
        'stroke="#8A857B" stroke-width="1"/>'
    )
    line = f'<polyline points="{pts}" fill="none" stroke="#0B4F6C" stroke-width="1.6"/>'
    end = (
        f'<circle cx="{px(n - 1):.1f}" cy="{py(vals[-1]):.1f}" r="3" fill="#0B4F6C"/>'
        f'<text x="{px(n - 1) - 4:.1f}" y="{py(vals[-1]) - 6:.1f}" font-size="10" '
        f'fill="#0B4F6C" text-anchor="end">{vals[-1]:+.2f}R</text>'
    )
    return (
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'xmlns="http://www.w3.org/2000/svg">{zero}{line}{end}</svg>'
    )


def _empty_svg(w: int, h: int, text: str) -> str:
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" fill="none" '
        f'stroke="#D8D2C6"/><text x="{w // 2}" y="{h // 2}" font-size="11" '
        f'fill="#8A857B" text-anchor="middle">{html.escape(text)}</text></svg>'
    )


# --- Tables -----------------------------------------------------------------------

def _hit_rate_rows(df: pd.DataFrame, label: str) -> str:
    """A hit-rate table body; suppress the percentage for sparse (n<20) groups (spec §4)."""
    if df.empty:
        return f"<tr><td>{html.escape(label)}</td><td>—</td><td>—</td></tr>"
    rows = []
    for _, r in df.iterrows():
        rate = f"{r['hit_rate']:.0%}" if not r["sparse"] else f"— (n={int(r['n'])})"
        rows.append(
            f"<tr><td>{html.escape(str(r['group']))}</td>"
            f"<td class='num'>{int(r['n'])}</td><td class='num'>{rate}</td></tr>"
        )
    return "".join(rows)


def _metric(label: str, value: str) -> str:
    return (
        f"<div class='metric'><div class='mv'>{html.escape(value)}</div>"
        f"<div class='ml'>{html.escape(label)}</div></div>"
    )


# --- Composition ------------------------------------------------------------------

def render_html(
    view: pd.DataFrame,
    *,
    events_path: Path = ev.EVENTS_PATH,
    as_of: str | pd.Timestamp | datetime | None = None,
) -> str:
    """The full one-page HTML. Computes every exhibit from ``view`` + the event log."""
    chain = ev.verify(events_path)
    cal = analytics.calibration(view)
    pnl = analytics.pnl_summary(view)
    stats = analytics.process_stats(view, path=events_path, as_of=as_of)
    overall = analytics.hit_rate(view)
    by_metal = analytics.hit_rate(view, by="metal")
    by_dir = analytics.hit_rate(view, by="direction")

    gen = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    as_of_txt = "latest" if as_of is None else str(pd.Timestamp(as_of).date())
    n_calls = stats.get("n_calls", 0)

    hit_txt = "—"
    if not overall.empty:
        o = overall.iloc[0]
        hit_txt = f"{o['hit_rate']:.0%}" if not o["sparse"] else f"— (n={int(o['n'])})"

    metrics = "".join([
        _metric("calls", str(n_calls)),
        _metric("open / resolved", f"{stats.get('n_open', 0)} / {stats.get('n_resolved', 0)}"),
        _metric("total R", f"{pnl.total_R:+.2f}"),
        _metric("expectancy R", "—" if pnl.expectancy_R is None else f"{pnl.expectancy_R:+.2f}"),
        _metric("hit rate", hit_txt),
        _metric("Brier", "—" if cal.brier is None else f"{cal.brier:.3f}"),
    ])

    chain_line = (
        f"<span class='ok'>✓ {html.escape(chain.summary())}</span>" if chain.ok
        else f"<span class='bad'>✗ {html.escape(chain.summary())}</span>"
    )

    cf = stats.get("close_counterfactual", {})
    cf_line = ""
    if cf.get("n_with_counterfactual"):
        cf_line = (
            f"<p class='cf'>Discretionary closes ({cf['n']}): mean "
            f"{cf['mean_actual_R']:+.2f}R vs. {cf['mean_held_to_plan_R']:+.2f}R if held to "
            f"plan (edge {cf['edge_from_closing_R']:+.2f}R).</p>"
        )

    return f"""<!doctype html>
<meta charset="utf-8">
<title>Track record — {as_of_txt}</title>
<style>
 @page {{ size: A4; margin: 14mm; }}
 body {{ font-family: Georgia,'Times New Roman',serif; color:#1A1A17; margin:0; }}
 .kicker {{ font-family:Arial,sans-serif; font-size:10px; letter-spacing:.09em;
   text-transform:uppercase; color:#8A857B; }}
 h1 {{ font-size:22px; margin:2px 0 2px 0; }}
 .sub {{ font-family:Arial,sans-serif; font-size:11px; color:#55514A; margin-bottom:8px; }}
 .chain {{ font-family:Arial,sans-serif; font-size:11px; margin:6px 0 10px 0; }}
 .ok {{ color:#2C6E49; }} .bad {{ color:#A03217; font-weight:bold; }}
 .metrics {{ display:flex; gap:14px; border-top:1px solid #1A1A17;
   border-bottom:1px solid #1A1A17; padding:8px 0; margin-bottom:10px; }}
 .metric {{ flex:1; }} .mv {{ font-size:18px; font-variant-numeric:tabular-nums; }}
 .ml {{ font-family:Arial,sans-serif; font-size:9px; text-transform:uppercase;
   letter-spacing:.05em; color:#8A857B; }}
 .row {{ display:flex; gap:18px; margin-bottom:8px; }}
 .col {{ flex:1; }}
 h2 {{ font-size:12px; margin:4px 0; border-bottom:1px solid #D8D2C6; padding-bottom:2px; }}
 table {{ border-collapse:collapse; width:100%; font-family:Arial,sans-serif; font-size:10px; }}
 td,th {{ padding:2px 4px; border-bottom:1px solid #EFEBE3; text-align:left; }}
 .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
 .box {{ font-family:Arial,sans-serif; font-size:9.5px; color:#55514A;
   background:#EFEBE3; border-left:3px solid #B3ADA1; padding:6px 8px; margin-top:8px; }}
 .cf {{ font-family:Arial,sans-serif; font-size:10px; color:#55514A; }}
 .foot {{ font-family:Arial,sans-serif; font-size:9px; color:#8A857B; margin-top:8px; }}
</style>
<div class="kicker">Buy-side evidence · point-in-time · free public proxies</div>
<h1>Trade recommendation track record</h1>
<div class="sub">As of {as_of_txt} · generated {gen}</div>
<div class="chain">Integrity: {chain_line}</div>

<div class="metrics">{metrics}</div>

<div class="row">
  <div class="col">
    <h2>Calibration — stated confidence vs. realized frequency</h2>
    {_reliability_svg(cal.reliability, cal.brier, cal.n)}
  </div>
  <div class="col">
    <h2>Equity curve (cumulative R)</h2>
    {_equity_svg(pnl.equity_curve)}
  </div>
</div>

<div class="row">
  <div class="col">
    <h2>Hit rate — overall &amp; by metal</h2>
    <table><tr><th>group</th><th class="num">n</th><th class="num">hit</th></tr>
    {_hit_rate_rows(overall, "all")}{_hit_rate_rows(by_metal, "—")}</table>
  </div>
  <div class="col">
    <h2>Hit rate — by direction</h2>
    <table><tr><th>group</th><th class="num">n</th><th class="num">hit</th></tr>
    {_hit_rate_rows(by_dir, "—")}</table>
    {cf_line}
  </div>
</div>

<div class="box">
  <b>Marking conventions.</b> Entry is the next available close <i>after</i> a call is
  logged (never the same-day close, never a decision-moment price). Stops take precedence
  when both levels are in range within a period. Marking is <b>close-only</b> — intra-period
  ordering is unknowable, so this is a stated limitation, not a bug. All prices are
  <b>free public proxies</b>, not licensed marks. Calibration and hit rate count only
  market resolutions (target/stop/expiry); discretionary closes are reported separately.
  Groups with n&lt;20 show counts, not percentages.
</div>
<div class="foot">
  Source: append-only, hash-chained event log (git-committed) + point-in-time proxy store.
  This page is self-caveating by design; verify the chain with
  <code>python -m tracker.cli verify</code>.
</div>
"""


def render(
    view: pd.DataFrame,
    *,
    out_path: str | Path,
    events_path: Path = ev.EVENTS_PATH,
    as_of: str | pd.Timestamp | datetime | None = None,
) -> Path:
    """Write the report. ``.pdf`` → WeasyPrint if available, else fall back to ``.html``
    (written alongside) so the report is always produced. Returns the path written."""
    out = Path(out_path)
    doc = render_html(view, events_path=events_path, as_of=as_of)

    if out.suffix.lower() == ".pdf":
        try:
            from weasyprint import HTML  # lazy: optional [report] extra
        except ImportError:
            out = out.with_suffix(".html")
            out.write_text(doc, encoding="utf-8")
            return out
        out.parent.mkdir(parents=True, exist_ok=True)
        HTML(string=doc).write_pdf(str(out))
        return out

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out
