"""
SEVERITY MODEL -- final deliverable.

WINDOW: 2022-2023 only. The severity-share diagnostic showed Grievous
drifting 14.3% -> 22.5% (2015->2023) as police forces converted to
injury-based reporting, and it never settles. Training across that drift
teaches the model which reporting regime a force used rather than what makes
a crash severe. 2022 (22.01%) and 2023 (22.48%) are adjacent and stable, and
still give 210k collisions -- ample. Recency is a bonus, not the reason.

OUTPUTS
  1. KSI binary model      -- the DfT-standard target, 23% positive
  2. Three-class model     -- for continuity with the classification framing
  3. Global SHAP
  4. SUB-CATEGORY SHAP     -- per level, of every categorical, for both stages
  5. API artefacts         -- model + payload for the web service

Sub-category SHAP is ranked by BETWEEN-LEVEL SPREAD, not mean|SHAP|. A
mostly-missing column collapses into one giant "unknown" level that shifts
every prediction by the same amount: high mean|SHAP|, zero discriminative
value. Spread measures what actually changes when the level changes.
"""
import warnings; warnings.filterwarnings("ignore")
import json
import os
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (classification_report, confusion_matrix, roc_auc_score,
                             average_precision_score, f1_score, precision_score,
                             recall_score, accuracy_score)
from lightgbm import LGBMClassifier
import shap
import joblib

RS = 42
YEARS = [2022, 2023]
OUT = "severity_outputs"
os.makedirs(OUT, exist_ok=True)
os.makedirs(f"{OUT}/subcategory_shap", exist_ok=True)

