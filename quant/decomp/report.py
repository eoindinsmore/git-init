"""Decomposition outputs — a tidy contributions frame for the app to chart, plus a
minimal self-contained HTML one-pager (PDF deferred to project step 9).

The stacked-bar contributions and the residual answer "why did the price move";
the orthogonalization order and any missing drivers are stated explicitly so the
tool's limits are visible on the page (spec §4, §9).
"""

from __future__ import annotations

import html

import pandas as pd

from quant.decomp.core import DRIFT, RESIDUAL
from quant.decomp.run import DecompRun


def contributions_frame(run: DecompRun) -> pd.DataFrame:
    """Tidy ``[component, label, contribution]`` frame, drivers in orthogonalization
    order then drift then residual — ready for a stacked bar in the app."""
    c = run.result.contributions
    rows = []
    for sid in run.result.order:
        rows.append({"component": sid, "label": run.spec.label_of(sid),
                     "contribution": float(c.get(sid, 0.0))})
    rows.append({"component": DRIFT, "label": DRIFT, "contribution": float(c.get(DRIFT, 0.0))})
    rows.append({"component": RESIDUAL, "label": RESIDUAL,
                 "contribution": float(c.get(RESIDUAL, 0.0))})
    return pd.DataFrame(rows)


def render_html(run: DecompRun) -> str:
    """One-page HTML: headline change, contribution table, betas, and the explicit
    orthogonalization order + missing-driver caveat."""
    r = run.result
    unit = "log return" if run.spec.return_kind == "log" else "% return"
    frame = contributions_frame(run)
    contrib_rows = "".join(
        f"<tr><td>{html.escape(row.label)}</td>"
        f"<td class='num'>{row.contribution:+.4f}</td></tr>"
        for row in frame.itertuples()
    )
    beta_rows = "".join(
        f"<tr><td>{html.escape(run.spec.label_of(name) if name != 'const' else 'const')}</td>"
        f"<td class='num'>{r.betas[name]:+.3f}</td>"
        f"<td class='num'>{r.tvalues[name]:+.2f}</td>"
        f"<td class='num'>{r.sign_flips.get(name, 0)}</td></tr>"
        for name in r.betas.index
    )
    order_txt = " → ".join(run.spec.label_of(s) for s in r.order) or "(none)"
    missing_txt = (
        "<p class='warn'>Declared but not yet in the store (see data-gap register): "
        + ", ".join(html.escape(m) for m in run.missing) + ".</p>"
        if run.missing else ""
    )
    span = ""
    if r.window:
        span = f"{r.window[0].date()} → {r.window[1].date()}"
    asof = f"as of {run.as_of.date()}" if run.as_of is not None else "current-best view"

    return f"""<!doctype html>
<meta charset="utf-8">
<title>Decomposition — {html.escape(run.spec.target_label)}</title>
<style>
 body{{font-family:Georgia,serif;margin:2rem;max-width:48rem;color:#1a1a1a}}
 h1{{font-size:1.4rem}} h2{{font-size:1rem;margin-top:1.4rem;border-bottom:1px solid #ccc}}
 table{{border-collapse:collapse;width:100%;font-size:.9rem}}
 td,th{{padding:.25rem .5rem;border-bottom:1px solid #eee;text-align:left}}
 .num{{text-align:right;font-variant-numeric:tabular-nums}}
 .warn{{color:#8a1f1f;font-size:.85rem}} .muted{{color:#666;font-size:.85rem}}
</style>
<h1>Why did {html.escape(run.spec.target_label)} move?</h1>
<p class="muted">{span} &middot; {asof} &middot; {unit}s &middot; R&sup2;={r.rsquared:.2f}
 &middot; n={r.nobs}</p>
<p class="muted">Orthogonalization order: {html.escape(order_txt)}
 (sequential economic residualization; contributions are additive).</p>
{missing_txt}
<h2>Contribution to the price change</h2>
<table><tr><th>Component</th><th class='num'>Contribution</th></tr>{contrib_rows}
<tr><td><b>Actual (total)</b></td><td class='num'><b>{r.actual:+.4f}</b></td></tr></table>
<h2>Betas (HAC t-stats, rolling sign-flips)</h2>
<table><tr><th>Driver</th><th class='num'>&beta;</th><th class='num'>t</th>
<th class='num'>flips</th></tr>
{beta_rows}</table>
"""
