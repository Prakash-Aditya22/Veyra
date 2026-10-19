"""Phase 4: how stable is the 2026-27 ranking?

    .venv/Scripts/python ml/experiments/ranking_stability.py --boot 30 --seeds 10     (~1 h)
    .venv/Scripts/python ml/experiments/ranking_stability.py --boot 2 --seeds 1      (benchmark)

  A. spatial-block bootstrap: the production training pair (2021-23 -> 2024-25) is
     reweighted by resampled 50 km blocks; the frozen LightGBM spec is refitted and
     2026-27 is re-forecast from the same 2023-25 inference features.
  B. seed-only refits: same data, different LightGBM random_state (subsample/colsample).
  C. historical-window sensitivity: 2026-27 rankings from the phase-2 window strategies
     (ml/interim/windows/forecast_preds_2025.npz, if present).
  D. observation dependence: for the production top 1,000, the production model re-scores
     each segment with its single largest history collision removed.

Writes ml/outputs/stability/*, ml/reports/ranking_stability_*.csv/json and
data/v2/extensions/segment_stability_v2.csv. The production files are not modified.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import BACKEND_DATA, INTERIM, OUTPUTS, REPORTS, SEED  # noqa: E402
from blackspot.experiment import _cols  # noqa: E402
from blackspot.features import FORECAST_CUTOFF, PRIMARY, Fold, Window, build_frame, history_features  # noqa: E402
from blackspot.io_utils import setup_logging, write_csv, write_json  # noqa: E402
from blackspot.models import fit_lgbm  # noqa: E402
from blackspot.stability import (block_bootstrap_weights, membership_frequency, national_ranks,  # noqa: E402
                                 order_preserved, rank_summary, segment_id_order, stability_class, topk_overlap)
from blackspot.steps import _context, _load_frozen  # noqa: E402

log = logging.getLogger("blackspot.stability")
OUT = OUTPUTS / "stability"
EXT = BACKEND_DATA / "v2" / "extensions"
SHAP_SAMPLE = 5000


def fit(Xtr, ytr, params, w=None, seed=SEED):
    from lightgbm import LGBMRegressor
    from blackspot.models import LGBM_DEFAULT
    p = dict(LGBM_DEFAULT); p.update(params); p["random_state"] = seed
    return LGBMRegressor(**p).fit(Xtr, ytr, sample_weight=w)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=30)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--reuse-preds", action="store_true",
                    help="reuse replicate predictions saved in ml/interim/stability_preds.npz")
    ap.add_argument("--attr-boot", type=int, default=8,
                    help="when reusing predictions saved without SHAP importances: refit this many of the same "
                         "bootstrap replicates (identical weights) for attribution stability")
    args = ap.parse_args(argv)
    setup_logging()
    OUT.mkdir(parents=True, exist_ok=True); EXT.mkdir(parents=True, exist_ok=True)
    spec = _load_frozen()
    params = spec["lgbm_params"]
    ctx = _context(with_aadf=False)
    fold = Fold(FORECAST_CUTOFF)
    Xtr_f = build_frame(ctx.seg, ctx.ac, fold.train_x, fold.train_y, ctx.road)
    Xte_f = build_frame(ctx.seg, ctx.ac, fold.test_x, None, ctx.road)
    cols = _cols(Xtr_f, ("history", "road", "context"))
    Xtr = Xtr_f[cols].values.astype(np.float32); ytr = Xtr_f[f"y_{PRIMARY}"].values
    Xte = Xte_f[cols].values.astype(np.float32)
    n = len(Xte)
    full = pd.read_parquet(OUTPUTS / "road_segments_v2_full.parquet",
                           columns=["segment_id", "blackspot_score", "rank", "single_event_flag"])
    full = full.set_index("segment_id").reindex(ctx.seg.segment_id.values)
    prod_pred, prod_rank = full.blackspot_score.values, full["rank"].values
    tie = segment_id_order(ctx.seg.segment_id.values)
    if not np.array_equal(national_ranks(prod_pred, tie), prod_rank):
        raise RuntimeError("rank helper does not reproduce the production ranks")

    rng = np.random.default_rng(SEED)
    shap_rows = rng.choice(n, SHAP_SAMPLE, replace=False)
    preds, kinds, shap_imp, times = [], [], [], []
    plan = [("bootstrap", i) for i in range(args.boot)] + [("seed", i) for i in range(args.seeds)]
    brng = np.random.default_rng(SEED + 1)
    saved = INTERIM / "stability_preds.npz"
    if args.reuse_preds:
        z = np.load(saved)                                    # numeric + fixed-width str arrays only
        want = [k for k, _ in plan]
        if list(z["kinds"]) != want:
            raise RuntimeError(f"saved replicates {list(z['kinds'])} do not match the requested plan {want}")
        preds, kinds = list(z["preds"]), list(z["kinds"])
        times = list(z["seconds"]) if "seconds" in z.files else []   # refit seconds (attribution refits below)
        if "shap_imp" in z.files:
            shap_imp = list(z["shap_imp"])
        else:                                                 # rebuild attributions from the same resamples
            for i in range(args.attr_boot):
                t0 = time.time()
                w = block_bootstrap_weights(ctx.blocks, brng)  # same RNG sequence -> identical weights
                m = fit(Xtr, ytr, params, w=w)
                d = float(np.max(np.abs(m.predict(Xte[shap_rows]).astype(np.float32) - preds[i][shap_rows])))
                if d > 1e-5:
                    raise RuntimeError(f"bootstrap {i} refit does not reproduce its saved predictions ({d})")
                contrib = m.booster_.predict(Xte[shap_rows], pred_contrib=True)
                shap_imp.append(np.abs(contrib[:, :-1]).mean(axis=0))
                times.append(time.time() - t0)
                log.info("attribution refit %d reproduces saved predictions (max diff %.1e): %.0fs",
                         i, d, times[-1])
            np.savez_compressed(saved, preds=np.vstack(preds), kinds=np.array(kinds, dtype="U16"),
                                shap_imp=np.vstack(shap_imp), seconds=np.array(times))   # never recompute these
        plan = []
    for kind, i in plan:
        t0 = time.time()
        if kind == "bootstrap":
            w = block_bootstrap_weights(ctx.blocks, brng)
            m = fit(Xtr, ytr, params, w=w)
        else:
            m = fit(Xtr, ytr, params, seed=SEED + 100 + i)
        p = m.predict(Xte).astype(np.float32)
        contrib = m.booster_.predict(Xte[shap_rows], pred_contrib=True)
        preds.append(p); kinds.append(kind)
        shap_imp.append(np.abs(contrib[:, :-1]).mean(axis=0))
        times.append(time.time() - t0)
        log.info("%s %d: %.0fs", kind, i, times[-1])
        np.savez_compressed(saved, preds=np.vstack(preds), kinds=np.array(kinds, dtype="U16"),
                            shap_imp=np.vstack(shap_imp), seconds=np.array(times))
    P = np.vstack(preds); kinds = np.array(kinds)
    R = np.vstack([national_ranks(p, tie) for p in P])
    summary = {"replicates": {"bootstrap": int((kinds == "bootstrap").sum()), "seed": int((kinds == "seed").sum())},
               "seconds_per_refit_mean": float(np.mean(times)) if times else 60.0, "segments": int(n),
               "estimated_hours_for_200_bootstrap_refits": float((np.mean(times) if times else 60.0) * 200 / 3600),
               "attribution_replicates": len(shap_imp)}

    ks = {"top100": 100, "top500": 500, "top1000": 1000, "top1pct": int(0.01 * n), "top5pct": int(0.05 * n),
          "top10pct": int(0.10 * n), "top20pct": int(0.20 * n)}
    rows = []
    for kind in ["bootstrap", "seed"]:
        sel = kinds == kind
        if sel.sum() < 2:
            continue
        Rk = R[sel]
        corr = np.corrcoef(np.log(P[sel]))
        for kname, k in ks.items():
            pair, prod = topk_overlap(Rk, k, prod_rank)
            freq = membership_frequency(Rk, k)[prod_rank <= k]
            rows.append({"variability": kind, "k": kname, "k_segments": k,
                         "mean_pairwise_overlap": pair, "mean_overlap_with_production": prod,
                         "share_of_production_topk_in_topk_in_>=90pct": float((freq >= 0.9).mean()),
                         "share_of_production_topk_in_topk_in_<50pct": float((freq < 0.5).mean())})
        summary[f"{kind}_mean_pairwise_corr_log_pred"] = float(corr[np.triu_indices(len(corr), 1)].mean())
        for gap in (1, 10, 100):
            summary[f"{kind}_order_preserved_gap{gap}_top1000"] = order_preserved(Rk, prod_rank, gap, 1000)
    T = pd.DataFrame(rows)
    write_csv(T.round(4), REPORTS / "ranking_stability_topk.csv")

    # per-segment table for the backend population
    v2 = pd.read_csv(BACKEND_DATA / "v2" / "road_segments_ranked_v2.csv", usecols=["segment_id", "rank"])
    pos = pd.Series(np.arange(n), index=ctx.seg.segment_id.values)
    rows_b = pos.reindex(v2.segment_id.values).values.astype(int)
    boot = kinds == "bootstrap"
    S = rank_summary(R[boot], rows_b)
    S.insert(0, "segment_id", v2.segment_id.values); S.insert(1, "rank", v2["rank"].values)
    for kname in ["top100", "top1000", "top5pct", "top10pct", "top20pct"]:
        S[f"freq_{kname}"] = membership_frequency(R[boot][:, rows_b], ks[kname])
    S["seed_rank_p05"] = np.percentile(R[kinds == "seed"][:, rows_b], 5, axis=0) if (kinds == "seed").any() else np.nan
    S["seed_rank_p95"] = np.percentile(R[kinds == "seed"][:, rows_b], 95, axis=0) if (kinds == "seed").any() else np.nan
    S["stability_class"] = stability_class(S.freq_top1000.values, S.freq_top5pct.values)

    # C. window sensitivity
    wfile = INTERIM / "windows" / "forecast_preds_2025.npz"
    win = {}
    if wfile.exists():
        # this file is written by our own historical_windows.py; older copies store segment_id as an
        # object array, so pickle is allowed for this self-produced local file only
        z = np.load(wfile, allow_pickle=True)
        wpos = pd.Series(np.arange(len(z["segment_id"])), index=z["segment_id"]).reindex(ctx.seg.segment_id.values)
        wr = {}
        for name in z.files:
            if name == "segment_id":
                continue
            wp = z[name][wpos.values.astype(int)]
            wr[name] = national_ranks(wp, tie)
            win[name] = {"max_abs_diff_vs_production_pred": float(np.max(np.abs(wp - prod_pred))) if
                         name == "REF_recent3_single" else None,
                         **{f"overlap_{kn}": float(len(set(np.flatnonzero(wr[name] <= k)) &
                                                       set(np.flatnonzero(prod_rank <= k))) / k)
                            for kn, k in ks.items() if k <= 400_000},
                         "spearman_log_pred": float(pd.Series(np.log(wp)).corr(pd.Series(np.log(prod_pred)),
                                                                                method="spearman"))}
        W = np.vstack([wr[k][rows_b] for k in wr])
        S["window_rank_min"] = W.min(axis=0); S["window_rank_max"] = W.max(axis=0)
        write_json(win, REPORTS / "ranking_stability_windows.json")

    # D. observation dependence: drop each top-1000 segment's largest history collision
    top = np.flatnonzero(prod_rank <= 1000)
    ac = ctx.ac[ctx.ac.collision_year.isin(fold.test_x.years)]
    own = ac[ac.seg_idx.isin(top)].sort_values(["seg_idx", "adj_ksi_cas", "collision_index"],
                                               ascending=[True, False, True])
    biggest = own.drop_duplicates("seg_idx")
    ac_red = ctx.ac[~ctx.ac.collision_index.isin(biggest.collision_index)]
    h_red = history_features(ac_red, ctx.seg, Window(fold.test_x.start, fold.test_x.end))
    X_red = Xte_f.copy()
    hcols = [c for c in cols if c.startswith("h_")]
    X_red.loc[top, hcols] = h_red.loc[top, hcols].values.astype(np.float32)   # own history only; context unchanged
    from lightgbm import Booster
    prod_model = Booster(model_file=str(OUTPUTS / "explainability" / "production_lgbm.txt"))  # verified by explain_blackspot.py
    p_check = prod_model.predict(Xte[top])
    p_red = prod_model.predict(X_red.loc[top, cols].values.astype(np.float32))
    allp = prod_pred.copy(); allp[top] = p_red
    new_rank = national_ranks(allp, tie)[top]
    D = pd.DataFrame({"segment_id": ctx.seg.segment_id.values[top], "rank": prod_rank[top],
                      "rank_without_largest_collision": new_rank, "forecast": prod_pred[top],
                      "forecast_without_largest_collision": p_red,
                      "largest_collision_adj_ksi": biggest.set_index("seg_idx").reindex(top).adj_ksi_cas.values,
                      "single_event_flag": full.single_event_flag.values[top]}).sort_values("rank")
    write_csv(D.round(4), REPORTS / "ranking_stability_drop_largest_collision.csv")
    summary["drop_largest_collision"] = {
        "production_model_reproduced_max_abs_diff": float(np.max(np.abs(p_check - prod_pred[top]))),
        "median_rank_change": float(np.median(D.rank_without_largest_collision - D["rank"])),
        "share_leaving_top1000": float((D.rank_without_largest_collision > 1000).mean()),
        "share_leaving_top5pct": float((D.rank_without_largest_collision > ks["top5pct"]).mean()),
        "flagged_single_event_in_top1000": int(D.single_event_flag.sum()),
        "flagged_median_new_rank": float(D[D.single_event_flag].rank_without_largest_collision.median())
        if D.single_event_flag.any() else None}
    S = S.merge(D[["segment_id", "rank_without_largest_collision"]], on="segment_id", how="left")
    write_csv(S.round(3), EXT / "segment_stability_v2.csv")

    # attribution stability across bootstrap models (SHAP on a fixed sample)
    SI = np.vstack(shap_imp)
    imp = pd.DataFrame(SI[boot] if len(SI) == len(kinds) else SI, columns=cols)
    ranks_imp = imp.rank(axis=1, ascending=False)
    from blackspot.explain import group
    grp = imp.T.groupby([group(c) for c in cols]).sum().T
    A = pd.DataFrame({"feature": cols, "mean_abs_shap_mean": imp.mean().values, "mean_abs_shap_sd": imp.std().values,
                      "importance_rank_median": ranks_imp.median().values, "importance_rank_min": ranks_imp.min().values,
                      "importance_rank_max": ranks_imp.max().values}).sort_values("mean_abs_shap_mean", ascending=False)
    write_csv(A.round(5), REPORTS / "ranking_stability_attributions.csv")
    summary["group_importance_cv"] = (grp.std() / grp.mean()).round(4).to_dict()
    summary["feature_importance_cv_top10"] = (imp.std() / imp.mean()).loc[A.feature.head(10)].round(4).to_dict()
    write_json(summary, REPORTS / "ranking_stability_summary.json")
    log.info("stability done: %s", summary)


if __name__ == "__main__":
    main()
