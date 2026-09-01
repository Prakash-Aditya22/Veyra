"""
Severity prediction on Road_Accident_Data_Cleaned.csv.

Extends the original 6-model suite (Decision Tree, Logistic Regression,
Random Forest, XGBoost, LightGBM, CatBoost + per-class SHAP) with:

  1. Two more individual models: HistGradientBoostingClassifier and
     BalancedRandomForestClassifier.
  2. Leak-safe Voting and Stacking ensembles over the tuned boosters.
  3. A threshold-tuned variant of the single best (CV-selected) model,
     fit via out-of-fold probabilities -- never the test set.
  4. Full per-level sub-category SHAP for every categorical column
     (all levels, including all 422 districts), on the full test set.
  5. Persisted model artifacts, since this run is too expensive to redo
     casually.

Class imbalance handling (IMBALANCE_MODE), the train/test leakage fixes
(District_Freq and numeric-median imputation computed train-only, CV done
inside imblearn Pipelines), and the core evaluation approach are unchanged
from the original script -- see the section comments below for the specific
reasoning behind each, which still applies.

Install once: pip install imbalanced-learn --break-system-packages
"""

import warnings
warnings.filterwarnings("ignore")

import gc
import json
import os
import random as _random

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import shap
import joblib

from scipy import sparse

from sklearn.model_selection import train_test_split, StratifiedKFold, cross_validate, RandomizedSearchCV
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_sample_weight
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    classification_report, accuracy_score, confusion_matrix,
    f1_score, make_scorer, recall_score, precision_score
)
from sklearn.base import clone
from sklearn.ensemble import (
    RandomForestClassifier, HistGradientBoostingClassifier,
    VotingClassifier, StackingClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier, Pool

from imblearn.over_sampling import RandomOverSampler, SMOTE
from imblearn.ensemble import BalancedRandomForestClassifier
from imblearn.pipeline import Pipeline as ImbPipeline

RANDOM_STATE = 42
TARGET = "Accident_Severity"
DATA_PATH = "Road_Accident_Data_Cleaned.csv"   # adjust path as needed
OUT_DIR = "./Severity_Models_UK"
MODELS_DIR = os.path.join(OUT_DIR, "models")
SHAP_DIR = os.path.join(OUT_DIR, "SubcategorySHAP")

# Set True first to confirm the whole script runs end-to-end (encoders, new
# models, ensembles, threshold tuning, sub-category SHAP) in a few minutes
# before committing to the long real run. Switch back to False and let it
# run in the background once this passes clean.
DRY_RUN = True

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(SHAP_DIR, exist_ok=True)

# ============================================================
# 1. LOAD + FEATURE ENGINEERING (deterministic transforms only -- safe before
#    any split, since these don't compute statistics that could differ between
#    train and test; they're per-row transforms of existing values)
# ============================================================
df = pd.read_csv(DATA_PATH, low_memory=False)

df["Hour"] = pd.to_datetime(df["Time"], format="%H:%M", errors="coerce").dt.hour
df["Month"] = pd.to_datetime(df["Accident_Date"], errors="coerce").dt.month
# NOTE: no .fillna() here on purpose. The 17 rows where Hour is NaN (and the
# NaN that propagates through sin/cos below) are filled later using the
# TRAINING-ONLY median, in the same pass that fixes District_Freq/NUMERIC_COLS
# leakage. Filling here with a full-dataset median would reintroduce exactly
# the leak that step is meant to prevent.

df["Hour_sin"] = np.sin(2 * np.pi * df["Hour"] / 24)
df["Hour_cos"] = np.cos(2 * np.pi * df["Hour"] / 24)
df["Month_sin"] = np.sin(2 * np.pi * df["Month"] / 12)
df["Month_cos"] = np.cos(2 * np.pi * df["Month"] / 12)

DROP_COLS = ["accident_id", "Original_Accident_Index", "Accident_Date", "Time"]
FEATURE_COLS = [c for c in df.columns if c not in DROP_COLS + [TARGET]]
X_raw = df[FEATURE_COLS].copy()
y_raw = df[TARGET].copy()

CATEGORICAL_COLS = [
    "Day_of_Week", "Junction_Control", "Junction_Detail", "Light_Conditions",
    "Local_Authority_(District)", "Carriageway_Hazards", "Police_Force",
    "Road_Surface_Conditions", "Road_Type", "Urban_or_Rural_Area",
    "Weather_Conditions", "Vehicle_Type",
]
X_raw[CATEGORICAL_COLS] = X_raw[CATEGORICAL_COLS].fillna("Unknown").astype(str)

# ============================================================
# 2. ENCODE TARGET + DETERMINE SPLIT INDICES FIRST
# ============================================================
le_target = LabelEncoder()
y_enc = le_target.fit_transform(y_raw)
class_names = le_target.classes_.tolist()
print("Classes:", class_names)
print(y_raw.value_counts())

train_idx, test_idx = train_test_split(
    np.arange(len(df)), test_size=0.2, random_state=RANDOM_STATE, stratify=y_enc
)

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
# 4. LABEL-ENCODED FEATURE SET (tree models)
# ============================================================
X_enc = X_raw.copy()
encoders = {}
for col in CATEGORICAL_COLS:
    le = LabelEncoder()
    X_enc[col] = le.fit_transform(X_enc[col])
    encoders[col] = le

cat_feature_indices = [X_enc.columns.get_loc(c) for c in CATEGORICAL_COLS]  # for CatBoost native handling

# HistGB-specific categorical index list: everything in cat_feature_indices
# EXCEPT Local_Authority_(District). sklearn's HistGradientBoostingClassifier
# hard-caps categorical cardinality at max_bins (255 max; verified against
# the installed sklearn 1.9.0: max_bins defaults to 255) and District has 422
# levels, so marking it categorical raises ValueError outright. HistGB still
# receives the exact same X_enc as every other label-encoded model (required
# so it can sit inside Voting/Stacking below, which need one shared feature
# matrix across all base estimators) -- it just treats that one column as an
# ordinary numeric/ordinal value instead of categorical, no different from
# how XGBoost/LightGBM/RandomForest/DecisionTree already treat that same
# label-encoded column today.
_district_col_idx = X_enc.columns.get_loc("Local_Authority_(District)")
histgb_cat_feature_indices = [i for i in cat_feature_indices if i != _district_col_idx]

# ============================================================
# 5. ONE-HOT FEATURE SET (Logistic Regression fairness + SHAP interpretability)
# ============================================================
OHE_CAT_COLS = [c for c in CATEGORICAL_COLS if c != "Local_Authority_(District)"]
X_ohe_dummies = pd.get_dummies(X_raw[OHE_CAT_COLS], columns=OHE_CAT_COLS, dtype=int, sparse=True)
ohe_feature_names = X_ohe_dummies.columns.tolist() + NUMERIC_COLS
X_ohe = sparse.hstack([
    sparse.csr_matrix(X_ohe_dummies.sparse.to_coo()),
    sparse.csr_matrix(X_raw[NUMERIC_COLS].values),
]).tocsr()

# ============================================================
# 5B. APPLY THE SPLIT
# ============================================================
X_train = X_enc.iloc[train_idx].reset_index(drop=True)
X_test = X_enc.iloc[test_idx].reset_index(drop=True)
y_train = y_enc[train_idx]
y_test = y_enc[test_idx]

X_train_cat = X_raw.iloc[train_idx].reset_index(drop=True)   # raw categorical values, for CatBoost
X_test_cat = X_raw.iloc[test_idx].reset_index(drop=True)

X_train_ohe = X_ohe[train_idx]
X_test_ohe = X_ohe[test_idx]
y_train_ohe = y_enc[train_idx]
y_test_ohe = y_enc[test_idx]

# ============================================================
# 6. IMBALANCE HANDLING (label-encoded + raw-categorical paths)
#    RandomOverSampler everywhere here (not SMOTENC) -- SMOTENC crashes on
#    Local_Authority_(District)'s 422 categories (its internal categorical
#    distance computation tries to allocate 4+ GiB), on both the
#    label-encoded and raw-categorical branches, regardless of dtype.
# ============================================================
ros_main = RandomOverSampler(random_state=RANDOM_STATE)
X_train_bal, y_train_bal = ros_main.fit_resample(X_train, y_train)
X_train_cat_bal, y_train_cat_bal = ros_main.fit_resample(X_train_cat, y_train)

print("Post-oversampling training class counts:", pd.Series(y_train_bal).value_counts().to_dict())

# ============================================================
# 6B. OHE-PATH RESAMPLER COMPARISON: RandomOverSampler vs SMOTE
#    X_train_ohe is fully numeric (District via District_Freq, not raw ID),
#    so plain SMOTE (not SMOTENC) runs without the categorical-cardinality
#    crash above -- but SMOTE interpolation on one-hot dummy columns produces
#    fractional values (e.g. Weather_Rain = 0.4), a known, commonly-used
#    simplification, not a hard error. Compared via 3-fold CV (not a single
#    slice, which is noisy enough that ROS vs SMOTE could look reversed on a
#    different split) using Logistic Regression, the one model that actually
#    trains on this representation. This conclusion is scoped to that
#    pathway only, not a general "SMOTE is better for this dataset" claim.
# ============================================================
IMBALANCE_MODE = "oversample"  # "oversample" or "class_weight" -- read ahead at section 7 too
_use_weight = (IMBALANCE_MODE == "class_weight")

if IMBALANCE_MODE == "oversample":
    print("\nComparing RandomOverSampler vs SMOTE on the OHE path (3-fold CV, Logistic Regression)...")
    _resampler_candidates = {
        "RandomOverSampler": lambda: RandomOverSampler(random_state=RANDOM_STATE),
        "SMOTE": lambda: SMOTE(random_state=RANDOM_STATE),
    }
    _skf_resampler = StratifiedKFold(n_splits=3, shuffle=True, random_state=RANDOM_STATE)
    _resampler_scores = {}
    for _rname, _rbuild in _resampler_candidates.items():
        _fold_f1 = []
        for _tr, _val in _skf_resampler.split(np.zeros(X_train_ohe.shape[0]), y_train_ohe):
            _Xtr, _Xval = X_train_ohe[_tr], X_train_ohe[_val]
            _ytr, _yval = y_train_ohe[_tr], y_train_ohe[_val]
            _Xtr_bal, _ytr_bal = _rbuild().fit_resample(_Xtr, _ytr)
            _lr = LogisticRegression(max_iter=1000, C=1.0, random_state=RANDOM_STATE, n_jobs=-1)
            _lr.fit(_Xtr_bal, _ytr_bal)
            _fold_f1.append(f1_score(_yval, _lr.predict(_Xval), average="macro"))
        _resampler_scores[_rname] = float(np.mean(_fold_f1))
    print("OHE resampler comparison (3-fold CV macro-F1, Logistic Regression):", _resampler_scores)
    OHE_RESAMPLER_NAME = max(_resampler_scores, key=_resampler_scores.get)
    print(f"Selected OHE resampler: {OHE_RESAMPLER_NAME}")
else:
    OHE_RESAMPLER_NAME = "RandomOverSampler"
    _resampler_scores = {}

_ohe_resampler = (SMOTE(random_state=RANDOM_STATE) if OHE_RESAMPLER_NAME == "SMOTE"
                   else RandomOverSampler(random_state=RANDOM_STATE))
X_train_ohe_bal, y_train_ohe_bal = _ohe_resampler.fit_resample(X_train_ohe, y_train_ohe)

# ============================================================
# 7. MODELS
#    IMBALANCE_MODE controls how class imbalance is handled (set above,
#    before section 6B, since the resampler comparison needs to know it too):
#      "oversample"    -> RandomOverSampler/SMOTE only (default)
#      "class_weight"  -> class_weight="balanced" only, no oversampling
# ============================================================

def make_models():
    return {
        "Decision Tree": DecisionTreeClassifier(max_depth=10, min_samples_split=20,
                                                 class_weight="balanced" if _use_weight else None,
                                                 random_state=RANDOM_STATE),
        "Logistic Regression": LogisticRegression(max_iter=1000, C=1.0,
                                                   class_weight="balanced" if _use_weight else None,
                                                   random_state=RANDOM_STATE, n_jobs=-1),
        "Random Forest": RandomForestClassifier(n_estimators=300, min_samples_split=5,
                                                 class_weight="balanced" if _use_weight else None,
                                                 random_state=RANDOM_STATE, n_jobs=-1),
        "XGBoost": XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.1,
                                  subsample=0.8, colsample_bytree=0.8, eval_metric="mlogloss",
                                  random_state=RANDOM_STATE, n_jobs=-1),
        "LightGBM": LGBMClassifier(n_estimators=300, learning_rate=0.1, num_leaves=63,
                                    subsample=0.8, colsample_bytree=0.8,
                                    class_weight="balanced" if _use_weight else None,
                                    random_state=RANDOM_STATE, n_jobs=-1, verbose=-1),
        "CatBoost": CatBoostClassifier(iterations=300, depth=6, learning_rate=0.1,
                                        auto_class_weights="Balanced" if _use_weight else None,
                                        random_state=RANDOM_STATE, verbose=0),
        "HistGB": HistGradientBoostingClassifier(
            max_iter=300, max_depth=6, learning_rate=0.1,
            categorical_features=histgb_cat_feature_indices,
            class_weight="balanced" if _use_weight else None,
            random_state=RANDOM_STATE,
        ),
        "BalancedRandomForest": BalancedRandomForestClassifier(
            n_estimators=300, sampling_strategy="all", replacement=True,
            random_state=RANDOM_STATE, n_jobs=-1,
        ),
    }

