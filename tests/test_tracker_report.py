"""Tests for the one-page track-record report (spec §5).

Confirms the HTML is self-contained and self-caveating (chain line, conventions box,
inline SVG exhibits) and that ``render`` writes a file and degrades PDF→HTML gracefully.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from quant import store
from tracker import analytics, calls, marking, report

_REG_YAML = """\
- series_id: cu_proxy
  source: test
  source_code: CU
  name: Copper proxy
  unit: USD/t
  frequency: D
  sa_status: NSA
  tags: {metal: copper, category: price_proxy}
  caveats: Free proxy — not a licensed price.
"""


@pytest.fixture
def env(tmp_path):
    reg = tmp_path / "registry"
    reg.mkdir()
    (reg / "cu.yaml").write_text(_REG_YAML, encoding="utf-8")
    dates = pd.bdate_range("2026-02-02", periods=21)
    values = [100.0] * len(dates)
    values[5] = 111.0
    df = pd.DataFrame({
        "series_id": "cu_proxy", "date": dates, "value": values, "as_of": dates,
        "source": "test", "frequency": "D", "unit": "USD/t", "last_updated": dates,
    })
    store_path = tmp_path / "facts.parquet"
    store.write_observations(df, path=store_path)
    events_path = tmp_path / "events.jsonl"
    calls.new_call(
        instrument="cu_proxy", expression="outright", metal="copper", direction="long",
        target=110.0, stop=90.0, horizon_days=30, confidence=0.6,
        thesis="Copper proxy call driving the one-page report test here.",
        path=events_path, store_path=store_path, registry_dir=reg,
        _now=datetime(2026, 2, 2, 12, 0, tzinfo=UTC),
    )
    marking.mark_open_calls("2026-03-30", path=events_path, store_path=store_path)
    view = analytics.build_view(as_of="2026-03-30", path=events_path, store_path=store_path)
    return view, events_path


def test_render_html_has_key_sections(env):
    view, events_path = env
    doc = report.render_html(view, events_path=events_path, as_of="2026-03-30")
    assert "Trade recommendation track record" in doc
    assert "Marking conventions" in doc
    assert "Brier" in doc
    assert "hash chain OK" in doc  # the verification line
    assert "<svg" in doc  # inline calibration/equity charts, no external assets
    assert "http" not in doc.replace("http://www.w3.org/2000/svg", "")  # no external fetches


def test_render_writes_html_file(env, tmp_path):
    view, events_path = env
    out = report.render(view, out_path=tmp_path / "tr.html", events_path=events_path)
    assert out.exists() and out.suffix == ".html"


def test_render_pdf_falls_back_to_html_when_weasyprint_absent(env, tmp_path, monkeypatch):
    view, events_path = env
    # Simulate WeasyPrint not installed: the import inside render() raises ImportError.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "weasyprint":
            raise ImportError("no weasyprint")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = report.render(view, out_path=tmp_path / "tr.pdf", events_path=events_path)
    assert out.suffix == ".html" and out.exists()  # graceful degrade, report still produced


def test_render_empty_view_does_not_crash(tmp_path):
    doc = report.render_html(pd.DataFrame(), events_path=tmp_path / "none.jsonl")
    assert "Trade recommendation track record" in doc and "no market-resolved" in doc