# STATS19 code -> label for the fields that matter interpretively. Only codes
# that are stable across the modern data guide are mapped; anything else stays
# numeric rather than risk a wrong label.
DECODE = {
    "light_conditions": {1: "Daylight", 4: "Dark-lit", 5: "Dark-unlit",
                         6: "Dark-no lighting", 7: "Dark-unknown"},
    "weather_conditions": {1: "Fine", 2: "Rain", 3: "Snow", 4: "Fine+wind",
                           5: "Rain+wind", 6: "Snow+wind", 7: "Fog/mist",
                           8: "Other", 9: "Unknown"},
    "road_surface_conditions": {1: "Dry", 2: "Wet", 3: "Snow", 4: "Frost/ice",
                                5: "Flood", 6: "Oil", 7: "Mud"},
    "road_type": {1: "Roundabout", 2: "One way", 3: "Dual carriageway",
                  6: "Single carriageway", 7: "Slip road", 9: "Unknown"},
    "urban_or_rural_area": {1: "Urban", 2: "Rural", 3: "Unallocated"},
    "first_road_class": {1: "Motorway", 2: "A(M)", 3: "A road", 4: "B road",
                         5: "C road", 6: "Unclassified"},
    "junction_detail": {0: "Not at junction", 1: "Roundabout", 2: "Mini-roundabout",
                        3: "T/staggered", 5: "Slip road", 6: "Crossroads",
                        7: "4+ arms", 8: "Private drive", 9: "Other"},
    "junction_control": {0: "Not at junction", 1: "Authorised person",
                         2: "Auto signal", 3: "Stop sign", 4: "Give way/uncontrolled"},
    "day_of_week": {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"},
}

print("loading ...")
df = pd.read_csv("stats19_recent.csv", low_memory=False)
df = df[df.collision_year.isin(YEARS)].reset_index(drop=True)
print(f"  {len(df):,} collisions ({YEARS[0]}-{YEARS[-1]})")

y3 = LabelEncoder().fit(df.Accident_Severity)
y_3class = y3.transform(df.Accident_Severity)
names3 = y3.classes_.tolist()
y_ksi = (df.Accident_Severity != "Minor").astype(int).values
print(f"  KSI positive rate: {y_ksi.mean()*100:.2f}%")
print(f"  {df.Accident_Severity.value_counts().to_dict()}")

DROP = {"Accident_Severity", "collision_index", "collision_year",
        "did_police_officer_attend_scene_of_accident"}   # attendance responds to severity
FEATS = [c for c in df.columns if c not in DROP]
X = df[FEATS].apply(pd.to_numeric, errors="coerce").astype(np.float32)
X = X.replace([np.inf, -np.inf], np.nan)
print(f"  {X.shape[1]} features")

tr, te = train_test_split(np.arange(len(df)), test_size=0.2, random_state=RS, stratify=y_3class)


def mk(**kw):
    p = dict(n_estimators=600, num_leaves=127, learning_rate=0.05, min_child_samples=40,
             colsample_bytree=0.6, reg_alpha=1.0, reg_lambda=1.0,
             random_state=RS, n_jobs=-1, verbose=-1)
    p.update(kw)
    return LGBMClassifier(**p)


# ============================================================
# 1. KSI BINARY -- the DfT-standard target
# ============================================================
print("\n" + "=" * 78)
print("MODEL 1 -- KSI (Killed or Seriously Injured) vs Slight")
print("=" * 78)
m_ksi = mk().fit(X.iloc[tr], y_ksi[tr])
p_ksi = m_ksi.predict_proba(X.iloc[te])[:, 1]
auc = roc_auc_score(y_ksi[te], p_ksi)
ap = average_precision_score(y_ksi[te], p_ksi)
base = y_ksi[te].mean()
print(f"  ROC-AUC  {auc:.4f}")
print(f"  PR-AUC   {ap:.4f}   (no-skill {base:.4f}, lift {ap/base:.2f}x)")

# threshold chosen on training data only
tr_oof = m_ksi.predict_proba(X.iloc[tr])[:, 1]
ths = np.arange(0.05, 0.96, 0.01)
best_t = max(ths, key=lambda t: f1_score(y_ksi[tr], (tr_oof >= t).astype(int)))
pred_ksi = (p_ksi >= best_t).astype(int)
print(f"  threshold {best_t:.2f} (selected on training data)")
print(classification_report(y_ksi[te], pred_ksi, target_names=["Slight", "KSI"], digits=3))

print("  gains -- targeting the highest-risk crashes:")
o = np.argsort(-p_ksi); t_ = y_ksi[te][o]
for f in [.01, .05, .10, .20]:
    k = int(len(t_) * f)
    print(f"    top {f:>4.0%}: {t_[:k].mean()*100:5.2f}% KSI  "
          f"(lift {t_[:k].mean()/base:4.2f}x)  captures {t_[:k].sum()/t_.sum()*100:5.1f}%")

# ============================================================
# 2. THREE-CLASS
# ============================================================
print("\n" + "=" * 78)
print("MODEL 2 -- three-class (Fatal / Grievous / Minor)")
print("=" * 78)
m3 = mk().fit(X.iloc[tr], y_3class[tr])
P3 = m3.predict_proba(X.iloc[te])
FI, GI, MI = (names3.index(c) for c in ["Fatal", "Grievous", "Minor"])

# per-class multipliers tuned on training predictions, then frozen
P3tr = m3.predict_proba(X.iloc[tr])
grid = np.concatenate([np.arange(.25, 3.01, .25), np.arange(3.5, 12.1, .5)])
best = (-1., 1., 1.)
for mf in grid:
    sf = P3tr[:, FI] * mf
    for mg in grid:
        s = f1_score(y_3class[tr], np.argmax(np.column_stack(
            [sf, P3tr[:, GI] * mg, P3tr[:, MI]]), 1), average="macro")
        if s > best[0]:
            best = (s, mf, mg)
_, MF_, MG_ = best
pred3 = np.argmax(np.column_stack([P3[:, FI] * MF_, P3[:, GI] * MG_, P3[:, MI]]), 1)
print(f"  multipliers Fatal x{MF_:.2f} Grievous x{MG_:.2f}")
print(classification_report(y_3class[te], pred3, target_names=names3, digits=3))
print(pd.DataFrame(confusion_matrix(y_3class[te], pred3), index=names3, columns=names3))
ap3 = [average_precision_score((y_3class[te] == i).astype(int), P3[:, i]) for i in range(3)]
print("\n  average precision vs no-skill:")
for i, n in enumerate(names3):
    b = (y_3class[te] == i).mean()
    print(f"    {n:9s} AP {ap3[i]:.4f}  no-skill {b:.4f}  lift {ap3[i]/b:.2f}x")

# ============================================================
# 3. SHAP
# ============================================================
print("\n" + "=" * 78)
print("SHAP")
print("=" * 78)
n_shap = min(60000, len(te))
idx = te[:n_shap]
sv = shap.TreeExplainer(m_ksi).shap_values(X.iloc[idx])
if isinstance(sv, list):
    sv = sv[1]
sv = np.asarray(sv)
if sv.ndim == 3:
    sv = sv[:, :, -1]

imp = pd.DataFrame({"feature": FEATS, "mean_abs_shap": np.abs(sv).mean(0)}
                   ).sort_values("mean_abs_shap", ascending=False)
imp.to_csv(f"{OUT}/global_shap_importance.csv", index=False)
print("\nglobal importance (top 15):")
print(imp.head(15).round(4).to_string(index=False))

# ============================================================
# 4. SUB-CATEGORY SHAP -- per level of every categorical
# ============================================================
print("\n" + "=" * 78)
print("SUB-CATEGORY SHAP -- ranked by BETWEEN-LEVEL SPREAD")
print("=" * 78)
CATS = [c for c in ["light_conditions", "weather_conditions", "road_surface_conditions",
                    "road_type", "urban_or_rural_area", "first_road_class",
                    "junction_detail", "junction_control", "day_of_week",
                    "speed_limit", "police_force", "local_authority_district"]
        if c in FEATS]

rows, summary = [], []
sub = df.iloc[idx]
for c in CATS:
    j = FEATS.index(c)
    lv = sub[c]
    d = pd.DataFrame({"level": lv.values, "shap": sv[:, j]})
    g = d.groupby("level")["shap"]
    t = pd.DataFrame({"n": g.count(), "mean_shap": g.mean(),
                      "std_shap": g.std().fillna(0),
                      "mean_abs_shap": g.apply(lambda s: s.abs().mean())}).reset_index()
    t = t[t.n >= 50]
    if len(t) < 2:
        continue
    t["label"] = t.level.map(DECODE.get(c, {})).fillna(t.level.astype(str))
    t["low_sample"] = t.n < 200
    t.insert(0, "category", c)
    t = t.sort_values("mean_shap", ascending=False)
    safe = c.replace("/", "_")
    t.to_csv(f"{OUT}/subcategory_shap/{safe}.csv", index=False)
    summary.append(t)

    w = t.n / t.n.sum()
    mu = (t.mean_shap * w).sum()
    spread = np.sqrt((w * (t.mean_shap - mu) ** 2).sum())
    rows.append({"category": c, "levels": len(t), "spread": spread,
                 "range": t.mean_shap.max() - t.mean_shap.min(),
                 "mean_abs_shap": t.mean_abs_shap.mean()})

rank = pd.DataFrame(rows).sort_values("spread", ascending=False)
rank.to_csv(f"{OUT}/subcategory_ranking.csv", index=False)
pd.concat(summary, ignore_index=True).to_csv(f"{OUT}/subcategory_shap_all.csv", index=False)
print(rank.round(4).to_string(index=False))

print("\ndirection by level -- what pushes a crash toward KSI (+) or slight (-):")
for c in rank.category.head(5):
    t = pd.concat(summary)
    t = t[t.category == c].sort_values("mean_shap", ascending=False)
    top = t.head(3)[["label", "n", "mean_shap"]].values
    bot = t.tail(2)[["label", "n", "mean_shap"]].values
    print(f"\n  [{c}]")
    for l, n, s in top:
        print(f"    {str(l):24s} n={int(n):>7,}  {s:+.4f}")
    print("    ...")
    for l, n, s in bot:
        print(f"    {str(l):24s} n={int(n):>7,}  {s:+.4f}")

# ============================================================
# 5. ARTEFACTS FOR THE SERVICE
# ============================================================
joblib.dump(m_ksi, f"{OUT}/severity_ksi_model.joblib")
joblib.dump(m3, f"{OUT}/severity_3class_model.joblib")
json.dump({
    "window": YEARS, "n_collisions": int(len(df)), "n_features": int(X.shape[1]),
    "ksi": {"roc_auc": float(auc), "pr_auc": float(ap), "no_skill": float(base),
            "lift": float(ap / base), "threshold": float(best_t),
            "precision": float(precision_score(y_ksi[te], pred_ksi)),
            "recall": float(recall_score(y_ksi[te], pred_ksi)),
            "f1": float(f1_score(y_ksi[te], pred_ksi))},
    "three_class": {"macro_f1": float(f1_score(y_3class[te], pred3, average="macro")),
                    "accuracy": float(accuracy_score(y_3class[te], pred3)),
                    "multipliers": {"Fatal": float(MF_), "Grievous": float(MG_)},
                    "average_precision": {n: float(ap3[i]) for i, n in enumerate(names3)}},
    "feature_order": FEATS,
}, open(f"{OUT}/severity_metrics.json", "w"), indent=2)

print(f"\nSaved to {OUT}/: models, metrics, global SHAP, "
      f"{len(summary)} sub-category SHAP tables")
