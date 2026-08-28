"""
Hierarchical (cascade) severity prediction on Road_Accident_Data_Cleaned.csv.

Instead of one flat 3-class model (Fatal / Grievous / Minor), this splits the
problem the way the severity scale is actually structured -- as two binary
questions:

    Stage 1:  Is this accident SERIOUS (KSI) or MINOR?
              KSI = Killed or Seriously Injured = Fatal + Grievous.
              Positive class = 14.51% of rows (vs 1.28% for Fatal alone).

    Stage 2:  GIVEN it is serious, is it FATAL or GRIEVOUS?
              Trained only on KSI rows. Positive (Fatal) = 8.85% of those.

Why this beats the flat 3-class formulation here:

  * The flat model has to isolate a 1.28% class. Diagnostics on this dataset
    showed the single highest-risk identifiable segment (70mph rural dual
    carriageway, unlit darkness) is only ~5.05% fatal -- so Fatal precision
    is bounded around 5-8% NO MATTER WHAT MODEL IS USED. That ceiling is a
    property of the feature set, not of the algorithm. Splitting the problem
    means neither stage ever has to fight a 1.28% base rate.
  * KSI is the metric UK road safety policy is actually written around
    (DfT reports KSI), so stage 1 is directly meaningful on its own.
  * Each stage is binary -> ROC-AUC / PR-AUC are available, which measure
    whether the model RANKS risk correctly. For blackspot work (ranking
    locations to prioritise intervention) ranking quality is the thing that
    matters, not argmax accuracy.
  * "What makes a crash serious" and "what makes a serious crash fatal" are
    genuinely different questions -- per-stage SHAP answers them separately,
    which a flat model cannot.

The two stages are recomposed into 3-class probabilities so results stay
directly comparable to the flat baseline:
    P(Minor)    = 1 - P(KSI)
    P(Grievous) = P(KSI) * (1 - P(Fatal|KSI))
    P(Fatal)    = P(KSI) * P(Fatal|KSI)

Leakage protections carried over from severity_prediction.py: identical
train/test split (same seed), District_Freq and numeric medians computed
train-only, and the new spatial target encoding computed train-only with
out-of-fold encoding for the training rows themselves.
"""

import warnings
warnings.filterwarnings("ignore")

import gc
import json
import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import shap
import joblib

from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (
    classification_report, accuracy_score, confusion_matrix, f1_score,
    recall_score, precision_score, roc_auc_score, average_precision_score,
)
from sklearn.ensemble import HistGradientBoostingClassifier
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier, Pool

RANDOM_STATE = 42
TARGET = "Accident_Severity"
DATA_PATH = "Road_Accident_Data_Cleaned.csv"
OUT_DIR = "./Severity_Cascade_UK"
MODELS_DIR = os.path.join(OUT_DIR, "models")
SHAP_DIR = os.path.join(OUT_DIR, "SubcategorySHAP")

# Unlike severity_prediction.py's DRY_RUN (which only shrank search
# iterations and so still took hours), this one also SUBSAMPLES the training
# data, so a smoke test genuinely finishes in a couple of minutes.
DRY_RUN = False
DRY_RUN_ROWS = 25_000

# Spatial target encoding: ~1.1km grid cells (lat/long rounded to 2dp).
#
# DEFAULT OFF -- the 2x2 ablation (ablation_study.py) measured what this is
# actually worth, and the answer is: almost nothing.
#
#     flat    | original features   macro-F1 0.3659
#     cascade | original features   macro-F1 0.4010   (+0.0351  <- the framing)
#     flat    | enriched features   macro-F1 0.3705   (+0.0046)
#     cascade | enriched features   macro-F1 0.4015   (+0.0005 on top of cascade)
#
# In isolation this feature looked promising (single-feature AUC 0.643 for
# Fatal on a held-out half), and it is provably leak-free -- a permutation
# test on a shuffled target scored 0.4988, i.e. chance, while a deliberately
# naive implementation scored 0.7794. But leak-free is not the same as
# useful: the geographic signal turns out to be almost entirely redundant
# with speed limit, light conditions, road type and urban/rural, which the
# model already has. Kept behind a flag because the negative result is worth
# preserving, not because it should be on.
USE_SPATIAL_TARGET_ENCODING = False
SPATIAL_DECIMALS = 2        # 2 -> ~1.1km cells (best measured resolution)
SMOOTHING_M = 20.0          # prior weight; higher = more shrinkage toward base rate

