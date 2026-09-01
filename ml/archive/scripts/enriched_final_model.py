"""
Final model on the STATS19-enriched features.

Combines the three things that were measured to work, in order of size:
  1. STATS19 enrichment        -- AP_Fatal 0.055 -> 0.128, KSI AUC 0.676 -> 0.789
  2. Threshold tuning          -- large macro-F1 gain, and free: average
                                  precision is rank-based, so per-class
                                  multipliers cannot change it
  3. LightGBM + LinearSVC blend -- LightGBM leads on Fatal, the linear model
                                  leads on Grievous; weights are per class

c_did_police_officer_attend_scene_of_accident is EXCLUDED. The leakage audit
showed 100% of the improvement survives without it, and police attendance is
a response to severity rather than a circumstance known at prediction time.

Blend weights and decision multipliers are chosen on out-of-fold training
predictions and frozen before the test set is scored once.
"""
import warnings; warnings.filterwarnings("ignore")
import json
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.svm import LinearSVC
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (f1_score, average_precision_score, roc_auc_score,
                             classification_report, confusion_matrix)
from lightgbm import LGBMClassifier

RS = 42
DATA = "accidents_enriched_explanatory.csv"

print("loading ...")
e = pd.read_csv(DATA, low_memory=False)
e = e[e["v_n_vehicle_rows"].notna()].reset_index(drop=True)   # rows that matched STATS19
sev = e["Accident_Severity"]
le = LabelEncoder().fit(sev)
y = le.transform(sev)
names = le.classes_.tolist()
FI, GI, MI = (names.index(c) for c in ["Fatal", "Grievous", "Minor"])
y_ksi = (sev != "Minor").astype(int).values
print(f"  {len(e):,} rows")

CATS = ["Day_of_Week", "Junction_Control", "Junction_Detail", "Light_Conditions",
        "Local_Authority_(District)", "Police_Force", "Road_Surface_Conditions",
        "Road_Type", "Urban_or_Rural_Area", "Weather_Conditions", "Vehicle_Type"]
e["Hour"] = pd.to_datetime(e["Time"], format="%H:%M", errors="coerce").dt.hour
e["Month"] = pd.to_datetime(e["Accident_Date"], errors="coerce").dt.month
NUM = ["Latitude", "Longitude", "Number_of_Casualties", "Number_of_Vehicles",
       "Speed_limit", "Hour", "Month"]

X = e[CATS + NUM].copy()
for c in CATS:
    X[c] = LabelEncoder().fit_transform(X[c].fillna("Unknown").astype(str))

new_cols = [c for c in e.columns
            if c[:2] in ("v_", "c_", "k_") and "police_officer_attend" not in c]
N = e[new_cols].copy()
for c in N.columns:
    if N[c].dtype == object:
        N[c] = LabelEncoder().fit_transform(N[c].fillna("NA").astype(str))
X = pd.concat([X, N], axis=1).apply(pd.to_numeric, errors="coerce")
X = X.replace([np.inf, -np.inf], np.nan)
print(f"  {X.shape[1]} features")

tr, te = train_test_split(np.arange(len(e)), test_size=0.2, random_state=RS, stratify=y)

# LightGBM takes NaN natively; LinearSVC does not. The second fillna(0) is
# the fix for columns that are entirely NaN within the training split -- their
# median is itself NaN, so a single median fill silently leaves NaNs behind.
med = X.iloc[tr].median()
X_dense = X.fillna(med).fillna(0)
sc = StandardScaler().fit(X_dense.iloc[tr])
Xs = sc.transform(X_dense)

mk_lgb = lambda: LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=63,
                                min_child_samples=40, class_weight="balanced",
                                random_state=RS, n_jobs=-1, verbose=-1)
mk_svc = lambda: CalibratedClassifierCV(
    LinearSVC(C=0.1, class_weight="balanced", max_iter=3000, random_state=RS), cv=3)

# ---------- out-of-fold probabilities ----------
print("\nout-of-fold probabilities (3 folds) ...")
oof_l = np.zeros((len(tr), 3)); oof_s = np.zeros((len(tr), 3))
for k, (a, b) in enumerate(StratifiedKFold(3, shuffle=True, random_state=RS).split(tr, y[tr]), 1):
    ia, ib = tr[a], tr[b]
    oof_l[b] = mk_lgb().fit(X.iloc[ia], y[ia]).predict_proba(X.iloc[ib])
    oof_s[b] = mk_svc().fit(Xs[ia], y[ia]).predict_proba(Xs[ib])
    print(f"  fold {k}/3")
y_tr = y[tr]

# ---------- per-class blend weights (OOF only) ----------
print("\nblend weights (w = weight on LightGBM):")
W = np.ones(3)
for c in range(3):
    t = (y_tr == c).astype(int)
    ap, w = max((average_precision_score(t, w * oof_l[:, c] + (1 - w) * oof_s[:, c]), w)
                for w in np.arange(0, 1.01, 0.05))
    W[c] = w
    print(f"  {names[c]:9s} w={w:.2f}  OOF AP={ap:.4f}")