models = make_models()
results = {}

print(f"\nTraining (IMBALANCE_MODE='{IMBALANCE_MODE}'), evaluating on the UNTOUCHED real test set...")
for name, model in models.items():
    if IMBALANCE_MODE == "oversample":
        train_cat_X, train_cat_y = X_train_cat_bal, y_train_cat_bal
        train_enc_X, train_enc_y = X_train_bal, y_train_bal
        train_ohe_X, train_ohe_y = X_train_ohe_bal, y_train_ohe_bal
    else:
        train_cat_X, train_cat_y = X_train_cat, y_train
        train_enc_X, train_enc_y = X_train, y_train
        train_ohe_X, train_ohe_y = X_train_ohe, y_train_ohe

    if name == "CatBoost":
        model.fit(train_cat_X, train_cat_y, cat_features=cat_feature_indices)
        y_pred = model.predict(X_test_cat).flatten()
    elif name == "Logistic Regression":
        model.fit(train_ohe_X, train_ohe_y)
        y_pred = model.predict(X_test_ohe)
    elif name == "BalancedRandomForest":
        # Always trained on the ORIGINAL (unbalanced) X_train/y_train,
        # regardless of IMBALANCE_MODE -- its whole mechanism is per-tree
        # internal balancing on raw imbalanced data. Feeding it already
        # globally-oversampled (duplicate-heavy) data would make that
        # internal balancing redundant and collapse bootstrap diversity
        # across trees, making it indistinguishable from plain RandomForest
        # + global oversampling instead of a genuinely different strategy.
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
    elif name == "XGBoost" and IMBALANCE_MODE == "class_weight":
        sw = compute_sample_weight("balanced", train_enc_y)
        model.fit(train_enc_X, train_enc_y, sample_weight=sw)
        y_pred = model.predict(X_test)
    else:
        model.fit(train_enc_X, train_enc_y)
        y_pred = model.predict(X_test)

    per_class_recall = recall_score(y_test, y_pred, average=None, labels=range(len(class_names)))
    per_class_precision = precision_score(y_test, y_pred, average=None, labels=range(len(class_names)), zero_division=0)

    row = {
        "accuracy": accuracy_score(y_test, y_pred),
        "macro_f1": f1_score(y_test, y_pred, average="macro"),
        "weighted_f1": f1_score(y_test, y_pred, average="weighted"),
        "macro_recall": recall_score(y_test, y_pred, average="macro"),
    }
    for i, cls in enumerate(class_names):
        row[f"{cls}_recall"] = per_class_recall[i]
        row[f"{cls}_precision"] = per_class_precision[i]
    results[name] = row

    print(f"\n--- {name} ---")
    print(classification_report(y_test, y_pred, target_names=class_names, digits=3))
    print("Confusion matrix (rows=true, cols=pred):")
    print(pd.DataFrame(confusion_matrix(y_test, y_pred), index=class_names, columns=class_names))

