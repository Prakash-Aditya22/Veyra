"""
Did the STATS19 enrichment actually buy information?

The honest test is NOT macro-F1. It is whether the risk-concentration ceiling
moved. Earlier diagnostics measured that the top 1% of sites, ranked by the
best model on the original 20 columns, ran at ~10-13% fatality against a 1.28%
base. If impact point, driver age and pedestrian involvement genuinely add
signal, that number should climb. If it does not, the enrichment failed
regardless of what any F1 score says.

Three feature sets, identical rows, identical model, identical split:
  ORIGINAL     -- the 20 columns the project started with
  ACTIONABLE   -- + collision/vehicle features a highway authority can act on
  EXPLANATORY  -- + casualty demographics (predicts better, not actionable)

Restricted throughout to the 91.5% of rows that matched STATS19, so all three
see exactly the same rows and the comparison is clean.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (average_precision_score, roc_auc_score, f1_score,
                             classification_report)
from lightgbm import LGBMClassifier

RS = 42
print("loading enriched files ...")
expl = pd.read_csv("accidents_enriched_explanatory.csv", low_memory=False)

# only rows that actually matched STATS19, so every feature set sees the same rows
matched = expl["v_n_vehicle_rows"].notna()
expl = expl[matched].reset_index(drop=True)
print(f"  {len(expl):,} matched rows")

sev = expl["Accident_Severity"]
y = LabelEncoder().fit(sev).transform(sev)
names = sorted(sev.unique())
FI = names.index("Fatal")
y_ksi = (sev != "Minor").astype(int).values

ORIG_CATS = ["Day_of_Week", "Junction_Control", "Junction_Detail", "Light_Conditions",
             "Local_Authority_(District)", "Police_Force", "Road_Surface_Conditions",
             "Road_Type", "Urban_or_Rural_Area", "Weather_Conditions", "Vehicle_Type"]
ORIG_NUM = ["Latitude", "Longitude", "Number_of_Casualties", "Number_of_Vehicles", "Speed_limit"]

expl["Hour"] = pd.to_datetime(expl["Time"], format="%H:%M", errors="coerce").dt.hour
expl["Month"] = pd.to_datetime(expl["Accident_Date"], errors="coerce").dt.month
ORIG_NUM += ["Hour", "Month"]

X_orig = expl[ORIG_CATS + ORIG_NUM].copy()
for c in ORIG_CATS:
    X_orig[c] = LabelEncoder().fit_transform(X_orig[c].fillna("Unknown").astype(str))
X_orig = X_orig.apply(pd.to_numeric, errors="coerce")

v_cols = [c for c in expl.columns if c.startswith("v_")]
c_cols = [c for c in expl.columns if c.startswith("c_")]
k_cols = [c for c in expl.columns if c.startswith("k_")]

def numeric(df_):
    d = df_.copy()
    for c in d.columns:
        if d[c].dtype == object:
            d[c] = LabelEncoder().fit_transform(d[c].fillna("NA").astype(str))
    return d.apply(pd.to_numeric, errors="coerce")

SETS = {
    "ORIGINAL   (20 cols)": X_orig,
    "ACTIONABLE (+veh/coll)": pd.concat([X_orig, numeric(expl[c_cols + v_cols])], axis=1),
    "EXPLANATORY (+casualty)": pd.concat([X_orig, numeric(expl[c_cols + v_cols + k_cols])], axis=1),
}

tr, te = train_test_split(np.arange(len(expl)), test_size=0.2, random_state=RS, stratify=y)
rows = []

for tag, X in SETS.items():
    X = X.replace([np.inf, -np.inf], np.nan)
    m = LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=63,
                       min_child_samples=40, class_weight="balanced",
                       random_state=RS, n_jobs=-1, verbose=-1).fit(X.iloc[tr], y[tr])
    P = m.predict_proba(X.iloc[te])

    mk = LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=63,
                        min_child_samples=40, class_weight="balanced",
                        random_state=RS, n_jobs=-1, verbose=-1).fit(X.iloc[tr], y_ksi[tr])
    p_ksi = mk.predict_proba(X.iloc[te])[:, 1]

    ap = [average_precision_score((y[te] == i).astype(int), P[:, i]) for i in range(3)]
    # the ceiling test: fatality rate among the top 1% by predicted fatal risk
    order = np.argsort(-P[:, FI]); truth = (y[te] == FI).astype(int)[order]
    k = int(len(truth) * 0.01)
    top1 = truth[:k].mean()
    top10 = truth[:int(len(truth) * 0.10)].mean()
    cap20 = truth[:int(len(truth) * 0.20)].sum() / truth.sum()

    rows.append({"features": tag, "n_cols": X.shape[1],
                 "macro_AP": float(np.mean(ap)), "AP_Fatal": ap[0], "AP_Griev": ap[1],
                 "KSI_ROC_AUC": roc_auc_score(y_ksi[te], p_ksi),
                 "top1%_fatal_rate": top1, "top1%_lift": top1 / truth.mean(),
                 "top10%_rate": top10, "capture@20%": cap20,
                 "macro_F1": f1_score(y[te], P.argmax(1), average="macro")})
    print(f"  done: {tag}")

r = pd.DataFrame(rows)
print("\n" + "=" * 104)
print("DID ENRICHMENT MOVE THE CEILING?")
print("=" * 104)
print(r.round(4).to_string(index=False))

b = r.iloc[0]
print("\nChange vs ORIGINAL:")
for i in [1, 2]:
    d = r.iloc[i]
    print(f"  {d.features:24s} macroAP {d.macro_AP-b.macro_AP:+.4f}   "
          f"AP_Fatal {d.AP_Fatal-b.AP_Fatal:+.4f}   KSI_AUC {d.KSI_ROC_AUC-b.KSI_ROC_AUC:+.4f}   "
          f"top1% {(d['top1%_fatal_rate']-b['top1%_fatal_rate'])*100:+.2f}pp")

r.to_csv("enrichment_results.csv", index=False)
print("\nSaved: enrichment_results.csv")
