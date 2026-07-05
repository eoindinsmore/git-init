"""Indicator-lab orchestrator — runs the five gates and promotes/rejects (spec §1).

The FDR gate is applied **across the whole candidate×lag grid at once** (that is the
point: many candidates × many lags is a large multiple-testing family). Only lags
that survive Benjamini–Hochberg proceed to the out-of-sample, economic, and stability
gates. Everything that runs gets a scorecard — approved or in the graveyard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from quant.indicators import core
from quant.scorecard import SCORECARD_DIR, Scorecard, write_scorecard
from quant.signal import ScorecardRef, Signal, worst_case_lag
from quant.stats import benjamini_hochberg


@dataclass(frozen=True)
class LabConfig:
    max_lag: int = 6
    train_frac: float = 0.6  # scan (gate 1) uses the first train_frac of the sample
    fdr_q: float = 0.10
    min_train: int = 40  # OOS walk-forward minimum training window
    stability_window: int = 60
    min_oos_r2: float = 0.0  # OOS gate threshold (positive = beats prevailing mean)
    min_sharpe: float = 0.0  # economic gate threshold (net)
    max_flip_share: float = 0.35  # stability: reject if minority-sign share exceeds this
    cost_per_turnover: float = 0.0


@dataclass
class CandidateEval:
    candidate_id: str
    target_id: str
    best_lag: int | None
    gates: dict[str, core.GateOutcome]
    promoted: bool
    scan: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)
    signal: Signal | None = None
    scorecard: ScorecardRef | None = None

    @property
    def failed_gate(self) -> str | None:
        for name, out in self.gates.items():
            if not out.passed:
                return name
        return None


def _direction(beta: float, target_id: str) -> str:
    return f"high = {'bullish' if beta > 0 else 'bearish'} {target_id}"


def run_lab(
    target_id: str,
    target: pd.Series,
    candidates: dict[str, pd.Series],
    *,
    config: LabConfig | None = None,
    registry: dict | None = None,
    write_scorecards: bool = False,
    scorecard_dir: Path = SCORECARD_DIR,
    created_as_of: date | None = None,
) -> list[CandidateEval]:
    """Run every candidate against ``target`` through the five gates.

    Returns one :class:`CandidateEval` per candidate (promoted or not). With
    ``write_scorecards=True`` an approved/rejected scorecard JSON+HTML is written for
    each (``scorecard_dir`` overridable so tests don't touch real docs).
    """
    cfg = config or LabConfig()
    stamp = created_as_of or date.today()

    # --- Gate 1: scan each candidate on the training window only. ---
    scans: dict[str, pd.DataFrame] = {}
    grid_p: dict[tuple[str, int], float] = {}
    for cid, cser in candidates.items():
        df = pd.concat([target.rename("y"), cser.rename("x")], axis=1).dropna()
        n_train = int(len(df) * cfg.train_frac)
        train = df.iloc[:n_train]
        scan = core.lead_lag_scan(train["y"], train["x"], max_lag=cfg.max_lag)
        scans[cid] = scan
        for lag, row in scan.iterrows():
            if pd.notna(row["pvalue"]):
                grid_p[(cid, lag)] = float(row["pvalue"])

    # --- Gate 2: Benjamini–Hochberg across the WHOLE grid. ---
    if grid_p:
        fdr = benjamini_hochberg(pd.Series(grid_p), q=cfg.fdr_q)
    else:
        fdr = pd.DataFrame(columns=["pvalue", "qvalue", "reject"])

    results: list[CandidateEval] = []
    for cid, cser in candidates.items():
        scan = scans[cid]
        gates: dict[str, core.GateOutcome] = {}

        # surviving lags for this candidate
        surviving = [
            lag for (c, lag) in fdr.index if c == cid and bool(fdr.loc[(c, lag), "reject"])
        ] if not fdr.empty else []
        gates["scan"] = core.GateOutcome(
            passed=scan["pvalue"].notna().any(),
            detail={"min_pvalue": float(np.nanmin(scan["pvalue"])) if scan["pvalue"].notna().any()
                    else np.nan},
        )
        if not surviving:
            gates["fdr"] = core.GateOutcome(passed=False, detail={"surviving_lags": []})
            results.append(_finalize(cid, target_id, None, gates, scan, cser, target,
                                     cfg, registry, stamp, write_scorecards, scorecard_dir))
            continue

        # best surviving lag = smallest q-value among survivors
        best_lag = min(surviving, key=lambda lag: float(fdr.loc[(cid, lag), "qvalue"]))
        best_q = float(fdr.loc[(cid, best_lag), "qvalue"])
        gates["fdr"] = core.GateOutcome(
            passed=True,
            detail={"surviving_lags": surviving, "best_lag": best_lag, "qvalue": best_q},
        )
        beta = float(scan.loc[best_lag, "beta"])

        # --- Gate 3: OOS ---
        oos = core.oos_confirm(target, cser, lag=best_lag, min_train=cfg.min_train)
        gates["oos"] = core.GateOutcome(
            passed=(pd.notna(oos["oos_r2"]) and oos["oos_r2"] > cfg.min_oos_r2),
            detail={"oos_r2": oos["oos_r2"], "n_test": oos["n_test"]},
        )

        # --- Gate 4: economic significance ---
        econ = core.economic_significance(
            target, cser, lag=best_lag, beta_sign=beta,
            cost_per_turnover=cfg.cost_per_turnover, z_window=cfg.stability_window,
        )
        gates["economic"] = core.GateOutcome(
            passed=(pd.notna(econ["sharpe_net"]) and econ["sharpe_net"] > cfg.min_sharpe),
            detail=econ,
        )

        # --- Gate 5: stability ---
        stab = core.stability(target, cser, lag=best_lag, window=cfg.stability_window)
        minority = (1.0 - stab["dominant_share"]) if pd.notna(stab["dominant_share"]) else np.nan
        gates["stability"] = core.GateOutcome(
            passed=(pd.notna(minority) and minority <= cfg.max_flip_share),
            detail=stab,
        )

        results.append(_finalize(cid, target_id, best_lag, gates, scan, cser, target,
                                  cfg, registry, stamp, write_scorecards, scorecard_dir))
    return results


def _finalize(cid, target_id, best_lag, gates, scan, cser, target, cfg, registry,
              stamp, write_scorecards, scorecard_dir) -> CandidateEval:
    promoted = all(o.passed for o in gates.values())
    beta = float(scan.loc[best_lag, "beta"]) if best_lag is not None else np.nan

    signal = None
    if promoted:
        lag_days = 0
        if registry is not None:
            try:
                lag_days = worst_case_lag([cid], registry)
            except KeyError:
                lag_days = 0
        vals = cser.dropna()
        vals = pd.Series(vals.to_numpy(), index=pd.DatetimeIndex(vals.index), name=cid)
        signal = Signal(
            signal_id=f"{cid}__leads__{target_id}",
            values=vals,
            direction_convention=_direction(beta, target_id),
            target=target_id,
            provenance=[cid],
            construction=f"lead-lag k={best_lag}: {target_id}(t) ~ {cid}(t-{best_lag}), "
                         "HAC OLS; FDR-gated, OOS-confirmed.",
            publication_lag_days=lag_days,
            created_as_of=stamp,
        )

    ref = None
    if write_scorecards:
        fdr_detail = gates.get("fdr", core.GateOutcome(False)).detail
        sc = Scorecard(
            scorecard_id=f"{cid}__leads__{target_id}",
            kind="indicator",
            target=target_id,
            created_as_of=stamp,
            in_sample={
                "best_lag": float(best_lag) if best_lag is not None else float("nan"),
                "beta": beta,
                "qvalue": float(fdr_detail.get("qvalue", float("nan"))),
            },
            out_of_sample={
                "oos_r2": float(gates.get("oos", core.GateOutcome(False)).detail.get(
                    "oos_r2", float("nan"))),
                "sharpe_net": float(gates.get("economic", core.GateOutcome(False)).detail.get(
                    "sharpe_net", float("nan"))),
            },
            fdr_status=(f"q={fdr_detail.get('qvalue'):.3f} (BH at {cfg.fdr_q})"
                        if "qvalue" in fdr_detail else "did not survive BH FDR"),
            n_variants_tried=len(scan),
            stability_note=str(gates.get("stability", core.GateOutcome(False)).detail),
            provenance=[cid],
            notes=("PROMOTED" if promoted else f"REJECTED at gate: "
                   f"{next((n for n, o in gates.items() if not o.passed), '?')}"),
        )
        ref = write_scorecard(sc, approved=promoted, base_dir=scorecard_dir)
        if signal is not None:
            signal = signal.model_copy(update={"scorecard": ref})

    return CandidateEval(
        candidate_id=cid, target_id=target_id, best_lag=best_lag, gates=gates,
        promoted=promoted, scan=scan, signal=signal, scorecard=ref,
    )
