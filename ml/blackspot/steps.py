"""Pipeline steps. Each reads its inputs from disk and writes its outputs atomically."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .config import INTERIM, REPORTS
from .io_utils import write_csv, write_json

log = logging.getLogger("blackspot.steps")

UNKNOWN_CODES = {  # values the DfT data guide uses for missing / unknown / out of range
    "speed_limit": {-1, 99}, "road_type": {-1, 9}, "junction_detail": {-1, 99},
    "junction_control": {9},          # -1 is used for "not at junction" in practice (see data_quality.md)
    "light_conditions": {-1, 7}, "weather_conditions": {-1, 9},
    "road_surface_conditions": {-1, 9}, "urban_or_rural_area": {-1, 3},
    "first_road_class": {-1}, "trunk_road_flag": {-1}, "pedestrian_crossing": {-1, 99},
    "carriageway_hazards": {-1, 99}, "special_conditions_at_site": {-1, 9},
}


def step_data() -> None:
    from . import stats19
    coll, q = stats19.build_collisions()

    # reporting regime: casualty-level injury-based share and reported vs adjusted serious
    by_year = coll.groupby("collision_year").agg(
        collisions=("collision_index", "size"), ksi_collisions=("is_ksi_collision", "sum"),
        casualties=("n_cas", "sum"), fatal_cas=("n_fatal_cas", "sum"),
        serious_cas=("n_serious_cas", "sum"), adj_serious_cas=("adj_serious_cas", "sum"),
        ksi_cas=("n_ksi_cas", "sum"), adj_ksi_cas=("adj_ksi_cas", "sum"))
    w = coll.n_cas.where(coll.n_cas > 0, 0)
    by_year["injury_based_cas_share"] = (coll.injury_based_share * w).groupby(coll.collision_year).sum() \
        / w.groupby(coll.collision_year).sum()
    by_year["serious_share_reported"] = by_year.serious_cas / by_year.casualties
    by_year["serious_share_adjusted"] = by_year.adj_serious_cas / by_year.casualties
    by_year["adj_over_reported_ksi"] = by_year.adj_ksi_cas / by_year.ksi_cas
    write_csv(by_year.reset_index().round(5), REPORTS / "data_quality_by_year.csv")

    # which forces still recorded casualties without injury-based reporting
    recent = coll[coll.collision_year >= 2022]
    pf = (recent.assign(ib=recent.injury_based_share * recent.n_cas)
          .groupby(["police_force", "collision_year"]).agg(ib=("ib", "sum"), cas=("n_cas", "sum")))
    pf = (pf.ib / pf.cas).unstack().round(3)
    write_csv(pf.reset_index(), REPORTS / "data_quality_injury_based_by_force.csv")
    q["forces_below_50pct_injury_based"] = {int(y): sorted(int(f) for f in pf.index[pf[y] < 0.5])
                                            for y in pf.columns}

    # missing / unknown codes by year
    miss = {}
    for c, bad in UNKNOWN_CODES.items():
        if c in coll:
            miss[c] = (coll[c].isin(bad) | coll[c].isna()).groupby(coll.collision_year).mean().round(4)
    miss = pd.DataFrame(miss)
    write_csv(miss.reset_index(), REPORTS / "data_quality_unknown_codes_by_year.csv")
    q["junction_detail_codes_by_year"] = {
        int(y): sorted(int(v) for v in g.junction_detail.dropna().unique())
        for y, g in coll.groupby("collision_year")}
    q["speed_limit_codes"] = sorted(float(v) for v in coll.speed_limit.dropna().unique())
    write_json(q, REPORTS / "data_quality.json")
    log.info("collisions: %s rows, %s-%s", len(coll), coll.collision_year.min(), coll.collision_year.max())


def step_network() -> None:
    from . import network
    seg, verts, off = network.build_segments()
    s = {"n_segments": int(len(seg)), "n_strokes": int(seg.stroke.nunique()),
         "total_km": float(seg.length_m.sum() / 1000),
         "km_by_class": (seg.groupby("road_class").length_m.sum() / 1000).round(1).to_dict(),
         "segments_by_class": seg.road_class.value_counts().to_dict(),
         "length_quantiles_m": seg.length_m.quantile([.01, .05, .25, .5, .75, .95, .99]).round(1).to_dict(),
         "share_single_piece_short(<250m)": float((seg.length_m < 250).mean()),
         "form_of_way_km": (seg.groupby("form_of_way").length_m.sum() / 1000).round(1).to_dict()}
    write_json(s, REPORTS / "network_summary.json")
    log.info("network: %s", s)


def block_id(e, n, size: float = 50_000.0) -> np.ndarray:
    """50 km British National Grid square used for spatial CV and clustered bootstrap."""
    return (np.floor(np.asarray(e) / size).astype(int) * 1000 + np.floor(np.asarray(n) / size).astype(int))


def step_snap() -> None:
    from . import network, snap, stats19
    from .io_utils import write_parquet
    coll = stats19.load_collisions()
    seg, verts, off = network.load_segments()
    res = snap.snap(coll, seg, verts, off)
    res["collision_year"] = coll.collision_year.values
    write_parquet(res, snap.ASSIGN_PARQUET)

    a = res.seg_idx >= 0
    out = {"collisions": int(len(res)), "assigned_share": float(a.mean()),
           "unassigned_reasons": res.loc[~a, "unassigned_reason"].value_counts().to_dict(),
           "match_type_share": res.loc[a, "match_type"].value_counts(normalize=True).round(4).to_dict(),
           "snap_distance_quantiles_m": res.loc[a, "snap_distance_m"].quantile([.5, .9, .99]).round(1).to_dict(),
           "assigned_share_by_year": a.groupby(res.collision_year).mean().round(4).to_dict()}
    ksi = coll.adj_ksi_cas.values
    out["adj_ksi_assigned_share_by_year"] = (pd.Series(ksi * a).groupby(res.collision_year).sum()
                                             / pd.Series(ksi).groupby(res.collision_year).sum()).round(4).to_dict()
    sc = seg.road_class.values[res.seg_idx.clip(lower=0)]
    out["adj_ksi_by_assigned_os_class"] = (pd.Series(np.where(a, ksi, 0)).groupby(np.where(a, sc, "unassigned"))
                                           .sum().round(1).to_dict())
    cross = pd.crosstab(coll.first_road_class[a.values], sc[a.values], normalize="index").round(3)
    write_csv(cross.reset_index(), REPORTS / "snap_stats19_class_vs_os_class.csv")
    write_json(out, REPORTS / "snap_summary.json")
    log.info("snap: %s", out)


# ================================================================== modelling steps
FROZEN_SPEC = None  # set lazily (OUTPUTS path) to avoid import-time side effects


def _frozen_path():
    from .config import OUTPUTS
    return OUTPUTS / "frozen_spec.json"


def _context(with_aadf=True):
    from . import network, snap, stats19
    from .experiment import make_context
    coll = stats19.load_collisions(columns=stats19.MODEL_COLUMNS)
    seg, _, _ = network.load_segments()
    assign = pd.read_parquet(snap.ASSIGN_PARQUET, columns=["collision_index", "seg_idx"])
    return make_context(seg, coll, assign, with_aadf=with_aadf)


def _append(frames, res, key):
    if key in res and len(res[key]):
        frames.append(res[key])


def step_develop() -> None:
    """Development folds only (test targets <= 2023). Writes and freezes the model spec."""
    import hashlib, json
    from .experiment import (ABLATION_PAIRS, EXPOSURE_PAIRS, MAIN_CANDIDATES, MAIN_PAIRS, ablation_specs,
                             exposure_specs, run_fold, standard_specs)
    from .features import DEV_CUTOFFS, PRIMARY, Fold

    ctx = _context()
    # 1. light LightGBM tuning on the earliest dev fold's training pair only:
    #    fit on spatial blocks A, validate on blocks B, both inside the training pair
    tuning = tune_lgbm(ctx, Fold(DEV_CUTOFFS[0]))
    best_params = tuning.sort_values("val_deviance").iloc[0].params
    write_csv(tuning.assign(params=tuning.params.map(json.dumps)), REPORTS / "lgbm_tuning.csv")
    log.info("chosen LightGBM params: %s", best_params)

    metrics, boots, cover, infos = [], [], [], {}
    for c in DEV_CUTOFFS:
        fold = Fold(c)
        res = run_fold(ctx, fold, standard_specs(best_params),
                       populations=("all", "numbered", "hist1", "class_M", "class_A", "class_B",
                                    "class_C", "class_U", "class_N"), pairs=MAIN_PAIRS)
        _append(metrics, res, "metrics"); _append(boots, res, "bootstrap"); _append(cover, res, "coverage")
        infos[c] = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in res["info"].items()}
        ab = run_fold(ctx, fold, ablation_specs(best_params), populations=("all",), n_boot=200,
                      reference=None, pairs=ABLATION_PAIRS)
        ab["metrics"]["study"] = "ablation"; ab["bootstrap"]["study"] = "ablation"
        _append(metrics, ab, "metrics"); _append(boots, ab, "bootstrap")
        ex = run_fold(ctx, fold, exposure_specs(best_params), populations=("exposure",), n_boot=200,
                      reference="hist_collisions", pairs=EXPOSURE_PAIRS)
        ex["metrics"]["study"] = "exposure"; ex["bootstrap"]["study"] = "exposure"
        _append(metrics, ex, "metrics"); _append(boots, ex, "bootstrap"); _append(cover, ex, "coverage")
    M = pd.concat(metrics, ignore_index=True); B = pd.concat(boots, ignore_index=True)
    M["study"] = M["study"].fillna("main") if "study" in M else "main"
    B["study"] = B["study"].fillna("main") if "study" in B else "main"
    write_csv(M, REPORTS / "rolling_origin_results.csv")
    write_csv(B, REPORTS / "rolling_origin_bootstrap.csv")
    write_csv(pd.concat(cover, ignore_index=True), REPORTS / "rolling_origin_coverage.csv")
    write_json(infos, REPORTS / "rolling_origin_model_info.json")

    # 2. pre-declared selection rule: lowest mean dev-fold Poisson deviance on the full
    #    scored population. A simpler model is chosen instead if its PAIRED block-bootstrap
    #    deviance difference from the best is within one standard error, averaged over
    #    the dev folds (simplicity order: eb < nb_glm < poisson_glm < lgbm).
    main = M[(M.study == "main") & (M.population == "all") & (M.target == PRIMARY)]
    cand = MAIN_CANDIDATES
    dev = main[main.model.isin(cand)].groupby("model").poisson_deviance.mean()
    best = dev.idxmin()
    pb = B[(B.study == "main") & (B.population == "all") & (B.metric == "dev")]
    pb = pb[pb.get("pair_reference", pd.Series(index=pb.index, dtype=object)) == best]
    diff = pb.groupby("model").diff_vs_ref_mean.mean()
    se = pb.groupby("model").diff_se.mean()
    chosen = best
    for m in cand:                                       # simplest first
        if m == best or (m in diff.index and diff[m] <= se[m]):
            chosen = m
            break
    spec = {"selected_model": chosen, "best_by_deviance": best,
            "dev_fold_mean_deviance": dev.round(6).to_dict(),
            "paired_deviance_diff_vs_best": diff.round(6).to_dict(), "paired_diff_se": se.round(6).to_dict(),
            "lgbm_params": best_params, "primary_target": PRIMARY, "dev_cutoffs": list(DEV_CUTOFFS),
            "rule": "lowest mean dev-fold Poisson deviance (population all); the simplest model whose paired "
                    "block-bootstrap deviance difference from the best is <= 1 SE wins"}
    payload = json.dumps(spec, sort_keys=True, default=str)
    spec["sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    write_json(spec, _frozen_path())
    log.info("FROZEN SPEC: %s", spec)


def tune_lgbm(ctx, fold):
    """Grid search inside the training pair of one dev fold, validated on held-out blocks."""
    import json
    from .features import PRIMARY, build_frame, feature_groups
    from .models import fit_lgbm
    from .evaluation import poisson_deviance
    X = build_frame(ctx.seg, ctx.ac, fold.train_x, fold.train_y, ctx.road)
    y = X[f"y_{PRIMARY}"].values
    cols = [c for g in ("history", "road", "context") for c in feature_groups(X)[g]]
    rng = np.random.default_rng(0)
    ub = np.unique(ctx.blocks)
    val_blocks = set(rng.choice(ub, size=len(ub) // 4, replace=False))
    val = np.isin(ctx.blocks, list(val_blocks)) & ctx.scored
    tr = ~np.isin(ctx.blocks, list(val_blocks)) & ctx.scored
    rows = []
    for nl in (31, 127):
        for mcs in (200, 1000):
            for ne in (300, 800):
                p = {"num_leaves": nl, "min_child_samples": mcs, "n_estimators": ne}
                m = fit_lgbm(X.loc[tr, cols].values.astype(np.float32), y[tr], p)
                d = poisson_deviance(y[val], m.predict(X.loc[val, cols].values.astype(np.float32)))
                rows.append({"params": p, "val_deviance": d})
                log.info("tune %s -> %.5f", json.dumps(p), d)
    return pd.DataFrame(rows)


def _load_frozen():
    import json
    p = _frozen_path()
    if not p.exists():
        raise RuntimeError("no frozen spec: run `pipeline.py develop` first. The final holdout is "
                           "only evaluated with a specification fixed on the development folds.")
    return json.loads(p.read_text())


def step_holdout() -> None:
    """Final holdout (cutoff 2023 -> target 2024-25) with the frozen spec, plus spatial CV,
    target sensitivity and the post-hoc 2022 fold."""
    from .experiment import exposure_specs, run_fold, standard_specs
    from .features import HOLDOUT_CUTOFF, POSTHOC_CUTOFFS, TARGETS, Fold

    spec = _load_frozen()
    log.info("using frozen spec %s (sha256 %s)", spec["selected_model"], spec["sha256"][:12])
    ctx = _context()
    params = spec["lgbm_params"]
    fold = Fold(HOLDOUT_CUTOFF)
    pops = ("all", "numbered", "hist1", "class_M", "class_A", "class_B", "class_C", "class_U", "class_N")
    metrics, boots, cover = [], [], []

    from .experiment import EXPOSURE_PAIRS, MAIN_PAIRS
    res = run_fold(ctx, fold, standard_specs(params), populations=pops, n_boot=300, keep_predictions=True,
                   pairs=MAIN_PAIRS)
    res["metrics"]["study"] = "holdout"; res["bootstrap"]["study"] = "holdout"
    _append(metrics, res, "metrics"); _append(boots, res, "bootstrap"); _append(cover, res, "coverage")
    _save_calibration(res, spec["selected_model"])

    # spatial: every block group predicted by models fitted without it
    rng = np.random.default_rng(7)
    ub = np.unique(ctx.blocks)
    grp_of = dict(zip(ub, rng.integers(0, 5, len(ub))))
    groups = np.array([grp_of[b] for b in ctx.blocks])
    sp = run_fold(ctx, fold, standard_specs(params), populations=("all", "numbered"), n_boot=300,
                  spatial_groups=groups, pairs=MAIN_PAIRS)
    sp["metrics"]["study"] = "holdout_spatial"; sp["bootstrap"]["study"] = "holdout_spatial"
    _append(metrics, sp, "metrics"); _append(boots, sp, "bootstrap")

    ex = run_fold(ctx, fold, exposure_specs(params), populations=("exposure", "aadf_q1", "aadf_q2", "aadf_q3",
                                                                  "aadf_q4", "aadf_q5"), n_boot=300,
                  pairs=EXPOSURE_PAIRS)
    ex["metrics"]["study"] = "holdout_exposure"; ex["bootstrap"]["study"] = "holdout_exposure"
    _append(metrics, ex, "metrics"); _append(boots, ex, "bootstrap"); _append(cover, ex, "coverage")

    for t in TARGETS:                                    # outcome-definition sensitivity
        if t == spec["primary_target"]:
            continue
        st = run_fold(ctx, fold, standard_specs(params), target=t, populations=("all",), n_boot=200,
                      pairs=MAIN_PAIRS)
        st["metrics"]["study"] = f"holdout_target_{t}"; st["bootstrap"]["study"] = f"holdout_target_{t}"
        _append(metrics, st, "metrics"); _append(boots, st, "bootstrap"); _append(cover, st, "coverage")

    for c in POSTHOC_CUTOFFS:
        ph = run_fold(ctx, Fold(c), standard_specs(params), populations=("all",), n_boot=200, pairs=MAIN_PAIRS)
        ph["metrics"]["study"] = "posthoc"; ph["bootstrap"]["study"] = "posthoc"
        _append(metrics, ph, "metrics"); _append(boots, ph, "bootstrap")

    M = pd.concat(metrics, ignore_index=True); B = pd.concat(boots, ignore_index=True)
    M["frozen_spec_sha256"] = spec["sha256"]
    write_csv(M, REPORTS / "model_comparison.csv")
    write_csv(B, REPORTS / "model_comparison_bootstrap.csv")
    write_csv(pd.concat(cover, ignore_index=True), REPORTS / "coverage_by_population.csv")
    log.info("holdout done")


def _save_calibration(res, selected):
    from .evaluation import calibration_table
    rows = res["rows"]
    out = []
    for m in [selected, "eb", "nb_glm", "lgbm", "hist_adj_ksi"]:
        if m in res["predictions"]:
            t = calibration_table(res["yte"][rows], res["predictions"][m][rows])
            t.insert(0, "model", m)
            out.append(t)
    write_csv(pd.concat(out, ignore_index=True), REPORTS / "calibration_holdout.csv")


def step_severity() -> None:
    """Deployable severity model: temporal + spatial validation, OOF thresholds, calibration, SHAP."""
    import joblib
    from . import severity as sv
    from . import stats19
    from .config import OUTPUTS
    out_dir = OUTPUTS / "severity_v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    coll = stats19.load_collisions()
    rows, rel = [], []

    for label_set, ib in [("injury_based_only", True), ("all_records", False)]:
        d = sv.prepare(coll, injury_based_only=ib)
        tr, va, te = (d.collision_year <= 2023).values, (d.collision_year == 2024).values, \
                     (d.collision_year == 2025).values
        log.info("severity %s: train %d, val %d, test %d", label_set, tr.sum(), va.sum(), te.sum())
        sets = sv.FEATURE_SETS if ib else {"core": sv.CORE}
        val_scores = {}
        for name, cols in sets.items():
            X = sv.matrix(d, cols)
            m = sv.fit(X[tr], d.y.values[tr])
            p_oof = sv.oof_predict(d[tr], X[tr], d.block.values[tr])
            thr = sv.best_f1_threshold(d.y.values[tr], p_oof)
            for split, mask in [("validation_2024", va), ("test_2025", te)]:
                p = m.predict_proba(sv._align_categories(X[tr], X[mask].copy()))[:, 1]
                r = {"label_set": label_set, "feature_set": name, "split": split,
                     **sv.metrics(d.y.values[mask], p, thr, d.fatal.values[mask])}
                if split == "test_2025":
                    r["roc_auc_ci_low"], r["roc_auc_ci_high"] = sv.block_bootstrap_auc(
                        d.y.values[mask], p, d.block.values[mask])
                if split == "test_2025" and name == "core":
                    t = sv.reliability(d.y.values[mask], p); t.insert(0, "label_set", label_set)
                    rel.append(t)
                rows.append(r)
                if split == "validation_2024":
                    val_scores[name] = r["roc_auc"]
            if ib and name == "core":
                core_model, core_X, core_d, core_tr = m, X, d, tr
        # spatial generalisation: block-grouped OOF over 2022-2025
        if ib:
            X = sv.matrix(d, sv.CORE)
            p_sp = sv.oof_predict(d, X, d.block.values)
            r = {"label_set": label_set, "feature_set": "core", "split": "spatial_blocks_2022_2025",
                 **sv.metrics(d.y.values, p_sp, sv.best_f1_threshold(d.y.values, p_sp), d.fatal.values)}
            rows.append(r)
            write_json({
                "validation_auc_by_feature_set": val_scores,
                "best_validation_auc": max(val_scores, key=val_scores.get),
                "served_and_explained": "core",
                "reason": "Coordinates and police force raise validation AUC, but force is administrative "
                          "(recording practice) and both act as location lookups; their gain cannot be "
                          "explained as road or environment risk. The served model therefore uses road, "
                          "environment and time only, and its SHAP is what the UI may show. Scores of the "
                          "geo/force variants are reported for transparency, not served."},
                out_dir / "feature_set_selection.json")

    # v1's shipped deployable model, scored prospectively on 2025 (it was trained on 2022-23)
    try:
        v1 = joblib.load(_v1_model_path())
        d = sv.prepare(coll, injury_based_only=False)
        te = d.collision_year == 2025
        X = d.loc[te].rename(columns={"hour": "Hour", "month": "Month", "day_of_year": "DayOfYear",
                                      "easting": "_e", "northing": "_n"})
        feats = v1.booster_.feature_name()
        Xv = X.reindex(columns=feats).apply(pd.to_numeric, errors="coerce").astype(np.float32)
        p = v1.predict_proba(Xv)[:, 1]
        import json as _json
        thr = _json.loads((_v1_model_path().parent / "deployable_vs_explanatory.json").read_text()
                          )["DEPLOYABLE"]["threshold"]            # v1's own threshold
        r = {"label_set": "all_records", "feature_set": "v1_deployable_model(24 feat)",
             "split": "test_2025", **sv.metrics(d.y.values[te], p, thr, d.fatal.values[te])}
        r["roc_auc_ci_low"], r["roc_auc_ci_high"] = sv.block_bootstrap_auc(
            d.y.values[te], p, d.block.values[te])
        rows.append(r)
    except Exception as e:                                    # noqa: BLE001 -- comparison is optional
        log.warning("v1 deployable model comparison skipped: %s", e)

    res = pd.DataFrame(rows)
    write_csv(res.round(5), REPORTS / "severity_results.csv")
    write_csv(pd.concat(rel, ignore_index=True).round(5), REPORTS / "severity_reliability_2025.csv")

    # final deployable model + SHAP on the 2025 test rows
    joblib.dump(core_model, out_dir / "severity_deployable_v2.joblib")
    te = (core_d.collision_year == 2025).values
    Xte = sv._align_categories(core_X[core_tr], core_X[te].copy())
    glob, per, rank = sv.shap_tables(core_model, Xte, core_d.loc[te, sv.CORE])
    write_csv(glob.round(6), out_dir / "shap_global.csv")
    write_csv(per.round(6), out_dir / "shap_per_level.csv")
    write_csv(rank.round(6), out_dir / "shap_ranking.csv")
    write_json({"features": sv.CORE, "categorical": sorted(sv.CATEGORICAL & set(sv.CORE)),
                "train_years": [2022, 2023], "label": "KSI collision, injury-based records only",
                "params": sv.PARAMS}, out_dir / "severity_deployable_v2_meta.json")
    log.info("severity done:\n%s", res[["label_set", "feature_set", "split", "roc_auc", "pr_auc", "brier_skill", "ece"]])


def _v1_model_path():
    from .config import ML_DIR
    return ML_DIR / "models" / "severity_deployable_model.joblib"


def step_forecast() -> None:
    from .outputs import run_forecast
    out = run_forecast(_context(), _load_frozen())
    log.info("forecast written: %d segments", len(out))


def step_coverage() -> None:
    """National KSI coverage of the scored network, by window, target and road class."""
    from . import network, snap, stats19
    from .coverage import coverage_table, summarise
    coll = stats19.load_collisions()
    seg, _, _ = network.load_segments()
    assign = pd.read_parquet(snap.ASSIGN_PARQUET)
    out = {}
    windows = {"v1_target_2022_2023": [2022, 2023], "holdout_target_2024_2025": [2024, 2025],
               "forecast_history_2023_2025": [2023, 2024, 2025]}
    rows = []
    for wname, yrs in windows.items():
        for t in ["adj_ksi_cas", "n_ksi_cas", "is_ksi_collision"]:
            d = coverage_table(coll, assign, seg, yrs, target=t)
            s_ = summarise(d)
            out[f"{wname}|{t}"] = s_
            for b, v in s_["by_bucket"].items():
                rows.append({"window": wname, "target": t, "bucket": b, "share": v,
                             "national_total": s_["national_total"]})
    # by STATS19 road class: national share and share captured by scored segments (holdout window, primary)
    d = coverage_table(coll, assign, seg, [2024, 2025], target="adj_ksi_cas")
    cls = d.groupby("stats19_class").apply(lambda g: pd.Series({
        "adj_ksi": g.y.sum(), "share_of_national": g.y.sum() / d.y.sum(),
        "share_on_scored_segments": g.y[g.bucket == "scored"].sum() / g.y.sum(),
        "share_on_access_roads": g.y[g.bucket == "access_road"].sum() / g.y.sum(),
        "share_unassigned": g.y[g.bucket.isin(["no_road", "no_coords"])].sum() / g.y.sum()}))
    write_csv(cls.reset_index().round(5), REPORTS / "coverage_by_stats19_class.csv")
    write_csv(pd.DataFrame(rows), REPORTS / "coverage_buckets.csv")
    write_json(out, REPORTS / "coverage_summary.json")
    log.info("coverage: %s", {k: v["by_bucket"] for k, v in out.items()})
