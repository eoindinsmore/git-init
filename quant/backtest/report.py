"""Backtest reporting — a Scorecard and a minimal HTML tearsheet (spec §3).

The deflated-Sharpe and bootstrap-p-value commentary is the honest headline: it says
whether the strategy would likely survive real capital given how many variants were
tried."""

from __future__ import annotations

import html
from datetime import date

from quant.backtest.core import BacktestResult
from quant.scorecard import Scorecard


def to_scorecard(
    result: BacktestResult,
    *,
    scorecard_id: str,
    target: str,
    provenance: list[str] | None = None,
    created_as_of: date | None = None,
) -> Scorecard:
    m = result.metrics
    dsr = m.get("deflated_sharpe", float("nan"))
    return Scorecard(
        scorecard_id=scorecard_id,
        kind="backtest",
        target=target,
        created_as_of=created_as_of or date.today(),
        in_sample={"sharpe_ann": m["sharpe_ann"], "ann_return": m["ann_return"],
                   "ann_vol": m["ann_vol"], "avg_turnover": m["avg_turnover"]},
        out_of_sample={"deflated_sharpe": dsr, "bootstrap_pvalue": m["bootstrap_pvalue"],
                       "max_drawdown": m["max_drawdown"], "hit_rate": m["hit_rate"]},
        n_variants_tried=result.n_variants_tried,
        stability_note=(f"deflated Sharpe {dsr:.2f} vs {result.n_variants_tried} variant(s)"),
        provenance=provenance or [],
        notes="Walk-forward, cost-aware; overlapping-return stats use bootstrap p-values.",
    )


def render_html(result: BacktestResult, *, title: str = "Backtest") -> str:
    m = result.metrics
    rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td class='num'>{v:.4g}</td></tr>"
        for k, v in m.items()
    )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
 body{{font-family:Georgia,serif;margin:2rem;max-width:40rem;color:#1a1a1a}}
 h1{{font-size:1.3rem}} table{{border-collapse:collapse;width:100%;font-size:.9rem}}
 td{{padding:.25rem .5rem;border-bottom:1px solid #eee}}
 .num{{text-align:right;font-variant-numeric:tabular-nums}}
 .muted{{color:#666;font-size:.85rem}}
</style>
<h1>{html.escape(title)}</h1>
<p class="muted">{result.n_variants_tried} variant(s) tried &middot; {m['n_obs']} periods
 &middot; {result.periods_per_year}/yr</p>
<table>{rows}</table>
<p class="muted">Deflated Sharpe and the bootstrap p-value are the survive-real-capital
 checks: they discount the headline Sharpe for multiple testing and return
 autocorrelation.</p>
"""