# Flat 3-class baseline from severity_prediction.py, for direct comparison.
FLAT_BASELINE_MACRO_F1 = 0.4020   # tuned LightGBM, held-out test set

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(SHAP_DIR, exist_ok=True)

# ============================================================
# 1. LOAD + FEATURE ENGINEERING (deterministic per-row transforms only)
# ============================================================
df = pd.read_csv(DATA_PATH, low_memory=False)

df["Hour"] = pd.to_datetime(df["Time"], format="%H:%M", errors="coerce").dt.hour
df["Month"] = pd.to_datetime(df["Accident_Date"], errors="coerce").dt.month
df["Hour_sin"] = np.sin(2 * np.pi * df["Hour"] / 24)
df["Hour_cos"] = np.cos(2 * np.pi * df["Hour"] / 24)
df["Month_sin"] = np.sin(2 * np.pi * df["Month"] / 12)
df["Month_cos"] = np.cos(2 * np.pi * df["Month"] / 12)

# Cheap derived features. Number_of_Vehicles on its own carries almost no
# signal here (Fatal mean 1.76 vs Minor 1.85 -- slightly inverted), but the
# single-vehicle case is a distinct failure mode (loss of control) with a
# different severity profile, so the flag may extract what the raw count
# cannot.
df["Is_Single_Vehicle"] = (df["Number_of_Vehicles"] == 1).astype(int)
df["Is_Weekend"] = df["Day_of_Week"].astype(str).str.strip().isin(["Saturday", "Sunday"]).astype(int)
df["Is_Night"] = df["Light_Conditions"].astype(str).str.startswith("Darkness").astype(int)
df["Casualties_Per_Vehicle"] = df["Number_of_Casualties"] / df["Number_of_Vehicles"].replace(0, np.nan)

DROP_COLS = ["accident_id", "Original_Accident_Index", "Accident_Date", "Time"]
FEATURE_COLS = [c for c in df.columns if c not in DROP_COLS + [TARGET]]
X_raw = df[FEATURE_COLS].copy()
y_sev = df[TARGET].copy()

CATEGORICAL_COLS = [
    "Day_of_Week", "Junction_Control", "Junction_Detail", "Light_Conditions",
    "Local_Authority_(District)", "Carriageway_Hazards", "Police_Force",
    "Road_Surface_Conditions", "Road_Type", "Urban_or_Rural_Area",
    "Weather_Conditions", "Vehicle_Type",
]
X_raw[CATEGORICAL_COLS] = X_raw[CATEGORICAL_COLS].fillna("Unknown").astype(str)

# ============================================================
# 2. TARGETS + SPLIT (same seed/stratification as severity_prediction.py,
#    so the held-out test set is the identical set of rows -> results are
#    directly comparable to the flat baseline)
# ============================================================
le_target = LabelEncoder()
y_enc = le_target.fit_transform(y_sev)
class_names = le_target.classes_.tolist()      # ['Fatal', 'Grievous', 'Minor']
FATAL_I, GRIEVOUS_I, MINOR_I = (class_names.index(c) for c in ["Fatal", "Grievous", "Minor"])

y_ksi = (y_sev != "Minor").astype(int).values        # stage 1 target
y_fatal = (y_sev == "Fatal").astype(int).values      # stage 2 target (only meaningful where KSI==1)

print("Class distribution:")
print(y_sev.value_counts())
print(f"\nStage 1 (KSI vs Minor):     positive = {y_ksi.mean()*100:.2f}%")
_ksi_mask_all = y_ksi == 1
print(f"Stage 2 (Fatal | KSI):      positive = {y_fatal[_ksi_mask_all].mean()*100:.2f}% "
      f"of {_ksi_mask_all.sum()} serious accidents")

