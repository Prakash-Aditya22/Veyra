"""Phase 3: what does "remove the largest collision" actually do to a top segment's forecast?

    .venv/Scripts/python ml/experiments/single_event_case.py         (~3 min, ~4 GB, no model fitting)

Phase 2 (ranking_stability.py, section D) re-scored each production top-1,000 segment with its
single largest 2023-25 collision removed and found that the flagged A57 Water Street segment's
forecast ROSE (6.43 -> 7.82). This script makes that result precise. It fits nothing:
  1. rebuilds the 2023-25 inference features with the production code (features.build_frame)
     and checks the saved production model (ml/outputs/explainability/production_lgbm.txt,
     verified in Phase 2) reproduces the stored blackspot_score for the top 1,000;
  2. repeats the Phase-2 intervention exactly and checks it reproduces the stored result;
  3. reports ranks two ways: simultaneous (every top-1,000 segment loses its largest collision,
     as Phase 2 did) and one-at-a-time (only this segment changes);
  4. for every flagged single-event segment in the top 1,000: the collisions, every feature
     before/after, the TreeSHAP decomposition before/after, and single-family substitutions;
  5. probes of the model surface on the top 1,000 (the Phase-2 statements about monotonicity),
     and the SHAP change by feature family for segments whose forecast rose vs fell.

Writes ml/reports/single_event_sensitivity.json, single_event_sensitivity_features.csv and the
optional, additive data/v2/extensions/segment_single_event_sensitivity_v2.csv (top 1,000). No
production file is written.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import BACKEND_DATA, OUTPUTS, REPORTS  # noqa: E402
from blackspot.explain import label  # noqa: E402
from blackspot.features import FORECAST_CUTOFF, Fold, Window, build_frame, history_features  # noqa: E402
from blackspot.io_utils import setup_logging, write_csv, write_json  # noqa: E402
from blackspot.stability import national_ranks, segment_id_order  # noqa: E402
from blackspot.steps import _context  # noqa: E402

log = logging.getLogger("blackspot.single_event")
MODEL = OUTPUTS / "explainability" / "production_lgbm.txt"
TOP = 1000

# history features grouped by what they count; used to read the SHAP decomposition
FAMILIES = {
    "collision counts": ["h_n_coll", "h_last_n_coll", "h_years_with_crash", "h_coll_per_km"],
    "all-casualty count": ["h_n_cas"],
    "serious/fatal counts": ["h_adj_ksi_cas", "h_n_ksi_cas", "h_n_fatal_cas", "h_is_ksi_collision",
                             "h_is_fatal_collision", "h_last_adj_ksi_cas", "h_adj_ksi_per_km"],
    "serious/fatal share": ["h_ksi_share"],
    "crash circumstances": ["h_share_junction", "h_share_dark", "h_share_urban", "h_share_wet",
                            "h_speed_median", "h_share_single_vehicle"],
}


def family(f: str) -> str:
    for k, v in FAMILIES.items():
        if f in v:
            return k
    return "road and context (values unchanged)"


def one_at_a_time_rank(prod: np.ndarray, tie: np.ndarray, i: int, new: float) -> int:
    """National rank of segment i if only its forecast became `new` (ties by segment_id, as production)."""
    better = (prod > new) | ((prod == new) & (tie < tie[i]))
    better[i] = False
    return int(better.sum()) + 1


def main():
    setup_logging()
    from lightgbm import Booster
    model = Booster(model_file=str(MODEL))
    # the model was fitted on a bare array (feature names Column_0..); its column order is recorded here
    cols = json.loads((MODEL.parent / "production_model_verification.json").read_text())["features"]
    if len(cols) != model.num_feature():
        raise RuntimeError("feature list does not match the saved production model")

    ctx = _context(with_aadf=False)
    fold = Fold(FORECAST_CUTOFF)                      # inference features 2023-25 -> forecast 2026-27
    X = build_frame(ctx.seg, ctx.ac, fold.test_x, None, ctx.road)
    full = pd.read_parquet(OUTPUTS / "road_segments_v2_full.parquet",
                           columns=["segment_id", "blackspot_score", "rank", "single_event_flag", "location"])
    full = full.set_index("segment_id").reindex(ctx.seg.segment_id.values)
    prod, prod_rank = full.blackspot_score.values, full["rank"].values
    tie = segment_id_order(ctx.seg.segment_id.values)
    top = np.flatnonzero(prod_rank <= TOP)

    X0 = X.loc[top, cols].values.astype(np.float32)
    p0 = model.predict(X0)
    d0 = float(np.max(np.abs(p0 - prod[top])))
    if d0 > 1e-6:
        raise RuntimeError(f"saved production model does not reproduce blackspot_score ({d0})")

    # the Phase-2 intervention, unchanged: largest 2023-25 collision by adjusted KSI (ties: collision_index)
    ac = ctx.ac[ctx.ac.collision_year.isin(fold.test_x.years)]
    own = ac[ac.seg_idx.isin(top)].sort_values(["seg_idx", "adj_ksi_cas", "collision_index"],
                                               ascending=[True, False, True])
    biggest = own.drop_duplicates("seg_idx").set_index("seg_idx")
    ac_red = ctx.ac[~ctx.ac.collision_index.isin(biggest.collision_index)]
    h_red = history_features(ac_red, ctx.seg, Window(fold.test_x.start, fold.test_x.end))
    hcols = [c for c in cols if c.startswith("h_")]
    X1f = X.loc[top, cols].copy()
    X1f[hcols] = h_red.loc[top, hcols].values.astype(np.float32)
    X1 = X1f.values.astype(np.float32)
    p1 = model.predict(X1)

    phase2 = pd.read_csv(REPORTS / "ranking_stability_drop_largest_collision.csv").set_index("segment_id")
    ids = ctx.seg.segment_id.values[top]
    d1 = float(np.max(np.abs(np.round(p1, 4) - phase2.loc[ids, "forecast_without_largest_collision"].values)))
    if d1 > 1e-4:
        raise RuntimeError(f"intervention does not reproduce the Phase-2 result ({d1})")

    allp = prod.copy(); allp[top] = p1
    rank_sim = national_ranks(allp, tie)[top]
    rank_one = np.array([one_at_a_time_rank(prod, tie, i, v) for i, v in zip(top, p1)])
    if not np.array_equal(rank_sim, phase2.loc[ids, "rank_without_largest_collision"].values):
        raise RuntimeError("simultaneous ranks do not reproduce the Phase-2 result")

    c0 = model.predict(X0, pred_contrib=True)[:, :-1]
    c1 = model.predict(X1, pred_contrib=True)[:, :-1]
    dphi = pd.DataFrame(c1 - c0, columns=cols)
    fam = dphi.T.groupby([family(c) for c in cols]).sum().T
    rose, fell = p1 > p0, p1 < p0
    by_family = pd.DataFrame({
        "family": fam.columns,
        "mean_change_log_rose": fam[rose].mean().values,
        "mean_change_log_fell": fam[fell].mean().values,
        "share_of_rising_segments_where_family_raised_forecast": (fam[rose] > 0).mean().values})
    summary = {
        "what": "production model re-scored with each top-1,000 segment's largest 2023-25 collision "
                "(by adjusted KSI) removed from its OWN history features; road and context features "
                "(including crashes on nearby roads and elsewhere on the stretch) are unchanged; no refit",
        "score_units": "expected DfT severity-adjusted KSI casualties on the segment, 2026-2027 total (two years)",
        "rank_direction": "rank 1 = highest forecast; a smaller rank number means higher priority",
        "production_model_reproduced_max_abs_diff": d0,
        "phase2_result_reproduced_max_abs_diff": d1,
        "top_n": TOP,
        "share_forecast_rose": float(rose.mean()), "share_forecast_fell": float(fell.mean()),
        "share_forecast_unchanged": float((p1 == p0).mean()),
        "median_rank_change_simultaneous": float(np.median(rank_sim - prod_rank[top])),
        "median_rank_change_one_at_a_time": float(np.median(rank_one - prod_rank[top])),
        "share_leaving_top1000_simultaneous": float((rank_sim > TOP).mean()),
        "share_leaving_top1000_one_at_a_time": float((rank_one > TOP).mean()),
        "largest_collision_adj_ksi_median_rose": float(np.median(biggest.reindex(top).adj_ksi_cas.values[rose])),
        "largest_collision_adj_ksi_median_fell": float(np.median(biggest.reindex(top).adj_ksi_cas.values[fell])),
        "family_change_rose_vs_fell": by_family.round(4).to_dict(orient="records"),
    }

    # ---- probes of the model surface (one input changed, everything else fixed; not realistic states)
    per_km = 1000.0 / ctx.seg.length_m.clip(lower=50).values[top]
    j = {c: cols.index(c) for c in cols}
    probes = {}
    P = X0.copy(); P[:, j["h_adj_ksi_cas"]] += 5; P[:, j["h_adj_ksi_per_km"]] += 5 * per_km
    q = model.predict(P)
    probes["add_5_adjusted_ksi_casualties"] = {"inputs_changed": ["h_adj_ksi_cas", "h_adj_ksi_per_km"],
                                               "share_up": float((q > p0).mean()), "share_down": float((q < p0).mean())}
    P = X0.copy(); P[:, j["h_ksi_share"]] = np.clip(P[:, j["h_ksi_share"]] - 0.1, 0, None)
    q = model.predict(P)
    probes["lower_ksi_share_by_0.1"] = {"inputs_changed": ["h_ksi_share"],
                                        "share_up": float((q > p0).mean()), "share_down": float((q < p0).mean())}
    P = X0.copy(); P[:, j["h_n_coll"]] -= 1; P[:, j["h_coll_per_km"]] -= per_km
    q = model.predict(P)
    probes["one_fewer_collision_count_only"] = {"inputs_changed": ["h_n_coll", "h_coll_per_km"],
                                                "share_up": float((q > p0).mean()),
                                                "share_down_or_unchanged": float((q <= p0).mean())}
    summary["model_surface_probes_top1000"] = probes

    # ---- flagged single-event segments in the top 1,000
    cases, rows = [], []
    for k in np.flatnonzero(full.single_event_flag.values[top]):
        i = top[k]
        sid = ctx.seg.segment_id.values[i]
        mine = ac[ac.seg_idx == i].sort_values(["adj_ksi_cas"], ascending=False)
        coll = mine[["collision_year", "n_cas", "n_ksi_cas", "adj_ksi_cas", "n_fatal_cas", "collision_severity"]]
        b0, b1 = X0[k], X1[k]
        subs = {}
        for name, fs in FAMILIES.items():
            idx = [j[f] for f in fs if f in j]
            a = b0.copy(); a[idx] = b1[idx]
            r = b1.copy(); r[idx] = b0[idx]
            subs[name] = {"before_with_only_this_family_changed": float(model.predict(a[None])[0]),
                          "after_with_only_this_family_restored": float(model.predict(r[None])[0])}
        for f in cols:
            rows.append({"segment_id": sid, "feature": f, "label": label(f), "family": family(f),
                         "value_before": float(b0[j[f]]), "value_after": float(b1[j[f]]),
                         "shap_log_before": float(c0[k, j[f]]), "shap_log_after": float(c1[k, j[f]]),
                         "shap_log_change": float(c1[k, j[f]] - c0[k, j[f]])})
        cases.append({
            "segment_id": sid, "location": full.location.values[i],
            "rank": int(prod_rank[i]), "forecast": float(p0[k]), "forecast_without_largest_collision": float(p1[k]),
            "rank_without_largest_collision_simultaneous": int(rank_sim[k]),
            "rank_without_largest_collision_one_at_a_time": int(rank_one[k]),
            "log_change": float(np.log(p1[k] / p0[k])),
            "shap_change_by_family": {f: round(float(v), 4) for f, v in fam.iloc[k].items()},
            "collisions_2023_25": coll.to_dict(orient="records"),
            "single_family_substitutions": subs})
    summary["single_event_segments_in_top1000"] = cases

    # ---- how far outside the model's learnt range are such events? (tree split thresholds)
    trees = model.trees_to_dataframe()
    trees = trees[trees.split_feature.notna()]
    feat = trees.split_feature.str.replace("Column_", "").astype(int).map(lambda i: cols[i])
    summary["largest_split_threshold"] = {f: float(trees.threshold[feat == f].max())
                                          for f in ["h_n_cas", "h_adj_ksi_cas", "h_n_ksi_cas", "h_last_adj_ksi_cas",
                                                    "h_adj_ksi_per_km", "h_n_coll"]}
    trw = ctx.ac[ctx.ac.collision_year.isin(fold.train_x.years)]
    summary["training_feature_window"] = str(fold.train_x)
    summary["training_window_assigned_collisions"] = {
        "n": int(len(trw)), "max_casualties_in_one_collision": int(trw.n_cas.max()),
        "collisions_with_20_or_more_casualties": int((trw.n_cas >= 20).sum()),
        "max_adjusted_ksi_in_one_collision": float(trw.adj_ksi_cas.max())}
    stab = BACKEND_DATA / "v2" / "extensions" / "segment_stability_v2.csv"
    if stab.exists():
        s = pd.read_csv(stab).set_index("segment_id")
        for c in cases:
            if c["segment_id"] in s.index:
                c["stability"] = {k: (v.item() if hasattr(v, "item") else v)
                                  for k, v in s.loc[c["segment_id"]].items()}

    write_json(summary, REPORTS / "single_event_sensitivity.json")
    write_csv(pd.DataFrame(rows).round(6), REPORTS / "single_event_sensitivity_features.csv")
    # optional backend extension: both rank definitions, so the UI never has to guess which one it holds
    ext = pd.DataFrame({
        "segment_id": ids, "rank": prod_rank[top], "forecast": np.round(p0, 4),
        "forecast_without_largest_collision": np.round(p1, 4),
        "rank_without_largest_collision_one_at_a_time": rank_one,
        "rank_without_largest_collision_simultaneous": rank_sim,
        "largest_collision_adj_ksi": np.round(biggest.reindex(top).adj_ksi_cas.values, 4),
        "single_event_flag": full.single_event_flag.values[top]}).sort_values("rank")
    write_csv(ext, BACKEND_DATA / "v2" / "extensions" / "segment_single_event_sensitivity_v2.csv")
    log.info("done: %s", {c["segment_id"]: (c["forecast"], c["forecast_without_largest_collision"]) for c in cases})


if __name__ == "__main__":
    main()