ORIGINAL_SIX = ["Decision Tree", "Logistic Regression", "Random Forest", "XGBoost", "LightGBM", "CatBoost"]

# ============================================================
# 8. LEADERBOARD -- ranked by macro-F1, all 8 baseline models included
# ============================================================
leaderboard = pd.DataFrame(results).T.sort_values("macro_f1", ascending=False)
leaderboard.to_csv(f"{OUT_DIR}/leaderboard.csv")
print("\n===== Baseline Leaderboard (ranked by macro-F1) =====")
print(leaderboard.round(4).to_string())

# ============================================================
# 8B. HYPERPARAMETER TUNING -- XGBoost, LightGBM, HistGB, BalancedRandomForest
#    (RandomizedSearchCV) + CatBoost (manual loop, see note below).
#    Widened search spaces (not just more trials) for XGBoost/LightGBM.
# ============================================================
print("\n" + "=" * 60)
print("HYPERPARAMETER TUNING")
print("=" * 60)

TUNE_N_ITER = 3 if DRY_RUN else 40   # each iter = a full 3-fold CV with oversampling refit per fold
TUNE_CV = 3

param_dists = {
    "XGBoost": {
        "model__n_estimators": [200, 300, 500, 800],
        "model__max_depth": [4, 6, 8, 10],
        "model__learning_rate": [0.01, 0.05, 0.1, 0.2],
        "model__subsample": [0.6, 0.8, 1.0],
        "model__colsample_bytree": [0.6, 0.8, 1.0],
        "model__min_child_weight": [1, 3, 5, 7],
        "model__gamma": [0, 0.1, 0.3, 0.5],
        "model__reg_alpha": [0, 0.1, 0.5, 1.0],
        "model__reg_lambda": [0.5, 1.0, 2.0, 5.0],
    },
    "LightGBM": {
        "model__n_estimators": [200, 300, 500, 800],
        "model__num_leaves": [31, 63, 127, 255],
        "model__learning_rate": [0.01, 0.05, 0.1, 0.2],
        "model__subsample": [0.6, 0.8, 1.0],
        "model__colsample_bytree": [0.6, 0.8, 1.0],
        "model__min_child_samples": [10, 20, 40, 80],
        "model__reg_alpha": [0, 0.1, 0.5, 1.0],
        "model__reg_lambda": [0.5, 1.0, 2.0, 5.0],
    },
    "CatBoost": {
        "model__iterations": [200, 300, 500, 800],
        "model__depth": [4, 6, 8, 10],
        "model__learning_rate": [0.01, 0.05, 0.1, 0.2],
        "model__l2_leaf_reg": [1, 3, 5, 9],
    },
    "HistGB": {
        "model__max_iter": [200, 300, 500, 800],
        "model__max_depth": [None, 6, 8, 10],
        "model__learning_rate": [0.01, 0.05, 0.1, 0.2],
        "model__l2_regularization": [0, 0.1, 0.5, 1.0],
        "model__max_leaf_nodes": [15, 31, 63, 127],
    },
    "BalancedRandomForest": {
        "model__n_estimators": [200, 300, 500, 800],
        "model__max_depth": [None, 8, 12, 20],
        "model__min_samples_split": [2, 5, 10, 20],
        "model__min_samples_leaf": [1, 2, 4, 8],
    },
}

macro_f1_scorer = make_scorer(f1_score, average="macro")
tuned_results = {}
tuned_estimators = {}
tuned_best_params = {}   # raw (model__-stripped) params, for rebuilding fresh estimators later

for name in ["XGBoost", "LightGBM", "HistGB", "BalancedRandomForest"]:
    print(f"\nTuning {name}...")
    base_model = make_models()[name]

    if name == "BalancedRandomForest":
        # Always original (unbalanced) data -- same reasoning as its
        # baseline training above; oversampling before it would defeat its
        # own internal per-tree balancing.
        resample_step = "passthrough"
    else:
        resample_step = (RandomOverSampler(random_state=RANDOM_STATE)
                          if IMBALANCE_MODE == "oversample" else "passthrough")
    pipe = ImbPipeline([("oversample", resample_step), ("model", base_model)])
    X_tune, y_tune = X_train, y_train
    X_eval, y_eval = X_test, y_test

    search = RandomizedSearchCV(
        pipe, param_distributions=param_dists[name], n_iter=TUNE_N_ITER,
        scoring=macro_f1_scorer, cv=TUNE_CV, random_state=RANDOM_STATE,
        n_jobs=1, verbose=1, refit=True,
    )
    if name == "XGBoost" and IMBALANCE_MODE == "class_weight":
        sw = compute_sample_weight("balanced", y_tune)
        search.fit(X_tune, y_tune, model__sample_weight=sw)
    else:
        search.fit(X_tune, y_tune)
    print(f"Best params for {name}: {search.best_params_}")
    print(f"Best CV macro-F1 for {name}: {search.best_score_:.4f}")

    y_pred = search.predict(X_eval)
    tuned_results[name] = {
        "accuracy": accuracy_score(y_eval, y_pred),
        "macro_f1": f1_score(y_eval, y_pred, average="macro"),
        "macro_recall": recall_score(y_eval, y_pred, average="macro"),
    }
    for i, cls in enumerate(class_names):
        tuned_results[name][f"{cls}_recall"] = recall_score(
            y_eval, y_pred, average=None, labels=range(len(class_names)))[i]
    tuned_estimators[name] = search.best_estimator_
    tuned_best_params[name] = {k.replace("model__", ""): v for k, v in search.best_params_.items()}

    print(f"Held-out test performance for tuned {name}:")
    print(classification_report(y_eval, y_pred, target_names=class_names, digits=3))

# ------------------------------------------------------------------
# CatBoost: manual tuning loop, not RandomizedSearchCV -- sklearn's clone(),
# which RandomizedSearchCV calls internally between every trial, fails on
# CatBoostClassifier once cat_features is set ("Cannot clone object
# CatBoostClassifier(...), as the constructor either does not set or
# modifies parameter cat_features"). Confirmed by actually running it.
# ------------------------------------------------------------------
print("\nTuning CatBoost (manual loop -- see comment above for why)...")
rng = _random.Random(RANDOM_STATE)
cb_param_grid = param_dists["CatBoost"]
cb_trials = [{k: rng.choice(v) for k, v in cb_param_grid.items()} for _ in range(TUNE_N_ITER)]

