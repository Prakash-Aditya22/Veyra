"""
Does the final model generalise, or is it exploiting where and when?

Three of the top ten features by gain are geographic (longitude, latitude,
local_authority_district). A random split lets crashes from the same location
sit on both sides, which flatters any model carrying location features. And
seven years of data finally makes a real temporal test possible.

  random    -- the usual split; same place and period on both sides
  spatial   -- entire ~11km regions held out, so test locations are UNSEEN
  temporal  -- train 2009-2013, test 2014-2015: predicting the FUTURE

A sharp drop under spatial means the model memorises places rather than
learning what makes crashes severe. A sharp drop under temporal means it
will decay in deployment.

Uses a lighter configuration than the headline model (500 trees x 127 leaves
rather than 1200 x 255) so three splits finish in reasonable time. All three
share it, so the comparison between them is exact; absolute values will sit
slightly below the headline figures.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, GroupShuffleSplit
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import average_precision_score, roc_auc_score, f1_score
from lightgbm import LGBMClassifier

RS = 42
CFG = dict(n_estimators=500, num_leaves=127, learning_rate=0.05,
           colsample_bytree=0.5, reg_alpha=1.0, reg_lambda=1.0,
           min_child_samples=40, max_depth=-1)

print("loading ...")
df = pd.read_csv("stats19_2009_2015.csv", low_memory=False)
le = LabelEncoder().fit(df["Accident_Severity"])
y = le.transform(df["Accident_Severity"])
names = le.classes_.tolist()
FI = names.index("Fatal")
y_ksi = (df["Accident_Severity"] != "Minor").astype(int).values
year = df["collision_year"].values

DROP = {"Accident_Severity", "collision_index", "collision_year",
        "did_police_officer_attend_scene_of_accident"}
X = df[[c for c in df.columns if c not in DROP]].copy()
for c in X.columns:
    if X[c].dtype == object:
        X[c] = LabelEncoder().fit_transform(X[c].fillna("NA").astype(str))
X = X.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).astype(np.float32)
print(f"  {len(df):,} rows x {X.shape[1]} features")

# ~11km cells, so whole regions can be held out together
cell = pd.Series(list(zip(df.latitude.round(1), df.longitude.round(1))))

splits = {}
splits["random"] = train_test_split(np.arange(len(df)), test_size=0.2,
                                    random_state=RS, stratify=y)
gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=RS)
splits["spatial (unseen ~11km regions)"] = next(gss.split(np.arange(len(df)), y, groups=cell.values))
splits["temporal (2009-13 -> 2014-15)"] = (np.where(year <= 2013)[0], np.where(year >= 2014)[0])

rows = []
for tag, (tr, te) in splits.items():
    print(f"\n{tag}: train {len(tr):,} / test {len(te):,}")
    m = LGBMClassifier(class_weight="balanced", random_state=RS, n_jobs=-1,
                       verbose=-1, **CFG).fit(X.iloc[tr], y[tr])
    P = m.predict_proba(X.iloc[te])
    mk = LGBMClassifier(class_weight="balanced", random_state=RS, n_jobs=-1,
                        verbose=-1, **CFG).fit(X.iloc[tr], y_ksi[tr])
    pk = mk.predict_proba(X.iloc[te])[:, 1]

    ap = [average_precision_score((y[te] == i).astype(int), P[:, i]) for i in range(3)]
    o = np.argsort(-P[:, FI]); t = (y[te] == FI).astype(int)[o]
    rows.append({"split": tag, "AP_Fatal": ap[FI], "macro_AP": float(np.mean(ap)),
                 "KSI_ROC_AUC": roc_auc_score(y_ksi[te], pk),
                 "macro_F1_argmax": f1_score(y[te], P.argmax(1), average="macro"),
                 "top1pct": t[:int(len(t) * .01)].mean(),
                 "capture20": t[:int(len(t) * .2)].sum() / t.sum(),
                 "base_rate": t.mean()})
    print(f"  AP_Fatal={ap[FI]:.4f}  KSI_AUC={rows[-1]['KSI_ROC_AUC']:.4f}  "
          f"top1%={rows[-1]['top1pct']*100:.2f}%")

r = pd.DataFrame(rows)
print("\n" + "=" * 108)
print("GENERALISATION CHECK")
print("=" * 108)
print(r.round(4).to_string(index=False))

base = r.iloc[0]
print("\nchange vs random split:")
for i in [1, 2]:
    d = r.iloc[i]
    print(f"  {d.split:34s} AP_Fatal {d.AP_Fatal-base.AP_Fatal:+.4f}   "
          f"KSI_AUC {d.KSI_ROC_AUC-base.KSI_ROC_AUC:+.4f}   "
          f"capture20 {(d.capture20-base.capture20)*100:+.1f}pp")

print("\nNote: the temporal split trains on 5 years and tests on 2, so its")
print("training set is smaller than the random split's -- part of any drop is")
print("data volume rather than genuine decay over time.")
r.to_csv("validation_2009_2015.csv", index=False)
print("\nSaved: validation_2009_2015.csv")
