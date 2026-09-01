"""
Model the 2009-2015 dataset and test whether 3.4x more data helped.

Direct comparison against the 2009-2010 result, using the same tuned
hyperparameters so only the data volume differs:
    2009-2010 (281,692 rows, 201 features): AP_Fatal 0.1460, macro-AP 0.4684,
    top1% 23.09%, capture@20% 81.2%

EXCLUSIONS
  collision_year  -- the model could otherwise fit year-specific artefacts
                     (Grievous drifts ~1pp across the window) which would not
                     generalise to a new year.
  did_police_officer_attend_scene_of_accident -- attendance is a RESPONSE to
                     severity, not a circumstance known at prediction time.
                     The earlier leak audit showed 100% of the gain survives
                     without it.
"""
import warnings; warnings.filterwarnings("ignore")
import json
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (average_precision_score, roc_auc_score, f1_score,
                             classification_report, confusion_matrix)
from lightgbm import LGBMClassifier

RS = 42
BEST = dict(n_estimators=1200, num_leaves=255, learning_rate=0.02,
            colsample_bytree=0.5, subsample=1.0, reg_alpha=1.0, reg_lambda=1.0,
            min_child_samples=40, max_depth=-1)

print("loading ...")
df = pd.read_csv("stats19_2009_2015.csv", low_memory=False)
print(f"  {len(df):,} rows x {df.shape[1]} columns")

le = LabelEncoder().fit(df["Accident_Severity"])
y = le.transform(df["Accident_Severity"])
names = le.classes_.tolist()
FI, GI, MI = (names.index(c) for c in ["Fatal", "Grievous", "Minor"])
y_ksi = (df["Accident_Severity"] != "Minor").astype(int).values

DROP = {"Accident_Severity", "collision_index", "collision_year",
        "did_police_officer_attend_scene_of_accident"}
X = df[[c for c in df.columns if c not in DROP]].copy()
for c in X.columns:
    if X[c].dtype == object:
        X[c] = LabelEncoder().fit_transform(X[c].fillna("NA").astype(str))
X = X.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
X = X.astype(np.float32)
print(f"  {X.shape[1]} features")

tr, te = train_test_split(np.arange(len(df)), test_size=0.2, random_state=RS, stratify=y)
print(f"  train {len(tr):,} / test {len(te):,}")

mk = lambda: LGBMClassifier(class_weight="balanced", random_state=RS, n_jobs=-1,
                            verbose=-1, **BEST)

print("\nout-of-fold probabilities for threshold tuning (3 folds) ...")
oof = np.zeros((len(tr), 3), dtype=np.float32)
for k, (a, b) in enumerate(StratifiedKFold(3, shuffle=True, random_state=RS).split(tr, y[tr]), 1):
    oof[b] = mk().fit(X.iloc[tr[a]], y[tr[a]]).predict_proba(X.iloc[tr[b]])
    print(f"  fold {k}/3")

grid = np.concatenate([np.arange(.25, 3.01, .25), np.arange(3.5, 12.1, .5)])
best = (-1., 1., 1.)
for mf in grid:
    sf = oof[:, FI] * mf
    for mg in grid:
        s = f1_score(y[tr], np.argmax(np.column_stack([sf, oof[:, GI] * mg, oof[:, MI]]), 1),
                     average="macro")
        if s > best[0]:
            best = (s, mf, mg)
_, MF, MG = best
print(f"multipliers: Fatal x{MF:.2f}  Grievous x{MG:.2f}  (OOF macro-F1 {best[0]:.4f})")

print("\nfinal fit ...")
model = mk().fit(X.iloc[tr], y[tr])
P = model.predict_proba(X.iloc[te])
ksi_auc = roc_auc_score(y_ksi[te], mk().fit(X.iloc[tr], y_ksi[tr]).predict_proba(X.iloc[te])[:, 1])

pred = np.argmax(np.column_stack([P[:, FI] * MF, P[:, GI] * MG, P[:, MI]]), 1)
ap = [average_precision_score((y[te] == i).astype(int), P[:, i]) for i in range(3)]
o = np.argsort(-P[:, FI]); t = (y[te] == FI).astype(int)[o]; base = t.mean()

res = {"rows": int(len(df)), "features": int(X.shape[1]),
       "macro_AP": float(np.mean(ap)), "AP_Fatal": ap[FI], "AP_Grievous": ap[GI],
       "macro_F1": f1_score(y[te], pred, average="macro"), "KSI_ROC_AUC": float(ksi_auc),
       "top1pct": float(t[:int(len(t) * .01)].mean()),
       "capture20": float(t[:int(len(t) * .2)].sum() / t.sum())}

PREV = {"rows": 281692, "features": 201, "macro_AP": 0.4684, "AP_Fatal": 0.1460,
        "AP_Grievous": 0.3084, "macro_F1": 0.4698, "KSI_ROC_AUC": 0.784,
        "top1pct": 0.2309, "capture20": 0.8119}

print("\n" + "=" * 92)
print("2009-2010 (281,692 rows)  vs  2009-2015 (1,040,051 rows)")
print("=" * 92)
cmp = pd.DataFrame([{"dataset": "2009-2010", **PREV}, {"dataset": "2009-2015", **res}])
print(cmp.round(4).to_string(index=False))
print("\nchange:")
for k in ["macro_AP", "AP_Fatal", "AP_Grievous", "macro_F1", "KSI_ROC_AUC", "top1pct", "capture20"]:
    print(f"  {k:14s} {PREV[k]:.4f} -> {res[k]:.4f}   ({res[k]-PREV[k]:+.4f})")

print("\n" + classification_report(y[te], pred, target_names=names, digits=3))
print(pd.DataFrame(confusion_matrix(y[te], pred), index=names, columns=names))
print(f"\nFatal risk ranking (base {base*100:.2f}%):")
for f in [.01, .05, .1, .2, .3]:
    k = int(len(t) * f)
    print(f"  top {f:>4.0%}: {t[:k].mean()*100:6.2f}%  lift {t[:k].mean()/base:5.2f}x  "
          f"captured {t[:k].sum()/t.sum()*100:5.1f}%")

imp = pd.DataFrame({"feature": X.columns,
                    "gain": model.booster_.feature_importance("gain")}).sort_values("gain", ascending=False)
imp["share_%"] = imp.gain / imp.gain.sum() * 100
print("\ntop 15 features:")
print(imp.head(15).round(2).to_string(index=False))

cmp.to_csv("comparison_2009_2015.csv", index=False)
imp.to_csv("feature_importance_2009_2015.csv", index=False)
json.dump({**res, "multipliers": {"Fatal": float(MF), "Grievous": float(MG)},
           "params": BEST}, open("model_2009_2015_config.json", "w"), indent=2)
print("\nSaved: comparison_2009_2015.csv, feature_importance_2009_2015.csv, model_2009_2015_config.json")
