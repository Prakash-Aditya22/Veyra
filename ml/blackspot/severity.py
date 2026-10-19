"""Severity classifier (KSI vs slight, collision level), audited separately from blackspots.

QUESTION
  Given that a collision happens on a road of this kind, in these conditions,
  at this time, how likely is it to kill or seriously injure someone? Inputs
  are only what is knowable without the collision's outcome (road layout,
  speed limit, junction, light, weather, surface, time, place). Crash-specific
  facts (number of vehicles, impact point, casualty ages) are not deployable
  and are only tested as an explicitly labelled variant.

LABEL CONSISTENCY
  "Serious" depends on how the force recorded injuries. The primary analysis
  keeps collisions whose every casualty was recorded under injury-based
  reporting (CRASH/COPA), so the label means the same thing in training and
  test years even though forces switched systems during 2024-25. A variant on
  all records is reported for comparison.

VALIDATION
  temporal : train 2022-23; feature-set choice on 2024; final test 2025 (untouched until then)
  spatial  : 2022-25, 50 km blocks in 5 groups, each group predicted by a model fitted without it
  threshold: maximises F1 on OUT-OF-FOLD training predictions (block-grouped 5-fold), never in-sample

INTERPRETATION
  SHAP is computed for the deployable model that is actually evaluated. Levels
  are ranked by between-level spread; unknown/missing levels and the
  administrative police_force are flagged and not presented as causes. SHAP
  values are model attributions (associations), not causal effects.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .config import SEED

log = logging.getLogger("blackspot.severity")

CORE = ["road_type", "speed_limit", "junction_detail", "junction_control", "first_road_class",
        "second_road_class", "urban_or_rural_area", "light_conditions", "weather_conditions",
        "road_surface_conditions", "carriageway_hazards", "pedestrian_crossing", "trunk_road_flag",
        "hour", "day_of_week", "month"]
CATEGORICAL = {"road_type", "junction_detail", "junction_control", "first_road_class", "second_road_class",
               "urban_or_rural_area", "light_conditions", "weather_conditions", "road_surface_conditions",
               "carriageway_hazards", "pedestrian_crossing", "trunk_road_flag", "day_of_week", "police_force"}
FEATURE_SETS = {
    "core": CORE,
    "core+geo": CORE + ["easting", "northing"],
    "core+geo+force": CORE + ["easting", "northing", "police_force"],
    "core+vehicles(not deployable)": CORE + ["number_of_vehicles"],
}
# special_conditions_at_site is excluded: its "unknown" share jumps from ~7% (2023)
# to 61% (2024) and 87% (2025) with the revised STATS19 specification.

# Where the data use a code differently from the guide's label (verified by cross-tabulation
# in ml/reports/data_quality.md), the label shown says what the code means in practice.
DATA_USAGE_OVERRIDES = {
    "junction_control": {-1: ("Not at junction (coded -1; guide label: data missing)", False)},
    "junction_detail": {0: ("Not at junction or within 20 m - includes roundabouts, mini-roundabouts "
                            "and slip roads under the 2024 coding", False)},
}

PARAMS = dict(objective="binary", n_estimators=400, learning_rate=0.05, num_leaves=63, min_child_samples=100,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
              random_state=SEED, n_jobs=-1, verbose=-1)


def prepare(coll: pd.DataFrame, injury_based_only: bool = True) -> pd.DataFrame:
    d = coll[coll.collision_year.between(2022, 2025)].copy()
    if injury_based_only:
        d = d[d.injury_based_share == 1.0]
    d["y"] = d.collision_severity.isin([1, 2]).astype(int)
    d["fatal"] = (d.collision_severity == 1).astype(int)
    from .experiment import block_id
    d["block"] = block_id(d.easting.fillna(0), d.northing.fillna(0))
    return d.reset_index(drop=True)


def matrix(d: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    X = d[cols].copy()
    for c in cols:
        if c in CATEGORICAL:
            X[c] = pd.Categorical(pd.to_numeric(X[c], errors="coerce").fillna(-1).astype(int))
        else:
            X[c] = pd.to_numeric(X[c], errors="coerce").astype(float)
    return X


def _align_categories(Xtr, Xte):
    for c in Xtr.columns:
        if isinstance(Xtr[c].dtype, pd.CategoricalDtype):
            cats = Xtr[c].cat.categories
            Xte[c] = pd.Categorical(Xte[c].astype(int), categories=cats)   # unseen level -> NaN
    return Xte


def fit(X, y, params=None):
    from lightgbm import LGBMClassifier
    p = dict(PARAMS); p.update(params or {})
    return LGBMClassifier(**p).fit(X, y)


def oof_predict(d, X, groups, k=5, params=None):
    p = np.zeros(len(d))
    ug = np.unique(groups)
    rng = np.random.default_rng(SEED)
    fold_of = dict(zip(ug, rng.integers(0, k, len(ug))))
    f = np.array([fold_of[g] for g in groups])
    for j in range(k):
        tr, te = f != j, f == j
        m = fit(X[tr], d.y.values[tr], params)
        p[te] = m.predict_proba(_align_categories(X[tr], X[te].copy()))[:, 1]
    return p


def best_f1_threshold(y, p):
    from sklearn.metrics import precision_recall_curve
    pr, rc, th = precision_recall_curve(y, p)
    f1 = 2 * pr * rc / np.clip(pr + rc, 1e-12, None)
    return float(th[np.argmax(f1[:-1])])


def metrics(y, p, thr, fatal=None) -> dict:
    from sklearn.metrics import (average_precision_score, brier_score_loss, f1_score, log_loss,
                                 precision_score, recall_score, roc_auc_score)
    base = y.mean()
    pred = (p >= thr).astype(int)
    out = {"n": int(len(y)), "ksi_rate": float(base), "roc_auc": roc_auc_score(y, p),
           "pr_auc": average_precision_score(y, p), "pr_auc_lift": average_precision_score(y, p) / base,
           "brier": brier_score_loss(y, p), "brier_skill": 1 - brier_score_loss(y, p) / (base * (1 - base)),
           "log_loss": log_loss(y, np.clip(p, 1e-6, 1 - 1e-6)), "ece": expected_calibration_error(y, p),
           "mean_pred": float(p.mean()), "threshold": thr,
           "precision_ksi": precision_score(y, pred, zero_division=0),
           "recall_ksi": recall_score(y, pred), "f1_ksi": f1_score(y, pred),
           "precision_slight": precision_score(1 - y, 1 - pred, zero_division=0),
           "recall_slight": recall_score(1 - y, 1 - pred), "f1_slight": f1_score(1 - y, 1 - pred),
           "macro_f1": f1_score(y, pred, average="macro")}
    if fatal is not None and fatal.sum() > 0:
        out["fatal_ap_using_pksi"] = average_precision_score(fatal, p)
        out["fatal_rate"] = float(fatal.mean())
    return out


def expected_calibration_error(y, p, bins=10):
    q = np.clip((p * bins).astype(int), 0, bins - 1)
    e = 0.0
    for b in range(bins):
        m = q == b
        if m.any():
            e += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(e)


def reliability(y, p, bins=10):
    q = np.clip((p * bins).astype(int), 0, bins - 1)
    t = pd.DataFrame({"bin": q, "y": y, "p": p}).groupby("bin").agg(n=("y", "size"), observed=("y", "mean"),
                                                                     predicted=("p", "mean")).reset_index()
    return t


def block_bootstrap_auc(y, p, blocks, n=200, seed=SEED):
    from sklearn.metrics import roc_auc_score
    from .evaluation import block_weights
    vals = []
    for w in block_weights(blocks, n, seed):
        keep = w > 0
        rep = np.repeat(np.flatnonzero(keep), w[keep].astype(int))
        vals.append(roc_auc_score(y[rep], p[rep]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


# ------------------------------------------------------------------ SHAP
def shap_tables(model, X: pd.DataFrame, raw: pd.DataFrame, max_rows=20_000, seed=SEED):
    import shap
    from . import codes
    idx = np.random.default_rng(seed).choice(len(X), size=min(max_rows, len(X)), replace=False)
    Xs = X.iloc[idx]
    sv = shap.TreeExplainer(model).shap_values(Xs)
    if isinstance(sv, list):
        sv = sv[1]
    sv = np.asarray(sv)
    if sv.ndim == 3:
        sv = sv[:, :, -1]
    glob = pd.DataFrame({"feature": X.columns, "mean_abs_shap": np.abs(sv).mean(0)}) \
        .sort_values("mean_abs_shap", ascending=False)
    per, rank = [], []
    for j, c in enumerate(X.columns):
        lv = pd.to_numeric(raw[c].iloc[idx], errors="coerce").values
        if c in ("hour", "month"):
            pass
        elif c == "speed_limit":
            pass
        elif c not in CATEGORICAL:
            continue
        t = pd.DataFrame({"level": lv, "shap": sv[:, j]}).groupby("level").shap.agg(
            n="size", mean_shap="mean", std_shap="std").reset_index()
        t = t[t.n >= 50]
        if len(t) < 2:
            continue
        lab = codes.labels(c) if c not in ("hour", "month", "speed_limit", "police_force") else {}
        unk = codes.unknown_codes(c) if lab else ({-1, 99} if c == "speed_limit" else {-1})
        lab, unk = dict(lab), set(unk)
        for code, (text, is_unk) in DATA_USAGE_OVERRIDES.get(c, {}).items():
            lab[code] = text
            (unk.add if is_unk else unk.discard)(code)
        t["label"] = [lab.get(int(v), str(int(v))) if np.isfinite(v) else "NA" for v in t.level]
        t["unknown_level"] = t.level.isin(unk)
        t["low_sample"] = t.n < 200
        t.insert(0, "feature", c)
        per.append(t)
        known = t[~t.unknown_level]
        for name, tt in [("all_levels", t), ("known_levels_only", known)]:
            if len(tt) < 2:
                continue
            w = tt.n / tt.n.sum()
            mu = (w * tt.mean_shap).sum()
            rank.append({"feature": c, "levels": "all" if name == "all_levels" else "known",
                         "n_levels": len(tt), "spread": float(np.sqrt((w * (tt.mean_shap - mu) ** 2).sum())),
                         "range": float(tt.mean_shap.max() - tt.mean_shap.min()),
                         "administrative": c == "police_force",
                         "unknown_share": float(t[t.unknown_level].n.sum() / t.n.sum())})
    rk = pd.DataFrame(rank).sort_values(["levels", "spread"], ascending=[True, False])
    return glob, pd.concat(per, ignore_index=True), rk
