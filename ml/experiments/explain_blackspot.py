"""Phase 3: explain the PRODUCTION blackspot model.

    .venv/Scripts/python ml/experiments/explain_blackspot.py        (~15 min)

1. Refit the production LightGBM exactly as `pipeline.py forecast` does (frozen spec,
   training pair 2021-23 -> 2024-25) and require its 2026-27 predictions to equal the
   stored blackspot_score for every segment. Only then save it (new file) and explain it.
2. Exact TreeSHAP for every segment (LightGBM pred_contrib), cross-checked with `shap`.
3. Global / group / dependence / interaction / local explanations, correlation of
   features, burden-vs-exposure analysis, and frontend exports.

Writes ml/outputs/explainability/ (model, plots, tables) and
data/v2/extensions/segment_explanations_*.{json,csv}. Existing files are not modified.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import BACKEND_DATA, OUTPUTS, SEED  # noqa: E402
from blackspot.experiment import fit_predict, standard_specs  # noqa: E402
from blackspot.explain import (FEATURES, assert_no_target_columns, check_additivity, contributions,  # noqa: E402
                               display_value, group, group_contributions, label, top_contributions)
from blackspot.features import FORECAST_CUTOFF, PRIMARY, Fold, build_frame  # noqa: E402
from blackspot.io_utils import file_hash, setup_logging, write_csv, write_json, write_text  # noqa: E402
from blackspot.steps import _context, _load_frozen  # noqa: E402

log = logging.getLogger("blackspot.explain")
OUT = OUTPUTS / "explainability"
EXT = BACKEND_DATA / "v2" / "extensions"
UNIFORM_N = 200_000
DEP_FEATURES = ["h_n_coll", "log_length", "stroke_adj_ksi_other", "net_km_3km", "n_junctions", "h_speed_median"]


def refit_production(ctx, spec):
    fold = Fold(FORECAST_CUTOFF)
    Xtr = build_frame(ctx.seg, ctx.ac, fold.train_x, fold.train_y, ctx.road)
    Xte = build_frame(ctx.seg, ctx.ac, fold.test_x, None, ctx.road)
    chosen = [s for s in standard_specs(spec["lgbm_params"]) if s.name == spec["selected_model"]][0]
    pred, info = fit_predict(chosen, Xtr, Xtr[f"y_{PRIMARY}"].values, Xte, PRIMARY)
    return info["_model"], info["_cols"], Xte, pred, fold


def verify_against_stored(seg, pred):
    full = pd.read_parquet(OUTPUTS / "road_segments_v2_full.parquet", columns=["segment_id", "blackspot_score", "rank"])
    s = full.set_index("segment_id").reindex(seg.segment_id.values)
    if s.blackspot_score.isna().any():
        raise RuntimeError("segments missing from the stored forecast")
    d = np.abs(s.blackspot_score.values - pred)
    rank_now = pd.Series(-pred).rank(method="first").values      # ties are vanishingly rare
    return {"n_segments": int(len(pred)), "max_abs_diff": float(d.max()), "mean_abs_diff": float(d.mean()),
            "identical_top1000": bool(set(np.argsort(-pred, kind="stable")[:1000]) ==
                                      set(np.flatnonzero(s["rank"].values <= 1000))),
            "rank_rows_differing": int((np.abs(rank_now - s["rank"].values) > 0).sum())}, s["rank"].values


def main():
    setup_logging()
    for d in (OUT, OUT / "plots", OUT / "local", EXT):
        d.mkdir(parents=True, exist_ok=True)
    spec = _load_frozen()
    ctx = _context(with_aadf=False)
    t0 = time.time()
    model, cols, Xte, pred, fold = refit_production(ctx, spec)
    assert_no_target_columns(cols)
    ver, rank = verify_against_stored(ctx.seg, pred)
    log.info("refit in %.0fs; verification %s", time.time() - t0, ver)
    if ver["max_abs_diff"] > 1e-6:
        raise RuntimeError(f"refitted model does not reproduce the production scores: {ver}")
    booster = model.booster_
    mpath = OUT / "production_lgbm.txt"
    booster.save_model(str(mpath))
    write_json({"verification": ver, "features": cols, "n_features": len(cols),
                "training_pair": {"features": str(fold.train_x), "target": str(fold.train_y)},
                "inference_features": str(fold.test_x), "forecast_years": fold.test_y.years,
                "objective": "poisson (log link): contributions add in log(expected KSI)",
                "frozen_spec_sha256": spec["sha256"], "model_file_sha256": file_hash(mpath),
                "lightgbm_params": model.get_params()}, OUT / "production_model_verification.json")

    X = Xte[cols].values.astype(np.float32)
    # TreeSHAP for all 1.83 M segments takes ~70 min on a laptop; every output below needs only:
    #   the backend-file segments (exports), a 200,000-segment uniform random sample
    #   (population-representative global statistics), the whole top 5%, and the local picks.
    rng = np.random.default_rng(SEED)
    hist = Xte.h_n_coll.values
    order = np.argsort(-pred, kind="stable")
    top5 = order[: int(0.05 * len(pred))]
    uniform = np.sort(rng.choice(len(X), UNIFORM_N, replace=False))
    v2 = pd.read_csv(BACKEND_DATA / "v2" / "road_segments_ranked_v2.csv", usecols=["segment_id", "rank"])
    pos = pd.Series(np.arange(len(ctx.seg)), index=ctx.seg.segment_id.values)
    backend_rows = pos.reindex(v2.segment_id.values).values.astype(int)
    hist1_u = uniform[hist[uniform] > 0]
    hist0_u = uniform[hist[uniform] == 0]
    picks = {"rank_1": order[0], "rank_10": order[9], "rank_100": order[99], "rank_1000": order[999],
             "rank_10000": order[9999],
             "median_with_history": hist1_u[np.argsort(pred[hist1_u])[len(hist1_u) // 2]],
             "median_no_history": hist0_u[np.argsort(pred[hist0_u])[len(hist0_u) // 2]],
             "rank_bottom_1pct": order[int(0.99 * len(order))]}
    need = np.unique(np.concatenate([backend_rows, uniform, top5, np.array(list(picks.values()))]))
    t1 = time.time()
    C = np.full((len(X), len(cols) + 1), np.nan, dtype=np.float32)
    C[need] = contributions(booster, X[need])
    add = check_additivity(C[need], pred[need])
    log.info("TreeSHAP for %d segments in %.0fs; additivity max err %.2e", len(need), time.time() - t1, add)

    # cross-check with the shap library on a sample
    import shap
    samp = rng.choice(need, 2000, replace=False)
    sv = shap.TreeExplainer(booster).shap_values(X[samp])
    shap_lib_diff = float(np.max(np.abs(np.asarray(sv) - C[samp, :-1])))

    # populations (global statistics on the uniform sample, except the top 5% which is complete)
    pops = {f"all segments (uniform random sample of {UNIFORM_N:,})": uniform,
            "top 5% by forecast (all 91,377)": top5,
            "segments with >= 1 collision 2023-25 (in the sample)": hist1_u,
            "segments with no collision 2023-25 (in the sample)": hist0_u}
    imp = []
    for pname, rows in pops.items():
        a = np.abs(C[rows, :-1]).mean(axis=0)
        m = C[rows, :-1].mean(axis=0)
        for j, c in enumerate(cols):
            imp.append({"population": pname, "feature": c, "label": label(c), "group": group(c),
                        "kind": FEATURES[c][2], "mean_abs_shap": float(a[j]), "mean_shap": float(m[j])})
    imp = pd.DataFrame(imp)
    imp["rank_in_population"] = imp.groupby("population").mean_abs_shap.rank(ascending=False, method="first")
    write_csv(imp.round(6), OUT / "global_importance.csv")
    G = group_contributions(C, cols)
    gimp = pd.DataFrame([{"population": p, **{f"mean_abs_{g}": float(np.abs(G[f"shap_{g}"].values[r]).mean())
                                               for g in ["history", "road", "context"]}}
                         for p, r in pops.items()])
    write_csv(gimp.round(6), OUT / "group_importance.csv")

    # feature correlation (uniform sample) -> which attributions are shared and unstable
    s50 = rng.choice(len(X), 50_000, replace=False)
    corr = pd.DataFrame(X[s50], columns=cols).corr(method="spearman")
    pairs = [(a, b, float(corr.loc[a, b])) for i, a in enumerate(cols) for b in cols[i + 1:]
             if abs(corr.loc[a, b]) >= 0.8 and np.isfinite(corr.loc[a, b])]
    write_csv(pd.DataFrame(pairs, columns=["feature_a", "feature_b", "spearman"]).sort_values(
        "spearman", key=abs, ascending=False).round(4), OUT / "correlated_feature_pairs.csv")

    # ---------------- plots
    for name, rows in [("all", rng.choice(uniform, 5000, replace=False)), ("top5pct", rng.choice(top5, 5000, replace=False))]:
        plt.figure()
        shap.summary_plot(C[rows, :-1], X[rows], feature_names=[label(c)[:48] for c in cols], max_display=18,
                          show=False, plot_size=(11, 8))
        plt.title(f"TreeSHAP (log expected KSI), sample of 5,000: {'all segments' if name == 'all' else 'top 5% by forecast'}",
                  fontsize=10)
        plt.tight_layout(); plt.savefig(OUT / "plots" / f"shap_summary_{name}.png", dpi=110); plt.close("all")
    dep_rows = np.concatenate([rng.choice(uniform, 15000, replace=False), rng.choice(top5, 5000, replace=False)])
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.5))
    for ax, f in zip(axes.ravel(), DEP_FEATURES):
        j = cols.index(f)
        xv = X[dep_rows, j]
        sc = ax.scatter(xv, C[dep_rows, j], c=np.log1p(hist[dep_rows]), s=3, cmap="viridis", alpha=0.5)
        ax.axhline(0, color="grey", lw=0.6)
        ax.set_xlabel(label(f)[:60], fontsize=8); ax.set_ylabel("SHAP (log expected KSI)", fontsize=8)
        if f in ("h_n_coll", "stroke_adj_ksi_other", "net_km_3km"):
            ax.set_xscale("symlog")
    fig.colorbar(sc, ax=axes.ravel().tolist(), label="log(1 + collisions here, 2023-25)")
    fig.suptitle("Dependence: how the model's log-prediction moves with each feature (colour = own crash history)")
    plt.savefig(OUT / "plots" / "shap_dependence.png", dpi=110); plt.close("all")

    # interactions on a small sample (exact interaction values are O(features^2))
    irows = np.concatenate([rng.choice(len(X), 600, replace=False), rng.choice(top5, 400, replace=False)])
    t2 = time.time()
    iv = np.asarray(shap.TreeExplainer(booster).shap_interaction_values(X[irows]))
    mi = np.abs(iv).mean(axis=0)
    inter = [{"feature_a": cols[a], "feature_b": cols[b], "mean_abs_interaction": float(2 * mi[a, b])}
             for a in range(len(cols)) for b in range(a + 1, len(cols))]
    inter = pd.DataFrame(inter).sort_values("mean_abs_interaction", ascending=False)
    main_eff = pd.DataFrame({"feature": cols, "mean_abs_main_effect": np.diag(mi)})
    write_csv(inter.head(30).round(6), OUT / "top_interactions.csv")
    write_csv(main_eff.sort_values("mean_abs_main_effect", ascending=False).round(6), OUT / "main_effects.csv")
    log.info("interactions on %d rows in %.0fs", len(irows), time.time() - t2)

    # ---------------- burden vs exposure (M/A with AADF, from the stored forecast table)
    full = pd.read_parquet(OUTPUTS / "road_segments_v2_full.parquet",
                           columns=["segment_id", "aadf", "ksi_per_100m_vkm_eb", "eb_excess_ksi_history", "length_m"])
    full = full.set_index("segment_id").reindex(ctx.seg.segment_id.values)
    ma = uniform[full.aadf.notna().values[uniform]]          # M/A with AADF, within the uniform sample
    la = np.log(full.aadf.values[ma])
    from scipy.stats import spearmanr
    expo = {"n_segments_with_aadf_in_sample": int(len(ma)),
            "spearman_logAADF_vs_log_forecast": float(spearmanr(la, np.log(pred[ma])).statistic),
            "spearman_logAADF_vs_rate_eb": float(spearmanr(la, full.ksi_per_100m_vkm_eb.values[ma],
                                                           nan_policy="omit").statistic)}
    for g in ["history", "road", "context"]:
        expo[f"spearman_logAADF_vs_shap_{g}"] = float(spearmanr(la, G[f"shap_{g}"].values[ma]).statistic)
    kinds = pd.Series({c: FEATURES[c][2] for c in cols})
    for kind in ["exposure_proxy", "risk_character"]:
        idx = [cols.index(c) for c in kinds[kinds == kind].index]
        ks = C[:, idx].sum(axis=1)
        expo[f"spearman_logAADF_vs_shap_{kind}"] = float(spearmanr(la, ks[ma]).statistic)
        rate_ok = ma[np.isfinite(full.ksi_per_100m_vkm_eb.values[ma]) & (full.length_m.values[ma] >= 250)]
        expo[f"spearman_rate_eb_vs_shap_{kind}_len250"] = float(spearmanr(
            full.ksi_per_100m_vkm_eb.values[rate_ok], ks[rate_ok]).statistic)
    write_json(expo, OUT / "burden_vs_exposure.json")

    # ---------------- local explanations
    flag = pd.read_parquet(OUTPUTS / "road_segments_v2_full.parquet", columns=["segment_id", "single_event_flag",
                                                                               "location", "n_crashes"])
    flag = flag.set_index("segment_id").reindex(ctx.seg.segment_id.values)
    sev = np.flatnonzero(flag.single_event_flag.values.astype(bool))
    if len(sev):
        top_sev = sev[np.argmin(rank[sev])]
        if np.isnan(C[top_sev, 0]):
            C[top_sev] = contributions(booster, X[top_sev:top_sev + 1])[0]
        picks["top_single_event_flagged"] = top_sev
    local = []
    for name, i in picks.items():
        phi = C[i, :-1]
        top = np.argsort(-np.abs(phi))[:10]
        local.append({"case": name, "segment_id": ctx.seg.segment_id.values[i], "rank": int(rank[i]),
                      "location": flag.location.values[i], "forecast_ksi_2026_27": float(pred[i]),
                      "base_value_log": float(C[i, -1]), "base_value_count": float(np.exp(C[i, -1])),
                      "single_event_flag": bool(flag.single_event_flag.values[i]),
                      "top_contributions": [{"feature": cols[j], "label": label(cols[j]), "value": float(X[i, j]),
                                             "display": display_value(cols[j], float(X[i, j])),
                                             "shap_log": float(phi[j]), "factor": float(np.exp(phi[j]))}
                                            for j in top],
                      "group_factors": {g: float(np.exp(G[f"shap_{g}"].values[i])) for g in ["history", "road", "context"]}})
        ex = shap.Explanation(values=phi, base_values=C[i, -1], data=X[i], feature_names=[label(c)[:55] for c in cols])
        plt.figure()
        shap.plots.waterfall(ex, max_display=12, show=False)
        plt.title(f"{name}: {flag.location.values[i]}  (rank {int(rank[i]):,}; forecast {pred[i]:.2f})", fontsize=9)
        plt.tight_layout(); plt.savefig(OUT / "local" / f"waterfall_{name}.png", dpi=105); plt.close("all")
    write_json(local, OUT / "local" / "local_explanations.json")

    # ---------------- frontend exports (keyed by segment_id; existing files untouched)
    rows = backend_rows
    tc = top_contributions(C, cols, X, rows, k=5)
    tc.insert(0, "segment_id", ctx.seg.segment_id.values[tc.row.values])
    tc.insert(1, "rank", rank[tc.row.values].astype(int))
    tc = tc.drop(columns="row")
    assert_no_target_columns(tc.feature.unique())
    write_csv(tc.round(6), EXT / "segment_explanations_v2.csv")
    top5000 = v2.nsmallest(5000, "rank")
    r5 = pos.reindex(top5000.segment_id.values).values.astype(int)
    js = {}
    for i in r5:
        phi = C[i, :-1]
        top = np.argsort(-np.abs(phi))[:5]
        js[ctx.seg.segment_id.values[i]] = {
            "rank": int(rank[i]), "forecast": round(float(pred[i]), 4), "base": round(float(np.exp(C[i, -1])), 4),
            "groups": {g: round(float(np.exp(G[f"shap_{g}"].values[i])), 3) for g in ["history", "road", "context"]},
            "top": [{"f": cols[j], "label": label(cols[j]), "value": round(float(X[i, j]), 3),
                     "display": display_value(cols[j], float(X[i, j])),
                     "factor": round(float(np.exp(phi[j])), 3)} for j in top]}
    write_text(json.dumps({"model": "production LightGBM (frozen spec " + spec["sha256"][:12] + ")",
                           "explains": "blackspot_score (expected adjusted KSI casualties 2026-27), not per-vehicle risk",
                           "how_to_read": "forecast = base x product of all feature factors; factors are model "
                                          "attributions (TreeSHAP), not causal effects",
                           "segments": js}, separators=(",", ":")),
               EXT / "segment_explanations_top5000_v2.json")
    write_json({"shap_library_vs_lightgbm_max_abs_diff": shap_lib_diff, "additivity_max_abs_err": add,
                "n_segments_explained": int(len(need)), "uniform_sample": UNIFORM_N,
                "backend_rows_explained": int(len(backend_rows)), "top5pct_explained": int(len(top5)),
                "seconds_treeshap": round(time.time() - t1, 1)},
               OUT / "shap_checks.json")
    log.info("explainability done; shap lib diff %.2e; additivity %.2e", shap_lib_diff, add)


if __name__ == "__main__":
    main()