cb_kwargs = {"auto_class_weights": "Balanced"} if IMBALANCE_MODE == "class_weight" else {}

cb_cv = StratifiedKFold(n_splits=TUNE_CV, shuffle=True, random_state=RANDOM_STATE)
best_score, best_params = -1, None
for trial_params in cb_trials:
    fold_scores = []
    for tr_idx, val_idx in cb_cv.split(X_train_cat, y_train):
        X_tr, X_val = X_train_cat.iloc[tr_idx], X_train_cat.iloc[val_idx]
        y_tr, y_val = y_train[tr_idx], y_train[val_idx]
        if IMBALANCE_MODE == "oversample":
            X_tr, y_tr = RandomOverSampler(random_state=RANDOM_STATE).fit_resample(X_tr, y_tr)
        params = {k.replace("model__", ""): v for k, v in trial_params.items()}
        m = CatBoostClassifier(cat_features=cat_feature_indices, random_state=RANDOM_STATE,
                                verbose=0, **cb_kwargs, **params)
        m.fit(X_tr, y_tr, cat_features=cat_feature_indices)
        pred = m.predict(X_val).flatten()
        fold_scores.append(f1_score(y_val, pred, average="macro"))
    mean_score = np.mean(fold_scores)
    if mean_score > best_score:
        best_score, best_params = mean_score, trial_params
print(f"Best params for CatBoost: {best_params}")
print(f"Best CV macro-F1 for CatBoost: {best_score:.4f}")

cb_final_params = {k.replace("model__", ""): v for k, v in best_params.items()}
train_X = X_train_cat_bal if IMBALANCE_MODE == "oversample" else X_train_cat
train_y = y_train_cat_bal if IMBALANCE_MODE == "oversample" else y_train
cb_final = CatBoostClassifier(cat_features=cat_feature_indices, random_state=RANDOM_STATE,
                               verbose=0, **cb_kwargs, **cb_final_params)
cb_final.fit(train_X, train_y, cat_features=cat_feature_indices)
y_pred = cb_final.predict(X_test_cat).flatten()
tuned_results["CatBoost"] = {
    "accuracy": accuracy_score(y_test, y_pred),
    "macro_f1": f1_score(y_test, y_pred, average="macro"),
    "macro_recall": recall_score(y_test, y_pred, average="macro"),
}
for i, cls in enumerate(class_names):
    tuned_results["CatBoost"][f"{cls}_recall"] = recall_score(
        y_test, y_pred, average=None, labels=range(len(class_names)))[i]
tuned_estimators["CatBoost"] = cb_final
tuned_best_params["CatBoost"] = cb_final_params
print("Held-out test performance for tuned CatBoost:")
print(classification_report(y_test, y_pred, target_names=class_names, digits=3))

# ============================================================
# 8C. VOTING + STACKING ENSEMBLES
#    Built only when IMBALANCE_MODE == "oversample" (the setting actually in
#    use). In "class_weight" mode, routing per-fold sample_weight for
#    XGBoost through a Pipeline nested inside VotingClassifier/
#    StackingClassifier isn't something sklearn does automatically without
#    explicit metadata routing -- easy to end up with weights silently not
#    propagating, producing misleading results rather than an obvious error.
#    Rather than build and only partially trust that path, the two new
#    ensembles are skipped entirely in class_weight mode.
# ============================================================


def unwrap_model(m):
    """Pull the raw fitted estimator out of an ImbPipeline wrapper, if any."""
    return m.named_steps["model"] if hasattr(m, "named_steps") else m


def build_fresh(name):
    """Fresh, unfitted estimator with the tuned hyperparameters. Not needed
    for correctness -- VotingClassifier/StackingClassifier call clone() on
    every estimator before fitting, which strips fitted state and keeps only
    constructor params regardless of whether the object passed in was
    already fitted (empirically confirmed against the installed sklearn:
    clone() on a fitted XGBClassifier raises NotFittedError on predict while
    keeping identical get_params()). Built explicitly anyway since it costs
    one line and removes even a hypothetical concern at zero cost."""
    base = make_models()[name]
    base.set_params(**tuned_best_params[name])
    return base


def make_ensemble_base(short_name, estimator):
    return (short_name, ImbPipeline([
        ("oversample", RandomOverSampler(random_state=RANDOM_STATE)),
        ("model", estimator),
    ]))


voting_clf = None
stacking_clf = None
best_stack_c = None

if IMBALANCE_MODE == "oversample":
    print("\nBuilding Voting/Stacking ensembles from tuned base learners...")
    fresh_xgb = build_fresh("XGBoost")
    fresh_lgbm = build_fresh("LightGBM")
    fresh_histgb = build_fresh("HistGB")
    fresh_rf = make_models()["Random Forest"]  # not separately tuned in this plan

    voting_base_estimators = [
        make_ensemble_base("xgb", fresh_xgb),
        make_ensemble_base("lgbm", fresh_lgbm),
        make_ensemble_base("histgb", fresh_histgb),
    ]
    stacking_base_estimators = voting_base_estimators + [make_ensemble_base("rf", fresh_rf)]

    # Meta-learner regularization chosen via a small grid rather than left at
    # sklearn's default -- base learners' OOF predictions are likely fairly
    # correlated (tuned XGB/LightGBM/HistGB often agree), and an unexamined
    # default risks the meta-learner overweighting that redundancy.
    _stack_c_grid = [1] if DRY_RUN else [0.01, 0.1, 1, 10]
    _stack_search_cv = StratifiedKFold(n_splits=(2 if DRY_RUN else 3), shuffle=True, random_state=RANDOM_STATE)
    best_stack_cv_score = -1
    for c in _stack_c_grid:
        candidate_stack = StackingClassifier(
            estimators=[(n, clone(p)) for n, p in stacking_base_estimators],
            final_estimator=LogisticRegression(C=c, max_iter=1000, random_state=RANDOM_STATE),
            cv=5, passthrough=False, n_jobs=1,
        )
        scores = cross_validate(candidate_stack, X_train, y_train, cv=_stack_search_cv,
                                 scoring=macro_f1_scorer, n_jobs=1)
        mean_score = float(np.mean(scores["test_score"]))
        print(f"  Stacking meta-learner C={c}: CV macro-F1={mean_score:.4f}")
        if mean_score > best_stack_cv_score:
            best_stack_cv_score, best_stack_c = mean_score, c
    print(f"Selected stacking meta-learner C={best_stack_c}")

    voting_clf = VotingClassifier(estimators=[(n, clone(p)) for n, p in voting_base_estimators],
                                   voting="soft", n_jobs=1)
    stacking_clf = StackingClassifier(
        estimators=[(n, clone(p)) for n, p in stacking_base_estimators],
        final_estimator=LogisticRegression(C=best_stack_c, max_iter=1000, random_state=RANDOM_STATE),
        cv=5, passthrough=False, n_jobs=1,
    )

    for ens_name, ens_model in [("Voting", voting_clf), ("Stacking", stacking_clf)]:
        print(f"Fitting {ens_name} ensemble...")
        ens_model.fit(X_train, y_train)
        y_pred = ens_model.predict(X_test)
        tuned_results[ens_name] = {
            "accuracy": accuracy_score(y_test, y_pred),
            "macro_f1": f1_score(y_test, y_pred, average="macro"),
            "macro_recall": recall_score(y_test, y_pred, average="macro"),
        }
        for i, cls in enumerate(class_names):
            tuned_results[ens_name][f"{cls}_recall"] = recall_score(
                y_test, y_pred, average=None, labels=range(len(class_names)))[i]
        tuned_estimators[ens_name] = ens_model
        print(f"Held-out test performance for {ens_name}:")
        print(classification_report(y_test, y_pred, target_names=class_names, digits=3))
