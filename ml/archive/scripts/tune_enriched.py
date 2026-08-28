"""
Hyperparameter tuning on the ENRICHED feature set.

Every enriched result so far used hand-picked hyperparameters
(n_estimators=400, lr=0.05, num_leaves=63). Tuning was done earlier on the
ORIGINAL 20 columns, where it plateaued -- but the feature set has since
changed completely (18 -> 201 columns), so that plateau says nothing about
this configuration. 201 features may want deeper trees, more leaves, or
stronger regularisation.

Optimised for macro Average Precision, not macro-F1. AP is threshold-free, so
it measures how much information the model extracts; macro-F1 depends on the
decision rule, which is tuned separately afterwards. Optimising AP first and
thresholding second is the principled order -- doing it the other way lets a
lucky decision boundary hide a weaker model.
"""
import warnings; warnings.filterwarnings("ignore")
import json
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, RandomizedSearchCV, StratifiedKFold
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (average_precision_score, f1_score, roc_auc_score,
                             classification_report, confusion_matrix, make_scorer)
from lightgbm import LGBMClassifier

RS = 42
N_ITER = 25

e = pd.read_csv("accidents_enriched_explanatory.csv", low_memory=False)
e = e[e["v_n_vehicle_rows"].notna()].reset_index(drop=True)
sev = e["Accident_Severity"]
le = LabelEncoder().fit(sev)
y = le.transform(sev)
names = le.classes_.tolist()
FI, GI, MI = (names.index(c) for c in ["Fatal", "Grievous", "Minor"])
y_ksi = (sev != "Minor").astype(int).values

CATS = ["Day_of_Week", "Junction_Control", "Junction_Detail", "Light_Conditions",
        "Local_Authority_(District)", "Police_Force", "Road_Surface_Conditions",
        "Road_Type", "Urban_or_Rural_Area", "Weather_Conditions", "Vehicle_Type"]
e["Hour"] = pd.to_datetime(e["Time"], format="%H:%M", errors="coerce").dt.hour
e["Month"] = pd.to_datetime(e["Accident_Date"], errors="coerce").dt.month
X = e[CATS + ["Latitude", "Longitude", "Number_of_Casualties", "Number_of_Vehicles",
              "Speed_limit", "Hour", "Month"]].copy()
for c in CATS:
    X[c] = LabelEncoder().fit_transform(X[c].fillna("Unknown").astype(str))
new = [c for c in e.columns if c[:2] in ("v_", "c_", "k_") and "police_officer_attend" not in c]
N = e[new].copy()
for c in N.columns:
    if N[c].dtype == object:
        N[c] = LabelEncoder().fit_transform(N[c].fillna("NA").astype(str))
X = pd.concat([X, N], axis=1).apply(pd.to_numeric, errors="coerce")
X = X.replace([np.inf, -np.inf], np.nan)
print(f"{len(e):,} rows x {X.shape[1]} features")

tr, te = train_test_split(np.arange(len(e)), test_size=0.2, random_state=RS, stratify=y)


def macro_ap(y_true, proba):
    return float(np.mean([average_precision_score((y_true == i).astype(int), proba[:, i])
                          for i in range(proba.shape[1])]))


scorer = make_scorer(macro_ap, response_method="predict_proba")

grid = {
    "n_estimators": [300, 500, 800, 1200],
    "learning_rate": [0.02, 0.03, 0.05, 0.08],
    "num_leaves": [31, 63, 127, 255],
    "min_child_samples": [20, 40, 80, 150],
    "colsample_bytree": [0.5, 0.7, 0.9],
    "subsample": [0.7, 0.9, 1.0],
    "reg_alpha": [0, 0.1, 1.0],
    "reg_lambda": [0.5, 1.0, 5.0],
    "max_depth": [-1, 8, 12],
}

print(f"\nRandomizedSearchCV: {N_ITER} candidates x 3 folds, scoring macro-AP ...")
search = RandomizedSearchCV(
    LGBMClassifier(class_weight="balanced", random_state=RS, n_jobs=-1, verbose=-1),
    grid, n_iter=N_ITER, scoring=scorer, cv=3, random_state=RS, n_jobs=1, verbose=2, refit=True)