oof_b = np.column_stack([W[c] * oof_l[:, c] + (1 - W[c]) * oof_s[:, c] for c in range(3)])


def tune(P, yt):
    grid = np.concatenate([np.arange(0.25, 3.01, 0.25), np.arange(3.5, 12.1, 0.5)])
    best = (-1.0, 1.0, 1.0)
    for mf in grid:
        sf = P[:, FI] * mf
        for mg in grid:
            s = f1_score(yt, np.argmax(np.column_stack([sf, P[:, GI] * mg, P[:, MI]]), 1),
                         average="macro")
            if s > best[0]:
                best = (s, mf, mg)
    return best


print("\ndecision multipliers (OOF):")
sb, mfb, mgb = tune(oof_b, y_tr)
sl, mfl, mgl = tune(oof_l, y_tr)
print(f"  blend    Fatal x{mfb:.2f} Grievous x{mgb:.2f}  (OOF macro-F1 {sb:.4f})")
print(f"  LightGBM Fatal x{mfl:.2f} Grievous x{mgl:.2f}  (OOF macro-F1 {sl:.4f})")

# ---------- final fit, single test evaluation ----------
print("\nfinal fit ...")
lgb_final = mk_lgb().fit(X.iloc[tr], y[tr])
svc_final = mk_svc().fit(Xs[tr], y[tr])
P_l = lgb_final.predict_proba(X.iloc[te])
P_s = svc_final.predict_proba(Xs[te])
P_b = np.column_stack([W[c] * P_l[:, c] + (1 - W[c]) * P_s[:, c] for c in range(3)])

ksi_model = mk_lgb().fit(X.iloc[tr], y_ksi[tr])
ksi_auc = roc_auc_score(y_ksi[te], ksi_model.predict_proba(X.iloc[te])[:, 1])

am = lambda P, mf, mg: np.argmax(np.column_stack([P[:, FI] * mf, P[:, GI] * mg, P[:, MI]]), 1)


def rep(tag, P, pred):
    ap = [average_precision_score((y[te] == i).astype(int), P[:, i]) for i in range(3)]
    o = np.argsort(-P[:, FI]); t = (y[te] == FI).astype(int)[o]
    return {"model": tag, "macro_F1": f1_score(y[te], pred, average="macro"),
            "macro_AP": float(np.mean(ap)), "AP_Fatal": ap[0], "AP_Grievous": ap[1],
            "top1pct_rate": t[:int(len(t) * .01)].mean(),
            "capture_at_20pct": t[:int(len(t) * .2)].sum() / t.sum()}


rows = [rep("LightGBM, argmax", P_l, P_l.argmax(1)),
        rep("LightGBM, threshold-tuned", P_l, am(P_l, mfl, mgl)),
        rep("Blend, argmax", P_b, P_b.argmax(1)),
        rep("Blend, threshold-tuned", P_b, am(P_b, mfb, mgb))]
r = pd.DataFrame(rows)
print("\n" + "=" * 104)
print("FINAL -- enriched features, held-out test set")
print("=" * 104)
print(r.round(4).to_string(index=False))
print(f"\nKSI ROC-AUC (enriched): {ksi_auc:.4f}")

best_row = r.loc[r.macro_F1.idxmax()]
best_pred = am(P_b, mfb, mgb) if "Blend" in best_row.model else am(P_l, mfl, mgl)
print(f"\n--- {best_row.model} ---")
print(classification_report(y[te], best_pred, target_names=names, digits=3))
print(pd.DataFrame(confusion_matrix(y[te], best_pred), index=names, columns=names))

o = np.argsort(-P_b[:, FI]); t = (y[te] == FI).astype(int)[o]; base = t.mean()
print(f"\nFatal risk ranking (base rate {base*100:.2f}%):")
for f in [0.01, 0.05, 0.10, 0.20, 0.30]:
    k = int(len(t) * f)
    print(f"  top {f:>4.0%}: {t[:k].mean()*100:6.2f}%   lift {t[:k].mean()/base:5.2f}x   "
          f"captured {t[:k].sum()/t.sum()*100:5.1f}%")

r.to_csv("enriched_final_results.csv", index=False)
json.dump({"blend_weights": dict(zip(names, W.round(3).tolist())),
           "multipliers": {"Fatal": float(mfb), "Grievous": float(mgb), "Minor": 1.0},
           "ksi_roc_auc": float(ksi_auc), "n_features": int(X.shape[1]),
           "n_rows": int(len(e))},
          open("enriched_final_config.json", "w"), indent=2)
print("\nSaved: enriched_final_results.csv, enriched_final_config.json")
