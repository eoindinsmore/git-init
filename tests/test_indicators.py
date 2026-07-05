"""Tests for quant.indicators — the five-gate leading-indicator lab.

The credibility claims we verify: a genuine leading indicator passes all gates and
becomes a Signal + approved scorecard; pure-noise candidates are caught by the FDR
gate (multiple-testing control) and land in the graveyard.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from quant.indicators import lead_lag_scan, run_lab
from quant.indicators.lab import LabConfig


def _idx(n):
    return pd.date_range("2000-01-31", periods=n, freq="ME")


def _make_leader(n=300, lag=2, beta=0.8, noise=0.3, seed=0):
    """A candidate that genuinely leads the target by `lag` periods."""
    rng = np.random.default_rng(seed)
    idx = _idx(n)
    cand = pd.Series(rng.normal(size=n), index=idx)
    target = beta * cand.shift(lag) + pd.Series(rng.normal(scale=noise, size=n), index=idx)
    return target, cand


def test_lead_lag_scan_finds_the_lag():
    target, cand = _make_leader(lag=3, beta=1.0, noise=0.2)
    scan = lead_lag_scan(target, cand, max_lag=6)
    # The true lead (3) should have the largest |t| and a positive beta.
    best = scan["t_hac"].abs().idxmax()
    assert best == 3
    assert scan.loc[3, "beta"] > 0


def test_genuine_indicator_is_promoted():
    target, cand = _make_leader(lag=2, beta=0.9, noise=0.25, seed=1)
    cfg = LabConfig(max_lag=4, train_frac=0.6, min_train=40, stability_window=40)
    evals = run_lab("target", target, {"leader": cand}, config=cfg)
    ev = evals[0]
    assert ev.promoted, f"failed at gate {ev.failed_gate}: {ev.gates}"
    assert ev.best_lag == 2
    assert ev.signal is not None
    assert ev.signal.provenance == ["leader"]
    assert "bullish" in ev.signal.direction_convention


def test_pure_noise_is_rejected_by_fdr():
    rng = np.random.default_rng(7)
    idx = _idx(300)
    target = pd.Series(rng.normal(size=300), index=idx)
    # 12 independent noise candidates — the FDR gate should let ~none through.
    candidates = {f"noise_{i}": pd.Series(rng.normal(size=300), index=idx) for i in range(12)}
    cfg = LabConfig(max_lag=6, fdr_q=0.10, min_train=40, stability_window=40)
    evals = run_lab("target", target, candidates, config=cfg)
    promoted = [e.candidate_id for e in evals if e.promoted]
    assert promoted == []  # multiple-testing control holds the line


def test_mixed_pool_promotes_only_the_real_one():
    rng = np.random.default_rng(3)
    idx = _idx(300)
    target, leader = _make_leader(lag=2, beta=0.9, noise=0.25, seed=3)
    candidates = {"leader": leader}
    for i in range(8):
        candidates[f"noise_{i}"] = pd.Series(rng.normal(size=300), index=idx)
    cfg = LabConfig(max_lag=4, fdr_q=0.10, min_train=40, stability_window=40)
    evals = run_lab("target", target, candidates, config=cfg)
    promoted = {e.candidate_id for e in evals if e.promoted}
    noise_promoted = {c for c in promoted if c.startswith("noise")}
    # The real leader is found; noise survival is heavily suppressed (FDR controls the
    # rate, not to exactly zero — the pure-noise test shows zero when no signal exists).
    assert "leader" in promoted
    assert len(noise_promoted) <= 1


def test_scorecards_written_to_split_dirs(tmp_path):
    target, leader = _make_leader(lag=2, beta=0.9, noise=0.25, seed=5)
    rng = np.random.default_rng(9)
    candidates = {"leader": leader, "dud": pd.Series(rng.normal(size=300), index=_idx(300))}
    cfg = LabConfig(max_lag=4, min_train=40, stability_window=40)
    evals = run_lab("target", target, candidates, config=cfg,
                    write_scorecards=True, scorecard_dir=tmp_path,
                    created_as_of=date(2026, 7, 5))
    promoted = {e.candidate_id for e in evals if e.promoted}
    assert "leader" in promoted
    assert (tmp_path / "leader__leads__target.json").exists()  # approved
    assert (tmp_path / "rejected" / "dud__leads__target.json").exists()  # graveyard
    # Promoted signal carries its scorecard ref.
    leader_ev = next(e for e in evals if e.candidate_id == "leader")
    assert leader_ev.signal.scorecard is not None