search.fit(X.iloc[tr], y[tr])
print(f"\nbest CV macro-AP: {search.best_score_:.4f}")
print(f"best params: {search.best_params_}")

# baseline = the hand-picked configuration used for every enriched result so far
base = LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=63,
                      min_child_samples=40, class_weight="balanced",
                      random_state=RS, n_jobs=-1, verbose=-1).fit(X.iloc[tr], y[tr])

# threshold tuning on OOF, applied to whichever model, so the comparison is fair
def oof_multipliers(model_params):
    oof = np.zeros((len(tr), 3))
    for a, b in StratifiedKFold(3, shuffle=True, random_state=RS).split(tr, y[tr]):
        m = LGBMClassifier(class_weight="balanced", random_state=RS, n_jobs=-1,
                           verbose=-1, **model_params).fit(X.iloc[tr[a]], y[tr[a]])
        oof[b] = m.predict_proba(X.iloc[tr[b]])
    g = np.concatenate([np.arange(.25, 3.01, .25), np.arange(3.5, 12.1, .5)])
    best = (-1., 1., 1.)
    for mf in g:
        sf = oof[:, FI] * mf
        for mg in g:
            s = f1_score(y[tr], np.argmax(np.column_stack([sf, oof[:, GI] * mg, oof[:, MI]]), 1),
                         average="macro")
            if s > best[0]:
                best = (s, mf, mg)
    return best[1], best[2]


rows = []
for tag, model, params in [("hand-picked", base, dict(n_estimators=400, learning_rate=0.05,
                                                       num_leaves=63, min_child_samples=40)),
                            ("tuned", search.best_estimator_, search.best_params_)]:
    P = model.predict_proba(X.iloc[te])
    mf, mg = oof_multipliers(params)
    pred = np.argmax(np.column_stack([P[:, FI] * mf, P[:, GI] * mg, P[:, MI]]), 1)
    ap = [average_precision_score((y[te] == i).astype(int), P[:, i]) for i in range(3)]
    o = np.argsort(-P[:, FI]); t = (y[te] == FI).astype(int)[o]
    rows.append({"config": tag, "macro_AP": float(np.mean(ap)), "AP_Fatal": ap[0],
                 "AP_Grievous": ap[1], "macro_F1_tuned": f1_score(y[te], pred, average="macro"),
                 "top1pct": t[:int(len(t) * .01)].mean(),
                 "capture20": t[:int(len(t) * .2)].sum() / t.sum(),
                 "mult_F": mf, "mult_G": mg})
    if tag == "tuned":
        best_pred, best_P = pred, P

r = pd.DataFrame(rows)
print("\n" + "=" * 100)
print("HAND-PICKED vs TUNED (enriched features, held-out test)")
print("=" * 100)
print(r.round(4).to_string(index=False))

print("\n--- tuned + threshold-tuned ---")
print(classification_report(y[te], best_pred, target_names=names, digits=3))
print(pd.DataFrame(confusion_matrix(y[te], best_pred), index=names, columns=names))

o = np.argsort(-best_P[:, FI]); t = (y[te] == FI).astype(int)[o]; b = t.mean()
print(f"\nFatal risk ranking (base {b*100:.2f}%):")
for f in [.01, .05, .1, .2, .3]:
    k = int(len(t) * f)
    print(f"  top {f:>4.0%}: {t[:k].mean()*100:6.2f}%  lift {t[:k].mean()/b:5.2f}x  "
          f"captured {t[:k].sum()/t.sum()*100:5.1f}%")

r.to_csv("tuned_enriched_results.csv", index=False)
json.dump({"best_params": search.best_params_, "cv_macro_ap": float(search.best_score_)},
          open("tuned_enriched_config.json", "w"), indent=2)
print("\nSaved: tuned_enriched_results.csv, tuned_enriched_config.json")