else:
    print("\nSkipping Voting/Stacking ensembles: IMBALANCE_MODE == 'class_weight' "
          "(nested sample_weight routing through Pipeline->Ensemble isn't safe "
          "without explicit metadata routing). Existing class_weight experiment unaffected.")

tuned_leaderboard = pd.DataFrame(tuned_results).T.sort_values("macro_f1", ascending=False)
tuned_leaderboard.to_csv(f"{OUT_DIR}/tuned_leaderboard.csv")
print("\n===== Tuned/Ensemble Leaderboard (untouched test set, ranked by macro-F1) =====")
print(tuned_leaderboard.round(4).to_string())

# ============================================================
# 9. CROSS-VALIDATION -- baseline CV (all 8 models, untuned configs) +
#    tuned/ensemble CV (tuned XGB/LightGBM/HistGB/BalancedRandomForest/
#    CatBoost + Voting/Stacking), combined into one leaderboard with a
#    `Tuned` column so the two tiers aren't read as directly comparable.
#    Oversampling done INSIDE each fold via imblearn Pipeline (leak-safe);
#    Voting/Stacking already do this internally via their own ImbPipeline
#    base estimators, so cross_validate() on the built ensemble is
#    sufficient -- no separate manual loop needed for them.
# ============================================================
skf = StratifiedKFold(n_splits=(2 if DRY_RUN else 5), shuffle=True, random_state=RANDOM_STATE)
scoring = {
    "accuracy": "accuracy",
    "macro_f1": make_scorer(f1_score, average="macro"),
    "macro_recall": make_scorer(recall_score, average="macro"),
}

cv_rows = []  # list of dicts: {"Model":..., "Tuned":bool, "test_accuracy":..., ...}

for name, model in make_models().items():
    if name == "CatBoost":
        continue  # handled separately below (native categorical handling doesn't fit sklearn Pipeline)
    if name == "BalancedRandomForest":
        resample_step = "passthrough"
        X_cv, y_cv = X_train, y_train
    elif name == "Logistic Regression":
        resample_step = (RandomOverSampler(random_state=RANDOM_STATE)
                          if IMBALANCE_MODE == "oversample" else "passthrough")
        X_cv, y_cv = X_train_ohe, y_train_ohe
    else:
        resample_step = (RandomOverSampler(random_state=RANDOM_STATE)
                          if IMBALANCE_MODE == "oversample" else "passthrough")
        X_cv, y_cv = X_train, y_train
    pipe = ImbPipeline([("oversample", resample_step), ("model", model)])
    if name == "XGBoost" and IMBALANCE_MODE == "class_weight":
        sw = compute_sample_weight("balanced", y_cv)
        scores = cross_validate(pipe, X_cv, y_cv, cv=skf, scoring=scoring, n_jobs=1,
                                 params={"model__sample_weight": sw})
    else:
        scores = cross_validate(pipe, X_cv, y_cv, cv=skf, scoring=scoring, n_jobs=1)
    row = {f"test_{k}": np.mean(v) for k, v in scores.items() if k.startswith("test_")}
    row.update({"Model": name, "Tuned": False})
    cv_rows.append(row)

# CatBoost baseline CV: run separately (native categorical handling doesn't
# fit the sklearn Pipeline machinery cleanly).
cb_fold_scores = {"accuracy": [], "macro_f1": [], "macro_recall": []}
for tr_idx, val_idx in skf.split(X_train_cat, y_train):
    X_tr, X_val = X_train_cat.iloc[tr_idx], X_train_cat.iloc[val_idx]
    y_tr, y_val = y_train[tr_idx], y_train[val_idx]
    if IMBALANCE_MODE == "oversample":
        X_tr, y_tr = RandomOverSampler(random_state=RANDOM_STATE).fit_resample(X_tr, y_tr)
    m = CatBoostClassifier(iterations=300, depth=6, learning_rate=0.1,
                            cat_features=cat_feature_indices, random_state=RANDOM_STATE,
                            verbose=0, **cb_kwargs)
    m.fit(X_tr, y_tr, cat_features=cat_feature_indices)
    pred = m.predict(X_val).flatten()
    cb_fold_scores["accuracy"].append(accuracy_score(y_val, pred))
    cb_fold_scores["macro_f1"].append(f1_score(y_val, pred, average="macro"))
    cb_fold_scores["macro_recall"].append(recall_score(y_val, pred, average="macro"))
cv_rows.append({f"test_{k}": np.mean(v) for k, v in cb_fold_scores.items()} |
                {"Model": "CatBoost", "Tuned": False})

# Tuned/ensemble CV tier.
print("\nRunning CV for tuned models and ensembles...")
for name in ["XGBoost", "LightGBM", "HistGB", "BalancedRandomForest"]:
    est = clone(unwrap_model(tuned_estimators[name]))
    est.set_params(**tuned_best_params[name])
    if name == "BalancedRandomForest":
        resample_step = "passthrough"
    else:
        resample_step = (RandomOverSampler(random_state=RANDOM_STATE)
                          if IMBALANCE_MODE == "oversample" else "passthrough")
    pipe = ImbPipeline([("oversample", resample_step), ("model", est)])
    scores = cross_validate(pipe, X_train, y_train, cv=skf, scoring=scoring, n_jobs=1)
    row = {f"test_{k}": np.mean(v) for k, v in scores.items() if k.startswith("test_")}
    row.update({"Model": name, "Tuned": True})
    cv_rows.append(row)

cb_tuned_fold_scores = {"accuracy": [], "macro_f1": [], "macro_recall": []}
for tr_idx, val_idx in skf.split(X_train_cat, y_train):
    X_tr, X_val = X_train_cat.iloc[tr_idx], X_train_cat.iloc[val_idx]
    y_tr, y_val = y_train[tr_idx], y_train[val_idx]
    if IMBALANCE_MODE == "oversample":
        X_tr, y_tr = RandomOverSampler(random_state=RANDOM_STATE).fit_resample(X_tr, y_tr)
    m = CatBoostClassifier(cat_features=cat_feature_indices, random_state=RANDOM_STATE,
                            verbose=0, **cb_kwargs, **cb_final_params)
    m.fit(X_tr, y_tr, cat_features=cat_feature_indices)
    pred = m.predict(X_val).flatten()
    cb_tuned_fold_scores["accuracy"].append(accuracy_score(y_val, pred))
    cb_tuned_fold_scores["macro_f1"].append(f1_score(y_val, pred, average="macro"))
    cb_tuned_fold_scores["macro_recall"].append(recall_score(y_val, pred, average="macro"))
cv_rows.append({f"test_{k}": np.mean(v) for k, v in cb_tuned_fold_scores.items()} |
                {"Model": "CatBoost", "Tuned": True})

if IMBALANCE_MODE == "oversample":
    for ens_name, ens_model in [("Voting", voting_clf), ("Stacking", stacking_clf)]:
        scores = cross_validate(clone(ens_model), X_train, y_train, cv=skf, scoring=scoring, n_jobs=1)
        row = {f"test_{k}": np.mean(v) for k, v in scores.items() if k.startswith("test_")}
        row.update({"Model": ens_name, "Tuned": True})
        cv_rows.append(row)

cv_df_raw = pd.DataFrame(cv_rows)[["Model", "Tuned", "test_accuracy", "test_macro_f1", "test_macro_recall"]]
cv_df_raw = cv_df_raw.sort_values("test_macro_f1", ascending=False).reset_index(drop=True)
cv_df = cv_df_raw.set_index("Model")   # for CSV/printing/eligibility-max lookups (index can repeat: baseline + tuned rows share a Model name)
cv_df.to_csv(f"{OUT_DIR}/cv_leaderboard.csv")
print("\n===== 5-Fold CV Leaderboard (leak-safe, ranked by macro-F1) =====")
print(cv_df.round(4).to_string())

