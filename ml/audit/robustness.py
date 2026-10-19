"""Robustness analyses that need the frozen spec and the production outputs.

    .venv/Scripts/python ml/audit/robustness.py

Writes ml/reports/robustness_extra.json (cited by robustness.md):
  1. target sensitivity of the production ranking (adjusted vs reported KSI casualties vs KSI collisions)
  2. regression to the mean on the final holdout: top segments by raw history vs by model
  3. burden vs exposure-adjusted rate vs excess: how much the top lists overlap (M/A with AADF)
  4. assignment-rule sensitivity: KSI that depends on fallback matches
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import OUTPUTS, REPORTS  # noqa: E402
from blackspot.experiment import fit_predict, standard_specs  # noqa: E402
from blackspot.features import FORECAST_CUTOFF, HOLDOUT_CUTOFF, PRIMARY, Fold, build_frame  # noqa: E402
from blackspot.io_utils import setup_logging, write_json  # noqa: E402
from blackspot.steps import _context, _load_frozen  # noqa: E402

log = logging.getLogger("blackspot.robustness")


def top_overlap(a, b, k):
    ia = set(np.argsort(-a, kind="stable")[:k]); ib = set(np.argsort(-b, kind="stable")[:k])
    return len(ia & ib) / k


def main():
    setup_logging()
    spec = _load_frozen()
    ctx = _context()
    out: dict = {"frozen_spec_sha256": spec["sha256"]}
    chosen = [s for s in standard_specs(spec["lgbm_params"]) if s.name == spec["selected_model"]][0]

    # 1. target sensitivity of the production ranking
    f = Fold(FORECAST_CUTOFF)
    Xtr = build_frame(ctx.seg, ctx.ac, f.train_x, f.train_y, ctx.road)
    Xte = build_frame(ctx.seg, ctx.ac, f.test_x, None, ctx.road)
    preds = {}
    for t in ["adj_ksi_cas", "n_ksi_cas", "is_ksi_collision"]:
        preds[t], _ = fit_predict(chosen, Xtr, Xtr[f"y_{t}"].values, Xte, t)
    from scipy.stats import spearmanr
    out["target_sensitivity"] = {
        t: {"spearman_vs_primary": float(spearmanr(preds[PRIMARY], preds[t]).statistic),
            **{f"top{k}_overlap": top_overlap(preds[PRIMARY], preds[t], k) for k in (100, 500, 1000, 5000)}}
        for t in preds if t != PRIMARY}

    # 2. regression to the mean on the holdout fold (no fitting: history vs realised future)
    h = Fold(HOLDOUT_CUTOFF)
    X = build_frame(ctx.seg, ctx.ac, h.test_x, h.test_y, ctx.road)
    hist = X[f"h_{PRIMARY}"].values * (2 / 3)          # history per 2 years
    fut = X[f"y_{PRIMARY}"].values
    rtm = {}
    for k in (100, 500, 1000, 5000):
        top = np.argsort(-hist, kind="stable")[:k]
        rtm[f"top{k}_by_history"] = {"history_per_2y": float(hist[top].sum()), "future_2y": float(fut[top].sum()),
                                     "future_over_history": float(fut[top].sum() / hist[top].sum())}
    # same question for the frozen model's own holdout forecast: do its top segments deliver?
    Xh_tr = build_frame(ctx.seg, ctx.ac, h.train_x, h.train_y, ctx.road)
    p_h, _ = fit_predict(chosen, Xh_tr, Xh_tr[f"y_{PRIMARY}"].values, X, PRIMARY)
    for k in (100, 500, 1000, 5000):
        top = np.argsort(-p_h, kind="stable")[:k]
        rtm[f"top{k}_by_model"] = {"forecast_2y": float(p_h[top].sum()), "future_2y": float(fut[top].sum()),
                                   "future_over_forecast": float(fut[top].sum() / p_h[top].sum())}
    out["regression_to_the_mean_holdout"] = rtm

    # paired CIs on the sub-populations where the margin over crash counts is smallest
    from blackspot.evaluation import WeightedRanker, block_weights
    cls = ctx.seg.road_class.values
    pops = {"numbered": np.isin(cls, ["M", "A", "B"]), "hist1": X.h_n_coll.values > 0}
    sub = {}
    for name, m in pops.items():
        y, b = fut[m], ctx.blocks[m]
        rm = WeightedRanker(p_h[m]).prepare(y); rc = WeightedRanker(X.h_n_coll.values[m]).prepare(y)
        d10, d20 = [], []
        for w in block_weights(b, 300, seed=11):
            d10.append(rm.capture_fast(w, 0.10) - rc.capture_fast(w, 0.10))
            d20.append(rm.capture_fast(w, 0.20) - rc.capture_fast(w, 0.20))
        one = np.ones(m.sum())
        sub[name] = {"model_c10": rm.capture_fast(one, 0.10), "counts_c10": rc.capture_fast(one, 0.10),
                     "diff_c10_ci": [float(np.percentile(d10, 2.5)), float(np.percentile(d10, 97.5))],
                     "model_c20": rm.capture_fast(one, 0.20), "counts_c20": rc.capture_fast(one, 0.20),
                     "diff_c20_ci": [float(np.percentile(d20, 2.5)), float(np.percentile(d20, 97.5))]}
    out["holdout_model_vs_counts_subpopulations"] = sub

    # 3. burden vs exposure rate vs excess on the production output
    full = pd.read_parquet(OUTPUTS / "road_segments_v2_full.parquet")
    ma = full[full.exposure_available & full.ksi_per_100m_vkm_eb.notna()].reset_index(drop=True)
    over = {}
    for k in (100, 500):
        over[f"top{k}"] = {
            "burden_vs_rate": top_overlap(ma.blackspot_score.values, ma.ksi_per_100m_vkm_eb.values, k),
            "burden_vs_excess_exposure": top_overlap(ma.blackspot_score.values, ma.eb_excess_ksi_exposure.values, k),
            "burden_vs_excess_no_exposure": top_overlap(ma.blackspot_score.values, ma.eb_excess_ksi_history.values, k),
            "rate_vs_excess_exposure": top_overlap(ma.ksi_per_100m_vkm_eb.values, ma.eb_excess_ksi_exposure.values, k)}
    def prof(s):
        return {"median_aadf": float(s.aadf.median()), "median_length_m": float(s.length_m.median()),
                "share_motorway": float((s.road_class == "M").mean()),
                "median_n_crashes": float(s.n_crashes.median())}
    # rates on very short segments have tiny denominators; repeat with a minimum length
    ml_ = ma[ma.length_m >= 250].reset_index(drop=True)
    over_250 = {f"top{k}": {
        "burden_vs_rate": top_overlap(ml_.blackspot_score.values, ml_.ksi_per_100m_vkm_eb.values, k),
        "burden_vs_excess_exposure": top_overlap(ml_.blackspot_score.values, ml_.eb_excess_ksi_exposure.values, k)}
        for k in (100, 500)}
    out["exposure_interpretation_MA_with_aadf"] = {
        "n_segments": int(len(ma)), "overlap": over,
        "top500_by_burden": prof(ma.nlargest(500, "blackspot_score")),
        "top500_by_rate": prof(ma.nlargest(500, "ksi_per_100m_vkm_eb")),
        "top500_by_excess_exposure": prof(ma.nlargest(500, "eb_excess_ksi_exposure")),
        "length_ge_250m": {"n_segments": int(len(ml_)), "overlap": over_250,
                           "top500_by_burden": prof(ml_.nlargest(500, "blackspot_score")),
                           "top500_by_rate": prof(ml_.nlargest(500, "ksi_per_100m_vkm_eb"))}}
    out["single_event_flag"] = {"segments_flagged_nationally": int(full.single_event_flag.sum()),
                                "flagged_in_top500": int(full.nsmallest(500, "rank").single_event_flag.sum()),
                                "flagged_in_top5000": int(full.nsmallest(5000, "rank").single_event_flag.sum())}

    # 4. assignment-rule sensitivity
    from blackspot.snap import ASSIGN_PARQUET
    a = pd.read_parquet(ASSIGN_PARQUET)
    c = ctx.coll[["collision_index", "collision_year", PRIMARY]].merge(a[["collision_index", "match_type"]],
                                                                       on="collision_index")
    w = c[c.collision_year.isin(h.test_y.years)]
    out["assignment_sensitivity_holdout_target"] = (w.groupby("match_type")[PRIMARY].sum()
                                                    / w[PRIMARY].sum()).round(4).to_dict()
    write_json(out, REPORTS / "robustness_extra.json")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
