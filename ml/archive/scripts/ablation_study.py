"""
2x2 ablation + validation-strategy study.

Two questions this answers that the cascade run could NOT:

  Q1. The cascade scored 0.4136 vs the flat model's 0.4020. But the cascade
      also had extra features (spatial target encoding + derived flags), so
      that +0.0116 could come from the FRAMING, the FEATURES, or both.
      -> 2x2: {flat, cascade} x {original features, enriched features}

  Q2. A random split lets crashes from the same ~1km location land in both
      train and test. That is legitimate for "predict severity at a known
      site" but NOT for "predict severity at a NEW site". A permutation test
      cannot detect this -- only a grouped split can.
      -> re-run the best config under RANDOM / SPATIAL / TEMPORAL splits

Everything uses one model family (LightGBM) and plain argmax -- no threshold
tuning, no model selection. The point is to isolate framing and features, so
every other knob is held fixed.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from sklearn.model_selection import train_test_split, StratifiedKFold, GroupShuffleSplit
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import f1_score, accuracy_score, recall_score, precision_score, roc_auc_score
from lightgbm import LGBMClassifier

RS = 42
SMOOTH_M = 20.0

df = pd.read_csv("Road_Accident_Data_Cleaned.csv", low_memory=False)
df["Hour"] = pd.to_datetime(df["Time"], format="%H:%M", errors="coerce").dt.hour
df["Month"] = pd.to_datetime(df["Accident_Date"], errors="coerce").dt.month
df["_year"] = pd.to_datetime(df["Accident_Date"], errors="coerce").dt.year

CATS = ["Day_of_Week", "Junction_Control", "Junction_Detail", "Light_Conditions",
        "Local_Authority_(District)", "Carriageway_Hazards", "Police_Force",
        "Road_Surface_Conditions", "Road_Type", "Urban_or_Rural_Area",
        "Weather_Conditions", "Vehicle_Type"]

# ---- ORIGINAL feature set (what the flat 0.4020 baseline used) ----
ORIGINAL = CATS + ["Latitude", "Longitude", "Number_of_Casualties", "Number_of_Vehicles",
                   "Speed_limit", "Hour", "Month"]

# ---- DERIVED extras ----
df["Is_Single_Vehicle"] = (df["Number_of_Vehicles"] == 1).astype(int)
df["Is_Night"] = df["Light_Conditions"].astype(str).str.startswith("Darkness").astype(int)
df["Is_Weekend"] = df["Day_of_Week"].astype(str).str.strip().isin(["Saturday", "Sunday"]).astype(int)
df["Casualties_Per_Vehicle"] = df["Number_of_Casualties"] / df["Number_of_Vehicles"].replace(0, np.nan)
df["Hour_sin"] = np.sin(2 * np.pi * df["Hour"] / 24)
df["Hour_cos"] = np.cos(2 * np.pi * df["Hour"] / 24)
DERIVED = ["Is_Single_Vehicle", "Is_Night", "Is_Weekend", "Casualties_Per_Vehicle",
           "Hour_sin", "Hour_cos"]

sev = df["Accident_Severity"]
le3 = LabelEncoder().fit(sev)
y3 = le3.transform(sev)
names = le3.classes_.tolist()
FI, GI, MI = (names.index(c) for c in ["Fatal", "Grievous", "Minor"])
y_ksi = (sev != "Minor").astype(int).values
y_fat = (sev == "Fatal").astype(int).values

# encode categoricals once (vocabulary only, not a statistic)
X_all = df.copy()
for c in CATS:
    X_all[c] = LabelEncoder().fit_transform(X_all[c].fillna("Unknown").astype(str))

cell_fine = pd.Series(list(zip(df.Latitude.round(2), df.Longitude.round(2))))    # ~1.1km, for encoding
cell_coarse = pd.Series(list(zip(df.Latitude.round(1), df.Longitude.round(1))))  # ~11km, for grouping


def build_spatial_encoding(tr, te, target_vec, name):
    """Train-only, OOF-within-train smoothed target encoding (verified clean
    by permutation test: AUC 0.4988 on a shuffled target)."""
    vals = np.full(len(df), np.nan)

    def rates(rows):
        t = pd.DataFrame({"c": cell_fine.iloc[rows].values, "y": target_vec[rows]})
        a = t.groupby("c")["y"].agg(["size", "mean"])
        p = float(target_vec[rows].mean())
        return (a["mean"] * a["size"] + p * SMOOTH_M) / (a["size"] + SMOOTH_M), p

    m, p = rates(tr)
    vals[te] = cell_fine.iloc[te].map(m).fillna(p).values
    skf = StratifiedKFold(5, shuffle=True, random_state=RS)
    for ei, hi in skf.split(tr, target_vec[tr]):
        fm, fp = rates(tr[ei])
        vals[tr[hi]] = cell_fine.iloc[tr[hi]].map(fm).fillna(fp).values
    return pd.Series(vals, name=name)


def lgb():
    return LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=63,
                          min_child_samples=40, class_weight="balanced",
                          random_state=RS, n_jobs=-1, verbose=-1)


def evaluate(y_true, y_pred, tag, extra=None):
    row = {"config": tag,
           "accuracy": accuracy_score(y_true, y_pred),
           "macro_f1": f1_score(y_true, y_pred, average="macro")}
    r = recall_score(y_true, y_pred, average=None, labels=range(3), zero_division=0)
    p = precision_score(y_true, y_pred, average=None, labels=range(3), zero_division=0)
    for i, n in enumerate(names):
        row[f"{n}_recall"] = r[i]
        row[f"{n}_prec"] = p[i]
    if extra:
        row.update(extra)
    return row


def run_config(framing, feats_kind, tr, te, tag):
    """framing: 'flat'|'cascade'   feats_kind: 'original'|'enriched'"""
    cols = list(ORIGINAL)
    X = X_all.copy()

    if feats_kind == "enriched":
        cols += DERIVED
        for tv, nm in [(y_ksi, "Cell_KSI_Rate"), (y_fat, "Cell_Fatal_Rate")]:
            X[nm] = build_spatial_encoding(tr, te, tv, nm).values
            cols.append(nm)

    X = X[cols].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.iloc[tr].median())

    if framing == "flat":
        m = lgb().fit(X.iloc[tr], y3[tr])
        pred = m.predict(X.iloc[te])
        return evaluate(y3[te], pred, tag)

    # cascade: stage1 KSI vs Minor, stage2 Fatal vs Grievous | KSI
    m1 = lgb().fit(X.iloc[tr], y_ksi[tr])
    p1 = m1.predict_proba(X.iloc[te])[:, 1]
    ksi_tr = tr[y_ksi[tr] == 1]
    m2 = lgb().fit(X.iloc[ksi_tr], y_fat[ksi_tr])
    p2 = m2.predict_proba(X.iloc[te])[:, 1]

    # recompose to 3-class probabilities, then plain argmax (same rule the
    # flat model gets -- no threshold tuning on either side)
    proba = np.zeros((len(te), 3))
    proba[:, MI] = 1 - p1
    proba[:, GI] = p1 * (1 - p2)
    proba[:, FI] = p1 * p2
    pred = proba.argmax(axis=1)

    ksi_te = y_ksi[te] == 1
    extra = {"stage1_auc": roc_auc_score(y_ksi[te], p1),
             "stage2_auc": roc_auc_score(y_fat[te][ksi_te], p2[ksi_te]) if ksi_te.sum() else np.nan}
    return evaluate(y3[te], pred, tag, extra)


# ============================================================
# PART 1 -- 2x2 ablation on the standard random split
# ============================================================
tr_r, te_r = train_test_split(np.arange(len(df)), test_size=0.2, random_state=RS, stratify=y3)

rows = []
print("=" * 78)
print("PART 1 -- 2x2 ABLATION (random split, LightGBM, argmax, no threshold tuning)")
print("=" * 78)
for feats in ["original", "enriched"]:
    for framing in ["flat", "cascade"]:
        tag = f"{framing:7s} | {feats}"
        print(f"  running {tag} ...")
        rows.append(run_config(framing, feats, tr_r, te_r, tag))

abl = pd.DataFrame(rows).set_index("config")
print("\n" + abl[["accuracy", "macro_f1", "Fatal_recall", "Fatal_prec",
                   "Grievous_recall", "Minor_recall"]].round(4).to_string())

base = abl.loc["flat    | original", "macro_f1"]
print("\nAttribution of the macro-F1 change (vs flat|original):")
for cfg in abl.index:
    print(f"  {cfg:22s} {abl.loc[cfg,'macro_f1']:.4f}   delta = {abl.loc[cfg,'macro_f1']-base:+.4f}")

# ============================================================
# PART 2 -- does it generalise to UNSEEN PLACES and FUTURE TIME?
#   random  : same ~1km location can appear in train AND test
#   spatial : entire ~11km regions held out -> tests new locations
#   temporal: train 2009, test 2010        -> tests future crashes
# ============================================================
print("\n" + "=" * 78)
print("PART 2 -- VALIDATION STRATEGY (cascade + enriched features)")
print("=" * 78)

splits = {"random": (tr_r, te_r)}

gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=RS)
tr_s, te_s = next(gss.split(np.arange(len(df)), y3, groups=cell_coarse.values))
splits["spatial (unseen ~11km regions)"] = (tr_s, te_s)

yr = df["_year"].values
tr_t, te_t = np.where(yr == 2009)[0], np.where(yr == 2010)[0]
if len(tr_t) and len(te_t):
    splits["temporal (train 2009 -> test 2010)"] = (tr_t, te_t)

rows2 = []
for label, (a, b) in splits.items():
    print(f"  running {label} ... (train={len(a)}, test={len(b)})")
    rows2.append(run_config("cascade", "enriched", a, b, label))

val = pd.DataFrame(rows2).set_index("config")
print("\n" + val[["accuracy", "macro_f1", "stage1_auc", "stage2_auc",
                   "Fatal_recall", "Minor_recall"]].round(4).to_string())

print("\nIf macro-F1/stage1_auc drop sharply under the SPATIAL split, the model")
print("leans on knowing specific locations and transfers poorly to new places.")
print("If it holds up, the spatial signal is genuinely generalisable.")

abl.to_csv("ablation_2x2.csv")
val.to_csv("ablation_validation_strategy.csv")
print("\nSaved: ablation_2x2.csv, ablation_validation_strategy.csv")