# ============================================================
# 9B. THRESHOLD-TUNED VARIANT OF THE BEST MODEL
#    Candidate chosen from the CV leaderboard (train-side only) -- NOT the
#    test leaderboard, since picking by test macro-F1 and then reporting
#    that same candidate's test macro-F1 after tuning would be test-set-
#    driven model selection.
# ============================================================
print("\n" + "=" * 60)
print("THRESHOLD TUNING (best CV candidate)")
print("=" * 60)

_best_cv_row = cv_df_raw.loc[cv_df_raw["test_macro_f1"].idxmax()]  # cv_df_raw has a unique positional
                                                                    # index (unlike Model-indexed cv_df,
                                                                    # where a name like "XGBoost" can
                                                                    # legitimately appear twice -- baseline
                                                                    # and tuned rows -- making label-based
                                                                    # .loc[] lookup ambiguous)
_candidate_name = _best_cv_row["Model"]
_candidate_cv_score = float(_best_cv_row["test_macro_f1"])
print(f"Threshold-tuning candidate (chosen by CV leaderboard): {_candidate_name} "
      f"(Tuned={_best_cv_row['Tuned']}, CV macro-F1={_candidate_cv_score:.4f})")


def get_repr_data(name):
    """(X_full_train, y_full_train, X_test_repr, needs_external_oversample)"""
    if name == "Logistic Regression":
        return X_train_ohe, y_train_ohe, X_test_ohe, True
    if name == "CatBoost":
        return X_train_cat, y_train, X_test_cat, True
    if name in ("BalancedRandomForest", "Voting", "Stacking"):
        return X_train, y_train, X_test, False
    return X_train, y_train, X_test, True  # Decision Tree, Random Forest, XGBoost, LightGBM, HistGB


def build_candidate(name):
    if name == "CatBoost":
        return CatBoostClassifier(cat_features=cat_feature_indices, random_state=RANDOM_STATE,
                                   verbose=0, **cb_kwargs, **cb_final_params)
    if name in tuned_best_params:
        return build_fresh(name)
    if name == "Voting":
        return clone(voting_clf)
    if name == "Stacking":
        return clone(stacking_clf)
    return make_models()[name]


def compute_oof_probabilities(name, n_splits=5):
    """Leak-safe OOF predict_proba over the full training set, using
    per-fold oversampling (fresh each fold) where applicable."""
    X_full, y_full, _, needs_resample = get_repr_data(name)
    is_sparse = sparse.issparse(X_full)
    n_rows = X_full.shape[0]
    oof = np.zeros((n_rows, len(class_names)))
    skf_oof = StratifiedKFold(n_splits=(2 if DRY_RUN else n_splits), shuffle=True, random_state=RANDOM_STATE)

    for tr_idx, val_idx in skf_oof.split(np.zeros(n_rows), y_full):
        if is_sparse:
            X_tr, X_val = X_full[tr_idx], X_full[val_idx]
        else:
            X_tr, X_val = X_full.iloc[tr_idx], X_full.iloc[val_idx]
        y_tr = y_full[tr_idx]

        est = build_candidate(name)
        if needs_resample and IMBALANCE_MODE == "oversample":
            X_tr, y_tr = RandomOverSampler(random_state=RANDOM_STATE).fit_resample(X_tr, y_tr)

        if name == "CatBoost":
            est.fit(X_tr, y_tr, cat_features=cat_feature_indices)
        elif name == "XGBoost" and IMBALANCE_MODE == "class_weight":
            sw = compute_sample_weight("balanced", y_tr)
            est.fit(X_tr, y_tr, sample_weight=sw)
        else:
            est.fit(X_tr, y_tr)

        oof[val_idx] = est.predict_proba(X_val)

    return oof, y_full


def search_class_weights(proba, y_true):
    """Grid search per-class probability multipliers (Minor fixed at 1.0)
    to maximize macro-F1. Grid search, not a continuous solver -- macro-F1
    under argmax is a discrete step function, so a gradient-free local
    optimizer has no real edge here and is harder to reproduce/debug."""
    weight_grid = [1] if DRY_RUN else [0.5, 1, 2, 3, 5, 8, 12]
    minor_idx = class_names.index("Minor")
    grievous_idx = class_names.index("Grievous")
    fatal_idx = class_names.index("Fatal")
    best_score, best_weights = -1, np.ones(len(class_names))
    for w_g in weight_grid:
        for w_f in weight_grid:
            weights = np.ones(len(class_names))
            weights[minor_idx] = 1.0
            weights[grievous_idx] = w_g
            weights[fatal_idx] = w_f
            preds = np.argmax(proba * weights, axis=1)
            score = f1_score(y_true, preds, average="macro")
            if score > best_score:
                best_score, best_weights = score, weights.copy()
    return best_weights, best_score


def is_degenerate(proba, weights, y_true):
    preds = np.argmax(proba * weights, axis=1)
    counts = np.bincount(preds, minlength=len(class_names))
    return bool(np.any(counts == 0))


oof_proba, oof_y = compute_oof_probabilities(_candidate_name)
threshold_weights, oof_macro_f1 = search_class_weights(oof_proba, oof_y)
print(f"OOF weight search macro-F1 (selection signal only, not reported as a "
      f"performance number): {oof_macro_f1:.4f}, weights={threshold_weights.tolist()}")

if is_degenerate(oof_proba, threshold_weights, oof_y):
    print("Degenerate weights detected (a class received zero predictions) -- "
          "falling back to CalibratedClassifierCV on training-side folds "
          "(same stratified k-fold split as the OOF pass, never the test set), "
          "then repeating the weight search against calibrated OOF probabilities.")
    X_full, y_full, _, needs_resample = get_repr_data(_candidate_name)
    is_sparse = sparse.issparse(X_full)
    n_rows = X_full.shape[0]
    calibrated_oof = np.zeros((n_rows, len(class_names)))
    skf_cal = StratifiedKFold(n_splits=(2 if DRY_RUN else 5), shuffle=True, random_state=RANDOM_STATE)
    for tr_idx, val_idx in skf_cal.split(np.zeros(n_rows), y_full):
        X_tr = X_full[tr_idx] if is_sparse else X_full.iloc[tr_idx]
        X_val = X_full[val_idx] if is_sparse else X_full.iloc[val_idx]
        y_tr = y_full[tr_idx]
        est = build_candidate(_candidate_name)
        if needs_resample and IMBALANCE_MODE == "oversample":
            X_tr, y_tr = RandomOverSampler(random_state=RANDOM_STATE).fit_resample(X_tr, y_tr)
        calibrated = CalibratedClassifierCV(est, cv=3)
        calibrated.fit(X_tr, y_tr)
        calibrated_oof[val_idx] = calibrated.predict_proba(X_val)
    threshold_weights, oof_macro_f1 = search_class_weights(calibrated_oof, y_full)
    print(f"Post-calibration OOF weight search macro-F1: {oof_macro_f1:.4f}, "
          f"weights={threshold_weights.tolist()}")

# Retrain on the full training set following IMBALANCE_MODE, then evaluate
# ONCE on the untouched test set with the frozen weights.
_, _, X_test_repr, needs_resample_final = get_repr_data(_candidate_name)
X_full, y_full, _, _ = get_repr_data(_candidate_name)
final_candidate = build_candidate(_candidate_name)
X_final_train, y_final_train = X_full, y_full
if needs_resample_final and IMBALANCE_MODE == "oversample":
    X_final_train, y_final_train = RandomOverSampler(random_state=RANDOM_STATE).fit_resample(X_full, y_full)

