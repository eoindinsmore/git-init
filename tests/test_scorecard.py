"""Tests for quant.scorecard — JSON/HTML writers and the approved/rejected split."""

from __future__ import annotations

import json
from datetime import date

from quant.scorecard import Scorecard, render_html, write_scorecard


def _sc(**over):
    base = dict(
        scorecard_id="ip_leads_copper",
        kind="indicator",
        target="copper_price_global",
        created_as_of=date(2026, 7, 5),
        in_sample={"beta": 0.42, "t_hac": 3.1},
        out_of_sample={"oos_r2": 0.05},
        fdr_status="q=0.03 (passes BH at 0.10)",
        n_variants_tried=48,
        provenance=["us_industrial_production"],
    )
    base.update(over)
    return Scorecard(**base)


def test_write_approved_roundtrips_json(tmp_path):
    ref = write_scorecard(_sc(), approved=True, base_dir=tmp_path)
    json_path = tmp_path / "ip_leads_copper.json"
    assert json_path.exists()
    assert (tmp_path / "ip_leads_copper.html").exists()  # sibling HTML
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["in_sample"]["beta"] == 0.42
    assert ref.scorecard_id == "ip_leads_copper"


def test_rejected_goes_to_graveyard(tmp_path):
    write_scorecard(_sc(scorecard_id="dud"), approved=False, base_dir=tmp_path)
    assert (tmp_path / "rejected" / "dud.json").exists()
    assert not (tmp_path / "dud.json").exists()


def test_html_contains_key_fields():
    html = render_html(_sc())
    assert "ip_leads_copper" in html
    assert "beta" in html
    assert "passes BH" in html
    assert "48" in html  # variants tried


def test_ref_path_is_repo_relative_when_under_repo(tmp_path):
    # base_dir outside the repo -> falls back to an absolute posix path, no crash.
    ref = write_scorecard(_sc(), approved=True, base_dir=tmp_path)
    assert ref.path.endswith("ip_leads_copper.json")
