"""Tests for the append-only trade-hypothesis tracker (charter constraint #6)."""

from __future__ import annotations

from datetime import datetime

from tracker import store
from tracker.schema import Direction, Hypothesis, Status


def _h(hid, **over):
    base = dict(
        hypothesis_id=hid,
        created_as_of=datetime(2026, 7, 5, 12, 0, 0),
        instrument="copper_price_global",
        thesis="test",
    )
    base.update(over)
    return Hypothesis(**base)


def test_append_and_read_preserves_order(tmp_path):
    p = tmp_path / "hyp.jsonl"
    store.append(_h("a"), p)
    store.append(_h("b"), p)
    recs = store.read_all(p)
    assert [r.hypothesis_id for r in recs] == ["a", "b"]


def test_append_is_additive_not_rewrite(tmp_path):
    p = tmp_path / "hyp.jsonl"
    store.append(_h("a"), p)
    store.append(_h("a", thesis="second copy"), p)  # same id appended again
    # Both lines are kept — the log is immutable/append-only.
    assert len(store.read_all(p)) == 2


def test_current_view_folds_supersede(tmp_path):
    p = tmp_path / "hyp.jsonl"
    store.append(_h("a", status=Status.DRAFT), p)
    store.append(
        _h("a2", supersedes="a", status=Status.OPEN, direction=Direction.LONG),
        p,
    )
    view = store.current_view(p)
    # Only the latest (a2) survives the fold; the file still has both lines.
    assert list(view["hypothesis_id"]) == ["a2"]
    assert len(store.read_all(p)) == 2
    assert view.iloc[0]["status"] == "open"


def test_immutability_frozen():
    h = _h("a")
    try:
        h.thesis = "changed"
        raised = False
    except Exception:
        raised = True
    assert raised  # frozen model — cannot mutate in place


def test_empty_view(tmp_path):
    assert store.current_view(tmp_path / "none.jsonl").empty