if _candidate_name == "CatBoost":
    final_candidate.fit(X_final_train, y_final_train, cat_features=cat_feature_indices)
elif _candidate_name == "XGBoost" and IMBALANCE_MODE == "class_weight":
    sw = compute_sample_weight("balanced", y_final_train)
    final_candidate.fit(X_final_train, y_final_train, sample_weight=sw)
else:
    final_candidate.fit(X_final_train, y_final_train)

test_proba = final_candidate.predict_proba(X_test_repr)
y_pred_threshold = np.argmax(test_proba * threshold_weights, axis=1)

threshold_tuned_name = f"{_candidate_name} + Threshold-Tuned"
tuned_results[threshold_tuned_name] = {
    "accuracy": accuracy_score(y_test, y_pred_threshold),
    "macro_f1": f1_score(y_test, y_pred_threshold, average="macro"),
    "macro_recall": recall_score(y_test, y_pred_threshold, average="macro"),
}
for i, cls in enumerate(class_names):
    tuned_results[threshold_tuned_name][f"{cls}_recall"] = recall_score(
        y_test, y_pred_threshold, average=None, labels=range(len(class_names)))[i]
tuned_estimators[threshold_tuned_name] = final_candidate

print(f"\nHeld-out test performance for {threshold_tuned_name}:")
print(classification_report(y_test, y_pred_threshold, target_names=class_names, digits=3))

tuned_leaderboard = pd.DataFrame(tuned_results).T.sort_values("macro_f1", ascending=False)
tuned_leaderboard.to_csv(f"{OUT_DIR}/tuned_leaderboard.csv")
print("\n===== Tuned/Ensemble Leaderboard incl. Threshold-Tuned (ranked by macro-F1) =====")
print(tuned_leaderboard.round(4).to_string())

# ============================================================
# 9C. BEATS-TOP-3 SUMMARY
#    Nothing is deleted from either leaderboard -- this is an explicit,
#    scannable readout on top of the full results, not a replacement for them.
# ============================================================
_previous_best_rows = {n: results[n]["macro_f1"] for n in ORIGINAL_SIX if n in results}
_previous_best_rows.update({n: tuned_results[n]["macro_f1"] for n in ["XGBoost", "LightGBM", "CatBoost"]
                             if n in tuned_results})
previous_best_model = max(_previous_best_rows, key=_previous_best_rows.get)
previous_best_f1 = _previous_best_rows[previous_best_model]

_all_new_entries = {**{k: v["macro_f1"] for k, v in results.items() if k not in ORIGINAL_SIX},
                     **{k: v["macro_f1"] for k, v in tuned_results.items()}}
best_new_model = max(_all_new_entries, key=_all_new_entries.get)
best_new_f1 = _all_new_entries[best_new_model]
beats_previous = best_new_f1 > previous_best_f1

summary_block = {
    "best_new_model": best_new_model,
    "best_new_macro_f1": round(best_new_f1, 4),
    "previous_best_model": previous_best_model,
    "previous_best_macro_f1": round(previous_best_f1, 4),
    "delta_macro_f1": round(best_new_f1 - previous_best_f1, 4),
    "beats_previous_best": bool(beats_previous),
}
print("\n===== Beats-Top-3 Summary =====")
for k, v in summary_block.items():
    print(f"{k}: {v}")

# ============================================================
# 9D. PERSIST EXPENSIVE ARTIFACTS
#    A multi-hour run producing tuned models, ensembles, and threshold
#    weights is too costly to redo casually if anything downstream needs it.
# ============================================================
print("\nSaving model artifacts...")


def save_model_artifact(name, model):
    safe_name = name.replace(" ", "_").replace("+", "plus").replace("(", "").replace(")", "")
    raw_model = unwrap_model(model)
    if isinstance(raw_model, CatBoostClassifier):
        raw_model.save_model(os.path.join(MODELS_DIR, f"{safe_name}.cbm"))
    else:
        joblib.dump(model, os.path.join(MODELS_DIR, f"{safe_name}.joblib"))


for name, model in models.items():
    save_model_artifact(f"baseline_{name}", model)
for name, model in tuned_estimators.items():
    save_model_artifact(name, model)

with open(os.path.join(MODELS_DIR, "threshold_weights.json"), "w") as f:
    json.dump({
        "candidate_model": _candidate_name,
        "weights": {cls: float(w) for cls, w in zip(class_names, threshold_weights)},
    }, f, indent=2)

preprocessing_metadata = {
    "class_names": class_names,
    "categorical_columns": CATEGORICAL_COLS,
    "label_encoder_classes": {col: list(enc.classes_) for col, enc in encoders.items()},
    "district_freq": {str(k): float(v) for k, v in district_freq.items()},
    "train_medians": {col: float(v) for col, v in train_medians.items()},
    "feature_columns_label_encoded": X_enc.columns.tolist(),
    "ohe_feature_names": ohe_feature_names,
    "ohe_resampler_used": OHE_RESAMPLER_NAME,
    "imbalance_mode": IMBALANCE_MODE,
    "random_state": RANDOM_STATE,
}
with open(os.path.join(MODELS_DIR, "preprocessing_metadata.json"), "w") as f:
    json.dump(preprocessing_metadata, f, indent=2)

model_selection_summary = {
    "chosen_model": _candidate_name,
    "chosen_cv_macro_f1": _candidate_cv_score,
    "test_macro_f1_threshold_tuned": float(tuned_results[threshold_tuned_name]["macro_f1"]),
    "threshold_weights": {cls: float(w) for cls, w in zip(class_names, threshold_weights)},
    "random_state": RANDOM_STATE,
    "imbalance_mode": IMBALANCE_MODE,
    "beats_top3_summary": summary_block,
}
with open(os.path.join(MODELS_DIR, "model_selection_summary.json"), "w") as f:
    json.dump(model_selection_summary, f, indent=2)

print(f"Artifacts saved to {MODELS_DIR}/")

# ============================================================
# 10. FULL SUB-CATEGORY (PER-LEVEL) SHAP
#    For every categorical column and every level within it (no cap,
#    including all 422 districts), per-class mean/std SHAP aggregated over
#    all rows at that level. Top 4 models chosen by CV leaderboard (not test
#    macro-F1 -- not because test-based selection would leak here, SHAP
#    doesn't feed back into any reported metric, but because CV-averaged
#    macro-F1 is less noisy given how few Fatal rows exist even in the full
#    test set, and it's one consistent selection criterion across the plan).
# ============================================================
print("\n" + "=" * 60)
print("SUB-CATEGORY SHAP")
print("=" * 60)

_shap_eligible = ["Decision Tree", "Random Forest", "XGBoost", "LightGBM",
                   "HistGB", "BalancedRandomForest", "CatBoost"]
_eligible_cv_scores = {}
for name in _shap_eligible:
    if name in cv_df.index:
        # if both baseline and tuned rows exist for this name, take the max
        _score = cv_df.loc[name, "test_macro_f1"]
        _eligible_cv_scores[name] = float(_score) if isinstance(_score, (int, float, np.floating)) else float(_score.max())

_top4_names = sorted(_eligible_cv_scores, key=_eligible_cv_scores.get, reverse=True)[:4]
print(f"Top 4 models selected for sub-category SHAP (by CV macro-F1): {_top4_names}")


def get_fitted_model_and_repr(name):
    """(fitted_model, X_explain, X_raw_subset) using the model's own native
    training representation -- CatBoost gets X_test_cat (its training
    schema), everything else gets X_test/X_enc."""
    if name in tuned_estimators and name != "CatBoost":
        model = unwrap_model(tuned_estimators[name])
    elif name == "CatBoost":
        model = tuned_estimators.get("CatBoost", models["CatBoost"])
    else:
        model = models[name]

    if name == "CatBoost":
        return model, X_test_cat, X_test_cat
    return model, X_test, X_test_cat  # X_test_cat used only for grouping (representation-independent)


