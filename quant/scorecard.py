"""Scorecards — the auto-generated evaluation artifact (spec §0.3).

Every indicator / nowcast / model / composite gets one: in-sample stats,
out-of-sample stats, FDR status, stability note, multiple-testing count. Nothing
enters the "approved" set without one, and rejected candidates get a scorecard
too — the graveyard in ``docs/scorecards/rejected/`` is part of the credibility
story (spec §1, §9).

This is the *skeleton*: the schema plus JSON + HTML writers. The stat bags
(``in_sample`` / ``out_of_sample``) are deliberately free-form ``dict[str,
float]`` so each module fills what is meaningful to it without a schema change.
PDF rendering (WeasyPrint, project step 9) is a later pass over ``render_html``.
"""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from quant.signal import ScorecardRef

# Repo-relative home for rendered scorecards. Approved at the top level; the
# rejected/ subdir is the indicator graveyard.
SCORECARD_DIR = Path(__file__).resolve().parents[1] / "docs" / "scorecards"
REJECTED_SUBDIR = "rejected"


class Scorecard(BaseModel):
    """A single evaluation record for a signal / model / nowcast."""

    model_config = ConfigDict(extra="forbid")

    scorecard_id: str
    kind: str  # "indicator" | "nowcast" | "backtest" | "composite" | "regime" | ...
    target: str  # what is being predicted/explained
    created_as_of: date

    # Free-form, module-specific stat bags. Examples:
    #   indicator in_sample: {"beta": .., "t_hac": .., "lead_k": ..}
    #   backtest out_of_sample: {"sharpe": .., "max_drawdown": .., "turnover": ..}
    in_sample: dict[str, float] = Field(default_factory=dict)
    out_of_sample: dict[str, float] = Field(default_factory=dict)

    fdr_status: str | None = None  # e.g. "q=0.03 (passes BH at 0.10)"
    n_variants_tried: int | None = None  # multiple-testing honesty (deflated-Sharpe input)
    stability_note: str | None = None  # e.g. "beta sign stable over 3 rolling windows"
    provenance: list[str] = Field(default_factory=list)  # registry series_ids used
    notes: str = ""


def _target_path(scorecard_id: str, *, approved: bool, base_dir: Path) -> Path:
    folder = base_dir if approved else base_dir / REJECTED_SUBDIR
    return folder / f"{scorecard_id}.json"


def write_scorecard(
    sc: Scorecard,
    *,
    approved: bool = True,
    base_dir: Path = SCORECARD_DIR,
) -> ScorecardRef:
    """Write ``sc`` as JSON (and a sibling ``.html``) and return a ``ScorecardRef``.

    ``approved=False`` routes to ``rejected/`` — the graveyard. The returned ref
    drops straight into :attr:`quant.signal.Signal.scorecard`. ``base_dir`` is
    overridable so tests never touch the real ``docs/`` tree.
    """
    json_path = _target_path(sc.scorecard_id, approved=approved, base_dir=base_dir)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(sc.model_dump_json(indent=2), encoding="utf-8")
    json_path.with_suffix(".html").write_text(render_html(sc), encoding="utf-8")

    # Store a repo-relative path when possible so refs are portable.
    try:
        rel = json_path.relative_to(Path(__file__).resolve().parents[1])
        path_str = rel.as_posix()
    except ValueError:
        path_str = json_path.as_posix()
    return ScorecardRef(scorecard_id=sc.scorecard_id, path=path_str)


def _rows(title: str, bag: dict[str, float]) -> str:
    if not bag:
        return ""
    body = "".join(
        f"<tr><td>{html.escape(k)}</td><td class='num'>{v:.4g}</td></tr>" for k, v in bag.items()
    )
    return f"<h2>{html.escape(title)}</h2><table>{body}</table>"


def render_html(sc: Scorecard) -> str:
    """A minimal, self-contained HTML rendering (no external assets).

    Deliberately plain — the WSJ/Dona-Wong report theme (repo ``DESIGN.md``) is
    applied when these are composed into the PDF report layer, not here.
    """
    meta = [
        ("kind", sc.kind),
        ("target", sc.target),
        ("created as-of", sc.created_as_of.isoformat()),
        ("FDR", sc.fdr_status or "—"),
        ("variants tried", "—" if sc.n_variants_tried is None else str(sc.n_variants_tried)),
        ("stability", sc.stability_note or "—"),
        ("provenance", ", ".join(sc.provenance) or "—"),
    ]
    meta_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>" for k, v in meta
    )
    notes = f"<h2>Notes</h2><p>{html.escape(sc.notes)}</p>" if sc.notes else ""
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Scorecard — {html.escape(sc.scorecard_id)}</title>
<style>
 body{{font-family:Georgia,serif;margin:2rem;max-width:46rem;color:#1a1a1a}}
 h1{{font-size:1.4rem}} h2{{font-size:1rem;margin-top:1.5rem;border-bottom:1px solid #ccc}}
 table{{border-collapse:collapse;width:100%;font-size:.9rem}}
 td{{padding:.25rem .5rem;border-bottom:1px solid #eee}}
 .num{{text-align:right;font-variant-numeric:tabular-nums}}
</style>
<h1>Scorecard — {html.escape(sc.scorecard_id)}</h1>
<table>{meta_rows}</table>
{_rows("In-sample", sc.in_sample)}
{_rows("Out-of-sample", sc.out_of_sample)}
{notes}
"""