train_idx, test_idx = train_test_split(
    np.arange(len(df)), test_size=0.2, random_state=RANDOM_STATE, stratify=y_enc
)

if DRY_RUN:
    rng = np.random.RandomState(RANDOM_STATE)
    train_idx = rng.choice(train_idx, size=min(DRY_RUN_ROWS, len(train_idx)), replace=False)
    test_idx = rng.choice(test_idx, size=min(DRY_RUN_ROWS // 4, len(test_idx)), replace=False)
    print(f"\n[DRY_RUN] subsampled to {len(train_idx)} train / {len(test_idx)} test rows")

# ============================================================
# 3. TRAIN-ONLY STATISTICS: District_Freq + numeric median imputation
# ============================================================
district_freq = X_raw.loc[train_idx, "Local_Authority_(District)"].value_counts(normalize=True)
X_raw["District_Freq"] = X_raw["Local_Authority_(District)"].map(district_freq)
X_raw["District_Freq"] = X_raw["District_Freq"].fillna(district_freq.min())

NUMERIC_COLS = [c for c in X_raw.columns if c not in CATEGORICAL_COLS]
X_raw[NUMERIC_COLS] = X_raw[NUMERIC_COLS].apply(pd.to_numeric, errors="coerce")
train_medians = X_raw.loc[train_idx, NUMERIC_COLS].median()
X_raw[NUMERIC_COLS] = X_raw[NUMERIC_COLS].fillna(train_medians)

# ============================================================
# 4. SPATIAL TARGET ENCODING (train-only, out-of-fold for train rows)
#
#    Straight target encoding leaks: a training row contributes to the very
#    cell-average used as its own feature, so the model can memorise it.
#    Standard fix, applied here:
#      - TEST rows      -> encoded from ALL training rows
#      - TRAINING rows  -> encoded out-of-fold (each fold encoded using the
#                          other folds only), so no row informs its own value
#    Both are smoothed toward the global base rate so that cells with a
#    handful of accidents don't produce wild estimates.
# ============================================================
SPATIAL_COLS = []
if USE_SPATIAL_TARGET_ENCODING:
    cell_key = list(zip(X_raw["Latitude"].round(SPATIAL_DECIMALS),
                        X_raw["Longitude"].round(SPATIAL_DECIMALS)))
    X_raw["_cell"] = pd.Series(cell_key, index=X_raw.index)

    def smoothed_rates(rows_idx, target_vec):
        """cell -> smoothed positive rate, computed from `rows_idx` only."""
        tmp = pd.DataFrame({"cell": X_raw.loc[rows_idx, "_cell"].values,
                            "y": target_vec[rows_idx]})
        agg = tmp.groupby("cell")["y"].agg(["size", "mean"])
        prior = float(target_vec[rows_idx].mean())
        smoothed = (agg["mean"] * agg["size"] + prior * SMOOTHING_M) / (agg["size"] + SMOOTHING_M)
        return smoothed, prior

    for feat_name, target_vec in [("Cell_KSI_Rate", y_ksi), ("Cell_Fatal_Rate", y_fatal)]:
        values = np.full(len(X_raw), np.nan)

        # Test rows: encode from the full training split.
        full_map, prior = smoothed_rates(train_idx, target_vec)
        values[test_idx] = X_raw.loc[test_idx, "_cell"].map(full_map).fillna(prior).values

        # Training rows: out-of-fold encoding.
        skf_te = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
        for enc_idx, held_idx in skf_te.split(train_idx, target_vec[train_idx]):
            enc_rows, held_rows = train_idx[enc_idx], train_idx[held_idx]
            fold_map, fold_prior = smoothed_rates(enc_rows, target_vec)
            values[held_rows] = X_raw.loc[held_rows, "_cell"].map(fold_map).fillna(fold_prior).values

        X_raw[feat_name] = values
        SPATIAL_COLS.append(feat_name)

    X_raw.drop(columns=["_cell"], inplace=True)
    NUMERIC_COLS = NUMERIC_COLS + SPATIAL_COLS
    print(f"\nAdded spatial target-encoding features: {SPATIAL_COLS} "
          f"(~{10 ** (2 - SPATIAL_DECIMALS) * 1.1:.1f}km cells)")

# ============================================================
# 5. LABEL-ENCODED FEATURE SET
# ============================================================
X_enc = X_raw.copy()
encoders = {}
for col in CATEGORICAL_COLS:
    le = LabelEncoder()
    X_enc[col] = le.fit_transform(X_enc[col])
    encoders[col] = le

cat_feature_indices = [X_enc.columns.get_loc(c) for c in CATEGORICAL_COLS]
# HistGB: sklearn caps categorical cardinality at max_bins (255); District has
# 422 levels, so it is excluded from the categorical mask and treated as an
# ordinary ordinal column -- exactly how XGBoost/LightGBM already treat it.
_district_idx = X_enc.columns.get_loc("Local_Authority_(District)")
histgb_cat_indices = [i for i in cat_feature_indices if i != _district_idx]

X_train = X_enc.iloc[train_idx].reset_index(drop=True)
X_test = X_enc.iloc[test_idx].reset_index(drop=True)
X_train_cat = X_raw.iloc[train_idx].reset_index(drop=True)
X_test_cat = X_raw.iloc[test_idx].reset_index(drop=True)

y_ksi_train, y_ksi_test = y_ksi[train_idx], y_ksi[test_idx]
y_fatal_train, y_fatal_test = y_fatal[train_idx], y_fatal[test_idx]
y_sev_train, y_sev_test = y_enc[train_idx], y_enc[test_idx]

# ============================================================
# 6. BINARY MODEL FACTORY
#    scale_pos_weight / class_weight instead of oversampling: for binary
#    targets this is equivalent in effect but avoids materialising a
#    duplicated training matrix, so it trains far faster and uses less RAM.
# ============================================================
N_EST = 100 if DRY_RUN else 400


def make_binary_models(pos_weight):
    return {
        "LightGBM": LGBMClassifier(
            n_estimators=N_EST, learning_rate=0.05, num_leaves=63,
            subsample=0.8, colsample_bytree=0.8, min_child_samples=40,
            reg_alpha=0.1, reg_lambda=1.0, scale_pos_weight=pos_weight,
            random_state=RANDOM_STATE, n_jobs=-1, verbose=-1),
        "XGBoost": XGBClassifier(
            n_estimators=N_EST, max_depth=8, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
            reg_alpha=0.1, reg_lambda=1.0, scale_pos_weight=pos_weight,
            eval_metric="logloss", random_state=RANDOM_STATE, n_jobs=-1),
        "HistGB": HistGradientBoostingClassifier(
            max_iter=N_EST, max_depth=8, learning_rate=0.05,
            l2_regularization=1.0, categorical_features=histgb_cat_indices,
            class_weight="balanced", random_state=RANDOM_STATE),
        "CatBoost": CatBoostClassifier(
            iterations=N_EST, depth=8, learning_rate=0.05, l2_leaf_reg=3,
            scale_pos_weight=pos_weight, random_state=RANDOM_STATE, verbose=0),
    }


def fit_binary(name, model, X_lab, X_cat, y):
    if name == "CatBoost":
        model.fit(X_cat, y, cat_features=cat_feature_indices)
    else:
        model.fit(X_lab, y)
    return model


def predict_proba_binary(name, model, X_lab, X_cat):
    X = X_cat if name == "CatBoost" else X_lab
    return model.predict_proba(X)[:, 1]


# ============================================================
# 7. OUT-OF-FOLD PROBABILITIES FOR BOTH STAGES
#    One shared fold structure. For fold k:
#      stage 1 trains on train-minus-k
#      stage 2 trains on (train-minus-k AND KSI only)
#      both predict on fold k
#    A held-out row's own label never enters either model's training data,
#    so these OOF probabilities are safe to tune thresholds on -- the real
#    test set is never touched until the final evaluation.
# ============================================================
N_FOLDS = 3 if DRY_RUN else 5
skf = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=RANDOM_STATE)

model_names = ["LightGBM", "XGBoost", "HistGB", "CatBoost"]
oof_ksi = {m: np.zeros(len(train_idx)) for m in model_names}
oof_fatal = {m: np.zeros(len(train_idx)) for m in model_names}

print("\n" + "=" * 62)
print("GENERATING OUT-OF-FOLD PROBABILITIES (both stages)")
print("=" * 62)

for fold, (tr, va) in enumerate(skf.split(X_train, y_sev_train), 1):
    print(f"  fold {fold}/{N_FOLDS} ...")
    X_tr_lab, X_va_lab = X_train.iloc[tr], X_train.iloc[va]
    X_tr_cat, X_va_cat = X_train_cat.iloc[tr], X_train_cat.iloc[va]

    # ---- stage 1: KSI vs Minor ----
    y_tr_ksi = y_ksi_train[tr]
    w1 = (y_tr_ksi == 0).sum() / max((y_tr_ksi == 1).sum(), 1)
    for name, model in make_binary_models(w1).items():
        fit_binary(name, model, X_tr_lab, X_tr_cat, y_tr_ksi)
        oof_ksi[name][va] = predict_proba_binary(name, model, X_va_lab, X_va_cat)
        del model
    gc.collect()

    # ---- stage 2: Fatal vs Grievous, trained on KSI rows only ----
    ksi_rows = tr[y_ksi_train[tr] == 1]
    y_tr_fatal = y_fatal_train[ksi_rows]
    w2 = (y_tr_fatal == 0).sum() / max((y_tr_fatal == 1).sum(), 1)
    X_tr2_lab, X_tr2_cat = X_train.iloc[ksi_rows], X_train_cat.iloc[ksi_rows]
    for name, model in make_binary_models(w2).items():
        fit_binary(name, model, X_tr2_lab, X_tr2_cat, y_tr_fatal)
        # Applied to ALL validation rows (not just KSI ones): the composition
        # step needs P(Fatal|KSI) for every row, and it gets multiplied by
        # P(KSI), so non-serious rows are down-weighted automatically.
        oof_fatal[name][va] = predict_proba_binary(name, model, X_va_lab, X_va_cat)
        del model
    gc.collect()

# ============================================================
# 8. PER-STAGE MODEL SELECTION (by OOF ranking quality, train-side only)
#    ROC-AUC / PR-AUC rather than F1: these measure whether the model orders
#    risk correctly, independent of any threshold -- which is the property
#    that matters for ranking locations, and the property a threshold is
#    then chosen on top of.
# ============================================================
print("\n===== Stage 1 (KSI vs Minor) -- OOF ranking quality =====")
s1_scores = {}
for name in model_names:
    auc = roc_auc_score(y_ksi_train, oof_ksi[name])
    ap = average_precision_score(y_ksi_train, oof_ksi[name])
    s1_scores[name] = auc
    print(f"  {name:12s} ROC-AUC={auc:.4f}   PR-AUC={ap:.4f}  (baseline PR-AUC={y_ksi_train.mean():.4f})")
best_s1 = max(s1_scores, key=s1_scores.get)
print(f"  -> stage 1 model: {best_s1}")

print("\n===== Stage 2 (Fatal | KSI) -- OOF ranking quality, KSI rows only =====")
_ksi_tr_mask = y_ksi_train == 1
s2_scores = {}
for name in model_names:
    auc = roc_auc_score(y_fatal_train[_ksi_tr_mask], oof_fatal[name][_ksi_tr_mask])
    ap = average_precision_score(y_fatal_train[_ksi_tr_mask], oof_fatal[name][_ksi_tr_mask])
    s2_scores[name] = auc
    print(f"  {name:12s} ROC-AUC={auc:.4f}   PR-AUC={ap:.4f}  "
          f"(baseline PR-AUC={y_fatal_train[_ksi_tr_mask].mean():.4f})")
best_s2 = max(s2_scores, key=s2_scores.get)
print(f"  -> stage 2 model: {best_s2}")

# ============================================================
# 9. JOINT THRESHOLD TUNING ON OOF PROBABILITIES
#    Two thresholds (t1 on P(KSI), t2 on P(Fatal|KSI)) searched jointly to
#    maximise composed 3-class macro-F1. Tuned purely on OOF training-side
#    probabilities, then FROZEN -- the test set plays no part in choosing
#    them. Grid search rather than a continuous optimiser because macro-F1
#    under thresholding is a step function with flat regions.
# ============================================================
p1_oof, p2_oof = oof_ksi[best_s1], oof_fatal[best_s2]


def compose_predictions(p_ksi, p_fatal, t1, t2):
    """Minor if not serious; else Fatal/Grievous by the stage-2 threshold."""
    pred = np.full(len(p_ksi), MINOR_I, dtype=int)
    serious = p_ksi >= t1
    pred[serious] = np.where(p_fatal[serious] >= t2, FATAL_I, GRIEVOUS_I)
    return pred


grid = np.arange(0.05, 0.96, 0.025)
best = {"macro_f1": -1.0, "t1": 0.5, "t2": 0.5}
for t1 in grid:
    serious = p1_oof >= t1
    if not serious.any():
        continue
    for t2 in grid:
        pred = np.full(len(p1_oof), MINOR_I, dtype=int)
        pred[serious] = np.where(p2_oof[serious] >= t2, FATAL_I, GRIEVOUS_I)
        score = f1_score(y_sev_train, pred, average="macro")
        if score > best["macro_f1"]:
            best = {"macro_f1": score, "t1": float(t1), "t2": float(t2)}

T1, T2 = best["t1"], best["t2"]
print(f"\nFrozen thresholds from OOF search: t1(KSI)={T1:.3f}  t2(Fatal|KSI)={T2:.3f}")
print(f"(OOF macro-F1 {best['macro_f1']:.4f} -- selection signal only, "
      f"not reported as a performance result)")

# ============================================================
# 10. FINAL FIT ON FULL TRAINING SET + SINGLE TEST EVALUATION
# ============================================================
print("\n" + "=" * 62)
print("FINAL FIT + HELD-OUT TEST EVALUATION")
print("=" * 62)

w1_full = (y_ksi_train == 0).sum() / max((y_ksi_train == 1).sum(), 1)
stage1_model = make_binary_models(w1_full)[best_s1]
fit_binary(best_s1, stage1_model, X_train, X_train_cat, y_ksi_train)

ksi_rows_full = np.where(y_ksi_train == 1)[0]
y_fatal_sub = y_fatal_train[ksi_rows_full]
w2_full = (y_fatal_sub == 0).sum() / max((y_fatal_sub == 1).sum(), 1)
stage2_model = make_binary_models(w2_full)[best_s2]
fit_binary(best_s2, stage2_model, X_train.iloc[ksi_rows_full],
           X_train_cat.iloc[ksi_rows_full], y_fatal_sub)

p1_test = predict_proba_binary(best_s1, stage1_model, X_test, X_test_cat)
p2_test = predict_proba_binary(best_s2, stage2_model, X_test, X_test_cat)

# ---- Stage 1 on its own: the KSI model, which is a deliverable in itself ----
s1_auc = roc_auc_score(y_ksi_test, p1_test)
s1_ap = average_precision_score(y_ksi_test, p1_test)
print(f"\n--- Stage 1: KSI vs Minor (held-out test) ---")
print(f"ROC-AUC = {s1_auc:.4f}    PR-AUC = {s1_ap:.4f}   (no-skill PR-AUC = {y_ksi_test.mean():.4f})")
print(classification_report(y_ksi_test, (p1_test >= T1).astype(int),
                            target_names=["Minor", "Serious (KSI)"], digits=3))

# ---- Stage 2 on its own, evaluated only where the truth is actually KSI ----
_ksi_te_mask = y_ksi_test == 1
s2_auc = roc_auc_score(y_fatal_test[_ksi_te_mask], p2_test[_ksi_te_mask])
s2_ap = average_precision_score(y_fatal_test[_ksi_te_mask], p2_test[_ksi_te_mask])
print(f"--- Stage 2: Fatal vs Grievous, among true serious accidents ---")
print(f"ROC-AUC = {s2_auc:.4f}    PR-AUC = {s2_ap:.4f}   "
      f"(no-skill PR-AUC = {y_fatal_test[_ksi_te_mask].mean():.4f})")
print(classification_report(y_fatal_test[_ksi_te_mask],
                            (p2_test[_ksi_te_mask] >= T2).astype(int),
                            target_names=["Grievous", "Fatal"], digits=3))

# ---- Recomposed 3-class, directly comparable to the flat baseline ----
y_pred_3 = compose_predictions(p1_test, p2_test, T1, T2)
macro_f1 = f1_score(y_sev_test, y_pred_3, average="macro")

print("--- Recomposed 3-class (held-out test) ---")
print(classification_report(y_sev_test, y_pred_3, target_names=class_names, digits=3))
print("Confusion matrix (rows=true, cols=pred):")
print(pd.DataFrame(confusion_matrix(y_sev_test, y_pred_3), index=class_names, columns=class_names))

print(f"\n{'='*62}")
print(f"Cascade 3-class macro-F1 : {macro_f1:.4f}")
print(f"Flat baseline macro-F1   : {FLAT_BASELINE_MACRO_F1:.4f}  (tuned LightGBM, severity_prediction.py)")
print(f"Delta                    : {macro_f1 - FLAT_BASELINE_MACRO_F1:+.4f}")
print("=" * 62)
print("Note: macro-F1 is reported for comparability with the flat model, but")
print("for blackspot ranking the stage-1 ROC-AUC/PR-AUC above are the more")
print("meaningful numbers -- they measure risk ordering, not argmax accuracy.")

# ============================================================
# 11. PER-STAGE SUB-CATEGORY SHAP
#     Two separate, genuinely different questions:
#       stage 1 -> what makes an accident SERIOUS?
#       stage 2 -> what makes a serious accident FATAL?
#     Binary models, so SHAP is a single array per stage (no per-class
#     splitting needed), which makes these far easier to read than the
#     3-class version.
#
#     Interpretation caveat: for LightGBM/XGBoost/HistGB the label-encoded
#     category values are ordinary numeric inputs (no native categorical
#     awareness), so read these as "contribution associated with rows at
#     this category level", not as a causal category effect. CatBoost is the
#     one model with genuine native categorical handling.
# ============================================================
print("\n" + "=" * 62)
print("PER-STAGE SUB-CATEGORY SHAP")
print("=" * 62)

SHAP_ROWS = 500 if DRY_RUN else len(X_test)

for stage_name, model_name, model in [("Stage1_KSI", best_s1, stage1_model),
                                       ("Stage2_Fatal_given_KSI", best_s2, stage2_model)]:
    print(f"\n{stage_name} ({model_name}) ...")
    X_lab = X_test.iloc[:SHAP_ROWS].reset_index(drop=True)
    X_cat = X_test_cat.iloc[:SHAP_ROWS].reset_index(drop=True)

    if model_name == "CatBoost":
        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(Pool(X_cat, cat_features=cat_feature_indices), check_additivity=False)
        X_for_names = X_cat
    else:
        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(X_lab, check_additivity=False)
        X_for_names = X_lab

    sv = np.asarray(sv)
    if sv.ndim == 3:                 # (rows, features, classes) -> positive class
        sv = sv[:, :, -1]

    stage_dir = os.path.join(SHAP_DIR, stage_name)
    os.makedirs(stage_dir, exist_ok=True)
    feature_cols = X_for_names.columns.tolist()

    # Global importance for this stage
    pd.DataFrame({
        "Feature": feature_cols,
        "Mean_Abs_SHAP": np.abs(sv).mean(axis=0),
    }).sort_values("Mean_Abs_SHAP", ascending=False).to_csv(
        os.path.join(stage_dir, "global_importance.csv"), index=False)

    fig = plt.figure(figsize=(12, 9))
    shap.summary_plot(sv, X_for_names, max_display=30, show=False)
    plt.title(f"{stage_name} | {model_name}")
    plt.tight_layout()
    plt.savefig(os.path.join(stage_dir, "beeswarm.png"), dpi=150)
    plt.close(fig)

    # Per-level breakdown for every categorical column, every level, no cap.
    summary_rows = []
    for cat_col in CATEGORICAL_COLS:
        col_idx = feature_cols.index(cat_col)
        levels = X_cat[cat_col].astype(str).values
        g = pd.DataFrame({"Level": levels, "SHAP": sv[:, col_idx]}).groupby("Level")["SHAP"]
        grouped = pd.DataFrame({
            "N_rows": g.count(),
            "Mean_SHAP": g.mean(),
            "Std_SHAP": g.std().fillna(0.0),
            "Mean_Abs_SHAP": g.apply(lambda s: s.abs().mean()),
        }).reset_index()
        grouped["Low_Sample"] = grouped["N_rows"] < 30
        grouped = grouped.sort_values("Mean_Abs_SHAP", ascending=False)

        safe_col = cat_col.replace("/", "_").replace("(", "").replace(")", "")
        grouped.to_csv(os.path.join(stage_dir, f"{safe_col}.csv"), index=False)

        g2 = grouped.copy()
        g2.insert(0, "Category", cat_col)
        summary_rows.append(g2)

    pd.concat(summary_rows, ignore_index=True).to_csv(
        os.path.join(stage_dir, "subcategory_shap_summary.csv"), index=False)

    del sv, summary_rows
    gc.collect()

# ============================================================
# 12. PERSIST ARTIFACTS
# ============================================================
for stage_name, name, model in [("stage1_ksi", best_s1, stage1_model),
                                 ("stage2_fatal", best_s2, stage2_model)]:
    if isinstance(model, CatBoostClassifier):
        model.save_model(os.path.join(MODELS_DIR, f"{stage_name}_{name}.cbm"))
    else:
        joblib.dump(model, os.path.join(MODELS_DIR, f"{stage_name}_{name}.joblib"))

summary = {
    "approach": "hierarchical cascade: KSI vs Minor, then Fatal vs Grievous | KSI",
    "stage1": {"model": best_s1, "threshold": T1, "test_roc_auc": float(s1_auc),
               "test_pr_auc": float(s1_ap), "positive_rate": float(y_ksi_test.mean())},
    "stage2": {"model": best_s2, "threshold": T2, "test_roc_auc": float(s2_auc),
               "test_pr_auc": float(s2_ap),
               "positive_rate": float(y_fatal_test[_ksi_te_mask].mean())},
    "recomposed_3class_macro_f1": float(macro_f1),
    "flat_baseline_macro_f1": FLAT_BASELINE_MACRO_F1,
    "delta_vs_flat": float(macro_f1 - FLAT_BASELINE_MACRO_F1),
    "spatial_target_encoding": USE_SPATIAL_TARGET_ENCODING,
    "spatial_features": SPATIAL_COLS,
    "random_state": RANDOM_STATE,
}
with open(os.path.join(MODELS_DIR, "cascade_summary.json"), "w") as f:
    json.dump(summary, f, indent=2)

with open(os.path.join(MODELS_DIR, "preprocessing_metadata.json"), "w") as f:
    json.dump({
        "class_names": class_names,
        "categorical_columns": CATEGORICAL_COLS,
        "label_encoder_classes": {c: list(e.classes_) for c, e in encoders.items()},
        "district_freq": {str(k): float(v) for k, v in district_freq.items()},
        "train_medians": {c: float(v) for c, v in train_medians.items()},
        "feature_columns": X_enc.columns.tolist(),
        "thresholds": {"t1_ksi": T1, "t2_fatal_given_ksi": T2},
    }, f, indent=2)

pd.DataFrame([
    {"Stage": "Stage 1 (KSI vs Minor)", "Model": best_s1, "ROC_AUC": s1_auc,
     "PR_AUC": s1_ap, "No_Skill_PR_AUC": y_ksi_test.mean(), "Threshold": T1},
    {"Stage": "Stage 2 (Fatal | KSI)", "Model": best_s2, "ROC_AUC": s2_auc,
     "PR_AUC": s2_ap, "No_Skill_PR_AUC": y_fatal_test[_ksi_te_mask].mean(), "Threshold": T2},
]).to_csv(os.path.join(OUT_DIR, "stage_leaderboard.csv"), index=False)

print(f"\nDone. Results, SHAP breakdowns and models are in {OUT_DIR}/")