SHAP_N_ROWS = 200 if DRY_RUN else len(X_test)

for name in _top4_names:
    print(f"\nRunning full-test-set sub-category SHAP for {name}...")
    model, X_explain_full, X_raw_full = get_fitted_model_and_repr(name)
    X_explain = X_explain_full.iloc[:SHAP_N_ROWS].reset_index(drop=True)
    X_raw_subset = X_raw_full.iloc[:SHAP_N_ROWS].reset_index(drop=True)

    if name == "CatBoost":
        pool = Pool(X_explain, cat_features=cat_feature_indices)
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(pool, check_additivity=False)
    else:
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_explain, check_additivity=False)

    if isinstance(shap_values, list) and len(shap_values) == len(class_names):
        sv_list = shap_values
    elif isinstance(shap_values, np.ndarray) and shap_values.ndim == 3:
        sv_list = [shap_values[:, :, i] for i in range(shap_values.shape[2])]
    else:
        raise ValueError(f"Unexpected SHAP output shape for {name}: {np.shape(shap_values)}")

    model_dir = os.path.join(SHAP_DIR, name.replace(" ", "_"))
    os.makedirs(model_dir, exist_ok=True)
    feature_cols = X_explain.columns.tolist()
    summary_rows = []

    for cat_col in CATEGORICAL_COLS:
        col_idx = feature_cols.index(cat_col)
        cat_dir = os.path.join(model_dir, cat_col.replace("/", "_").replace("(", "").replace(")", ""))
        os.makedirs(cat_dir, exist_ok=True)
        levels = X_raw_subset[cat_col].astype(str)

        for cls_idx, cls_name in enumerate(class_names):
            sv_col = sv_list[cls_idx][:, col_idx]
            df_level = pd.DataFrame({"Level": levels.values, "SHAP": sv_col})
            g = df_level.groupby("Level")["SHAP"]
            grouped = pd.DataFrame({
                "N_rows": g.count(),
                "Mean_SHAP": g.mean(),
                "Std_SHAP": g.std().fillna(0.0),
                "Mean_Abs_SHAP": g.apply(lambda s: s.abs().mean()),
            }).reset_index()
            grouped["Low_Sample"] = grouped["N_rows"] < 30
            grouped = grouped.sort_values("Mean_Abs_SHAP", ascending=False)
            grouped.to_csv(os.path.join(cat_dir, f"{cls_name}.csv"), index=False)

            grouped_long = grouped.copy()
            grouped_long.insert(0, "Category", cat_col)
            grouped_long.insert(2, "Class", cls_name)
            summary_rows.append(grouped_long)

    summary_df = pd.concat(summary_rows, ignore_index=True)
    summary_df = summary_df[["Category", "Level", "Class", "N_rows", "Mean_SHAP",
                              "Mean_Abs_SHAP", "Std_SHAP", "Low_Sample"]]
    summary_df.to_csv(os.path.join(model_dir, "subcategory_shap_summary.csv"), index=False)

    # Memory hygiene: one model at a time, explicit cleanup before the next.
    del shap_values, sv_list, summary_rows, summary_df
    gc.collect()

print("\nNote: Voting/Stacking are meta-ensembles without a single coherent "
      "tree structure -- sub-category SHAP is not computed for them directly. "
      "See the base learners' own SHAP output above instead.")
print("Note: for XGBoost/LightGBM/HistGB/RandomForest/BalancedRandomForest, "
      "the label-encoded category values are ordinary numeric inputs to those "
      "models (no native categorical awareness) -- read their Mean_SHAP as "
      "'contribution associated with rows at this category level', not a "
      "causal category effect. CatBoost has genuine native categorical "
      "handling, so its numbers are the more directly interpretable ones.")

# ============================================================
# 10B. GLOBAL PER-CLASS SHAP (OHE feature set) -- unchanged from the
#    original approach, using whichever OHE resampler won in section 6B.
# ============================================================
shap.initjs()
tree_models_for_shap = {"Decision Tree", "Random Forest", "XGBoost", "LightGBM"}
ohe_models = {}
for name in tree_models_for_shap | {"Logistic Regression"}:
    m = make_models()[name]
    if IMBALANCE_MODE == "oversample":
        m.fit(X_train_ohe_bal, y_train_ohe_bal)
    else:
        if name == "XGBoost":
            sw = compute_sample_weight("balanced", y_train_ohe)
            m.fit(X_train_ohe, y_train_ohe, sample_weight=sw)
        else:
            m.fit(X_train_ohe, y_train_ohe)
    ohe_models[name] = m


def sample_rows_dense(X_sparse, n, seed):
    rng = np.random.RandomState(seed)
    n = min(n, X_sparse.shape[0])
    idx = rng.choice(X_sparse.shape[0], size=n, replace=False)
    return X_sparse[idx].toarray()


background = sample_rows_dense(X_train_ohe, 100, RANDOM_STATE)


def compute_shap(name, model, X_explain):
    if name == "Logistic Regression":
        explainer = shap.LinearExplainer(model, background)
        sv = explainer.shap_values(X_explain)
    else:
        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(X_explain, check_additivity=False)
    if isinstance(sv, list) and len(sv) == len(class_names):
        return sv
    elif isinstance(sv, np.ndarray) and sv.ndim == 3:
        return [sv[:, :, i] for i in range(sv.shape[2])]
    elif isinstance(sv, np.ndarray) and sv.ndim == 2:
        raise ValueError(
            f"Unexpected 2D SHAP output for {len(class_names)}-class problem -- "
            f"shape {sv.shape}. This needs a real fix, not the old [sv,-sv,sv] guess."
        )
    return sv


def plot_shap_global(name, model, X_explain):
    shap_values = compute_shap(name, model, X_explain)
    model_dir = os.path.join(OUT_DIR, name.replace(" ", "_"))
    os.makedirs(model_dir, exist_ok=True)
    for cls_idx, cls_name in enumerate(class_names):
        fig = plt.figure(figsize=(12, 9))
        shap.summary_plot(shap_values[cls_idx], X_explain, feature_names=ohe_feature_names,
                           max_display=30, show=False)
        plt.title(f"{name} | {cls_name}")
        plt.tight_layout()
        plt.savefig(os.path.join(model_dir, f"{cls_name}_beeswarm.png"), dpi=150)
        plt.close(fig)

        stats = pd.DataFrame({
            "Feature": ohe_feature_names,
            "Mean_Abs_SHAP": np.mean(np.abs(shap_values[cls_idx]), axis=0),
        }).sort_values("Mean_Abs_SHAP", ascending=False)
        stats.to_csv(os.path.join(model_dir, f"{cls_name}_stats.csv"), index=False)


SAMPLE_SIZE_FOR_SHAP = {"Decision Tree": 500, "Logistic Regression": 500,
                         "Random Forest": 150, "XGBoost": 400, "LightGBM": 500}
if DRY_RUN:
    SAMPLE_SIZE_FOR_SHAP = {k: 50 for k in SAMPLE_SIZE_FOR_SHAP}

for name, model in ohe_models.items():
    X_shap = sample_rows_dense(X_test_ohe, SAMPLE_SIZE_FOR_SHAP.get(name, 300), RANDOM_STATE)
    print(f"Running global SHAP for {name}...")
    plot_shap_global(name, model, X_shap)

print(f"\nDone. Leaderboards, confusion matrices, models, and SHAP outputs are in {OUT_DIR}/")
