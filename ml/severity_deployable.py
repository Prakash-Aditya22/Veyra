"""
CAN THE SEVERITY MODEL ACTUALLY PREDICT? -- deployable vs explanatory.

The 236-feature model scores well, but many of those features are only known
once a crash has been investigated: casualty ages, whether a pedestrian was
struck, first point of impact, vehicle manoeuvre. A live service asked "how
severe is a crash likely to be on this stretch of road, in these conditions?"
has none of them.

So two models are trained and compared on the SAME rows and split:

  DEPLOYABLE  -- only what is knowable BEFORE/INDEPENDENT of the outcome:
                 road layout, speed limit, junction, weather, light, surface,
                 time, location. This is what the web service can actually run.

  EXPLANATORY -- everything, including post-crash detail. Useful for asking
                 "what made this crash severe?", useless for prediction.

The gap between them is the honest cost of deployability, and the deployable
number is the one to quote for the service.
"""
import warnings; warnings.filterwarnings("ignore")
import json
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import (roc_auc_score, average_precision_score, f1_score,
                             classification_report, precision_score, recall_score)
from lightgbm import LGBMClassifier
import joblib

RS = 42
YEARS = [2022, 2023]

print("loading ...")
df = pd.read_csv("stats19_recent.csv", low_memory=False)
df = df[df.collision_year.isin(YEARS)].reset_index(drop=True)
y = (df.Accident_Severity != "Minor").astype(int).values
print(f"  {len(df):,} collisions | KSI {y.mean()*100:.2f}%")

# Knowable before the outcome is determined: road, environment, time, place.
# number_of_vehicles is included (apparent immediately); number_of_casualties
# is NOT -- it is essentially the outcome.
DEPLOYABLE = [c for c in [
    "road_type", "speed_limit", "junction_detail", "junction_control",
    "first_road_class", "first_road_number", "second_road_class",
    "urban_or_rural_area", "light_conditions", "weather_conditions",
    "road_surface_conditions", "special_conditions_at_site", "carriageway_hazards",
    "pedestrian_crossing", "trunk_road_flag", "number_of_vehicles",
    "latitude", "longitude", "local_authority_district", "police_force",
    "Hour", "Month", "DayOfYear", "day_of_week",
] if c in df.columns]

EXCLUDE_ALL = {"Accident_Severity", "collision_index", "collision_year",
               "did_police_officer_attend_scene_of_accident"}
EXPLANATORY = [c for c in df.columns if c not in EXCLUDE_ALL]

print(f"  deployable  {len(DEPLOYABLE)} features")
print(f"  explanatory {len(EXPLANATORY)} features")

tr, te = train_test_split(np.arange(len(df)), test_size=0.2, random_state=RS, stratify=y)
base = y[te].mean()
results = {}

for tag, feats in [("DEPLOYABLE", DEPLOYABLE), ("EXPLANATORY", EXPLANATORY)]:
    X = df[feats].apply(pd.to_numeric, errors="coerce").astype(np.float32)
    X = X.replace([np.inf, -np.inf], np.nan)
    m = LGBMClassifier(n_estimators=600, num_leaves=127, learning_rate=0.05,
                       min_child_samples=40, colsample_bytree=0.6,
                       reg_alpha=1.0, reg_lambda=1.0,
                       random_state=RS, n_jobs=-1, verbose=-1).fit(X.iloc[tr], y[tr])
    p = m.predict_proba(X.iloc[te])[:, 1]

    ptr = m.predict_proba(X.iloc[tr])[:, 1]
    th = max(np.arange(.05, .96, .01),
             key=lambda t: f1_score(y[tr], (ptr >= t).astype(int)))
    pred = (p >= th).astype(int)

    auc, ap = roc_auc_score(y[te], p), average_precision_score(y[te], p)
    o = np.argsort(-p); t_ = y[te][o]
    gains = {f"top{int(f*100)}pct": {
        "ksi_rate": float(t_[:int(len(t_)*f)].mean()),
        "lift": float(t_[:int(len(t_)*f)].mean()/base),
        "captured": float(t_[:int(len(t_)*f)].sum()/t_.sum())} for f in [.01, .05, .1, .2]}

    results[tag] = {"n_features": len(feats), "roc_auc": float(auc), "pr_auc": float(ap),
                    "no_skill": float(base), "lift": float(ap/base), "threshold": float(th),
                    "precision": float(precision_score(y[te], pred)),
                    "recall": float(recall_score(y[te], pred)),
                    "f1": float(f1_score(y[te], pred)), "gains": gains}

    print(f"\n{'='*74}\n{tag} -- {len(feats)} features\n{'='*74}")
    print(f"  ROC-AUC {auc:.4f}   PR-AUC {ap:.4f}  (no-skill {base:.4f}, lift {ap/base:.2f}x)")
    print(classification_report(y[te], pred, target_names=["Slight", "KSI"], digits=3))
    print("  gains:")
    for f in [.01, .05, .1, .2]:
        k = int(len(t_) * f)
        print(f"    top {f:>4.0%}: {t_[:k].mean()*100:5.2f}% KSI  lift {t_[:k].mean()/base:4.2f}x  "
              f"captures {t_[:k].sum()/t_.sum()*100:5.1f}%")

    if tag == "DEPLOYABLE":
        joblib.dump(m, "severity_outputs/severity_deployable_model.joblib")
        imp = pd.DataFrame({"feature": feats,
                            "gain": m.booster_.feature_importance("gain")}
                           ).sort_values("gain", ascending=False)
        imp["share_pct"] = imp.gain / imp.gain.sum() * 100
        imp.to_csv("severity_outputs/deployable_feature_importance.csv", index=False)
        print("\n  top features the service will actually use:")
        print(imp.head(12).round(2).to_string(index=False))

d, e = results["DEPLOYABLE"], results["EXPLANATORY"]
print("\n" + "=" * 74)
print("THE COST OF BEING DEPLOYABLE")
print("=" * 74)
print(f"  ROC-AUC   {d['roc_auc']:.4f}  vs  {e['roc_auc']:.4f}   ({d['roc_auc']-e['roc_auc']:+.4f})")
print(f"  PR-AUC    {d['pr_auc']:.4f}  vs  {e['pr_auc']:.4f}   ({d['pr_auc']-e['pr_auc']:+.4f})")
print(f"  F1        {d['f1']:.4f}  vs  {e['f1']:.4f}   ({d['f1']-e['f1']:+.4f})")
print(f"\n  The deployable model keeps "
      f"{(d['pr_auc']-d['no_skill'])/(e['pr_auc']-e['no_skill'])*100:.0f}% of the "
      f"explanatory model's lift over chance.")

json.dump(results, open("severity_outputs/deployable_vs_explanatory.json", "w"), indent=2)
print("\nSaved: severity_outputs/severity_deployable_model.joblib, "
      "deployable_feature_importance.csv, deployable_vs_explanatory.json")
