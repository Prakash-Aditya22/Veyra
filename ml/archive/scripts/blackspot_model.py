"""
SEGMENT-LEVEL BLACKSPOT MODEL  (Safety Performance Function)

The earlier approach predicted severity per crash and summed the
probabilities into a segment score. It barely beat counting crashes, and the
reason is structural: blackspot risk is FREQUENCY x SEVERITY, and a per-crash
severity classifier models only the second term. Crash counts already encode
the first, which is why they were competitive.

This models the thing that actually matters: expected KSI count per segment,
from segment characteristics. That is the Safety Performance Function used in
road safety engineering, and the per-crash severity model becomes one input
feature rather than the whole method.

SETUP (strictly prospective -- no target leakage)
    features : built from 2009-2013 crashes only
    target   : KSI count in 2014-2015
    split    : segments split into train/test, so the model is scored on
               segments it never saw, predicting a period it never saw

Poisson objective, because the target is a count with variance rising in the
mean -- squared error would treat a 0-vs-2 error the same as 20-vs-22.

Outputs feed the web service directly: a score per segment, SHAP drivers
explaining WHY, and a SHAP-based typology grouping segments by the KIND of
risk they carry (which determines what intervention would help).
"""
import warnings; warnings.filterwarnings("ignore")
import json
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.cluster import KMeans
from lightgbm import LGBMRegressor, LGBMClassifier
import shap

RS = 42
SEG_M = 500
BUILD = [2009, 2010, 2011, 2012, 2013]
FUTURE = [2014, 2015]
M_PER_DEG_LAT = 111_320.0

print("loading ...")
df = pd.read_csv("stats19_2009_2015.csv", low_memory=False)
lat, lon = df["latitude"].values, df["longitude"].values
df["seg_x"] = np.floor(lon * M_PER_DEG_LAT * np.cos(np.radians(lat)) / SEG_M).astype(np.int32)
df["seg_y"] = np.floor(lat * M_PER_DEG_LAT / SEG_M).astype(np.int32)
df["segment_id"] = df.seg_x.astype(str) + "_" + df.seg_y.astype(str)
df["is_ksi"] = (df.Accident_Severity != "Minor").astype(int)
df["is_fatal"] = (df.Accident_Severity == "Fatal").astype(int)
b = df[df.collision_year.isin(BUILD)].copy()
f = df[df.collision_year.isin(FUTURE)]
print(f"  {len(b):,} build crashes, {len(f):,} future crashes, "
      f"{b.segment_id.nunique():,} segments")

# ---------- per-crash severity model, as ONE segment feature ----------
# Calibrated (no class_weight): these probabilities are averaged per segment,
# so they must reflect true prevalence rather than a rebalanced prior.
print("\nper-crash severity model (feeds in as a feature) ...")
DROP = {"Accident_Severity", "collision_index", "collision_year", "segment_id",
        "seg_x", "seg_y", "is_ksi", "is_fatal",
        "did_police_officer_attend_scene_of_accident"}
FEATS = [c for c in df.columns if c not in DROP]
Xc = np.empty((len(df), len(FEATS)), dtype=np.float32)
for i, c in enumerate(FEATS):
    col = df[c]
    Xc[:, i] = (LabelEncoder().fit_transform(col.fillna("NA").astype(str))
                if col.dtype == object else pd.to_numeric(col, errors="coerce"))
Xc[~np.isfinite(Xc)] = np.nan
bi = b.index.values
sev = LGBMClassifier(n_estimators=300, num_leaves=63, learning_rate=0.05,
                     min_child_samples=40, random_state=RS, n_jobs=-1,
                     verbose=-1).fit(Xc[bi], b.is_ksi)
b["p_ksi"] = sev.predict_proba(Xc[bi])[:, 1]
print(f"  calibration: mean predicted {b.p_ksi.mean():.4f} vs actual {b.is_ksi.mean():.4f}")

# ---------- segment features, from BUILD YEARS ONLY ----------
print("\nbuilding segment features ...")


def mode_or_nan(s):
    m = s.mode()
    return m.iloc[0] if len(m) else np.nan


g = b.groupby("segment_id")
seg = pd.DataFrame({
    "n_crashes": g.size(),
    "n_ksi": g.is_ksi.sum(),
    "n_fatal": g.is_fatal.sum(),
    "mean_p_ksi": g.p_ksi.mean(),          # severity model's contribution
    "max_p_ksi": g.p_ksi.max(),
    "lat": g.latitude.mean(),
    "lon": g.longitude.mean(),
    "speed_max": g.speed_limit.max(),
    "speed_mean": g.speed_limit.mean(),
    "n_veh_mean": g.number_of_vehicles.mean(),
    "n_cas_mean": g.number_of_casualties.mean(),
    "n_years_active": g.collision_year.nunique(),
    "n_roads": g.first_road_number.nunique(),
})
for col in ["road_type", "junction_detail", "urban_or_rural_area", "light_conditions",
            "first_road_class", "speed_limit", "junction_control"]:
    if col in b.columns:
        seg[f"mode_{col}"] = g[col].agg(mode_or_nan)
for col, name in [("light_conditions", "pct_dark"), ("road_surface_conditions", "pct_wet")]:
    if col in b.columns:
        seg[name] = g[col].agg(lambda s: (s != s.mode().iloc[0]).mean() if len(s.mode()) else 0)
ped = [c for c in b.columns if c.startswith("k_casualty_class_")]
if ped:
    seg["pct_ped"] = g[ped[-1]].mean()
seg["crashes_per_year"] = seg.n_crashes / len(BUILD)
seg["ksi_rate"] = seg.n_ksi / seg.n_crashes
seg = seg.reset_index()

# ---------- target: FUTURE KSI ----------
fut = f.groupby("segment_id").agg(future_ksi=("is_ksi", "sum"),
                                  future_fatal=("is_fatal", "sum")).reset_index()
seg = seg.merge(fut, on="segment_id", how="left").fillna({"future_ksi": 0, "future_fatal": 0})
print(f"  {len(seg):,} segments, {seg.future_ksi.sum():,.0f} future KSI to predict")

# ---------- model ----------
MDROP = {"segment_id", "future_ksi", "future_fatal"}
MF = [c for c in seg.columns if c not in MDROP]
Xs = seg[MF].apply(pd.to_numeric, errors="coerce").astype(np.float32)
ys = seg.future_ksi.values

tr, te = train_test_split(np.arange(len(seg)), test_size=0.3, random_state=RS)
print(f"\ntraining Poisson SPF on {len(tr):,} segments, testing on {len(te):,} ...")
spf = LGBMRegressor(objective="poisson", n_estimators=600, num_leaves=63,
                    learning_rate=0.05, min_child_samples=40, colsample_bytree=0.7,
                    reg_lambda=1.0, random_state=RS, n_jobs=-1, verbose=-1)
spf.fit(Xs.iloc[tr], ys[tr])
seg["predicted_ksi"] = spf.predict(Xs)

# ---------- validate: does it beat counting, on unseen segments? ----------
t = seg.iloc[te]
tot = t.future_ksi.sum()
print("\n" + "=" * 88)
print("BLACKSPOT RANKING -- held-out segments, predicting 2014-2015 KSI")
print("=" * 88)
print(f"{'method':28s} {'top 1%':>9} {'top 5%':>9} {'top 10%':>9} {'top 20%':>9}")
methods = {"SPF (segment count model)": t.predicted_ksi.values,
           "per-crash severity sum": (t.n_crashes * t.mean_p_ksi).values,
           "observed KSI count": t.n_ksi.values,
           "raw crash count": t.n_crashes.values}
rows = []
for name, sc in methods.items():
    o = np.argsort(-sc)
    caps = [t.future_ksi.values[o[:int(len(t) * p)]].sum() / tot * 100
            for p in [.01, .05, .10, .20]]
    rows.append({"method": name, **{f"top{int(p*100)}pct": c for p, c in zip([.01, .05, .1, .2], caps)}})
    print(f"{name:28s} {caps[0]:8.2f}% {caps[1]:8.2f}% {caps[2]:8.2f}% {caps[3]:8.2f}%")

# ---------- SHAP: why is a segment risky ----------
print("\ncomputing SHAP on the segment model ...")
sv = shap.TreeExplainer(spf).shap_values(Xs)
imp = pd.DataFrame({"feature": MF, "mean_abs_shap": np.abs(sv).mean(0)}
                   ).sort_values("mean_abs_shap", ascending=False)
print(imp.head(12).round(4).to_string(index=False))

# top 3 drivers per segment, for the API payload
order = np.argsort(-np.abs(sv), axis=1)[:, :3]
seg["top_drivers"] = [json.dumps([{"feature": MF[j], "shap": round(float(sv[i, j]), 4)}
                                  for j in order[i]]) for i in range(len(seg))]

# ---------- SHAP typology: what KIND of blackspot ----------
# Clustering on SHAP profiles rather than raw features groups segments by WHY
# they are risky, which is what determines the appropriate intervention.
print("\nclustering segments by SHAP profile ...")
top_seg = seg.nlargest(20000, "predicted_ksi").index
Z = StandardScaler().fit_transform(sv[top_seg])
km = KMeans(n_clusters=5, random_state=RS, n_init=10).fit(Z)
seg["blackspot_type"] = -1
seg.loc[top_seg, "blackspot_type"] = km.labels_

print("\nblackspot types (mean SHAP driver per cluster):")
for c in range(5):
    m = seg.loc[top_seg][seg.loc[top_seg].blackspot_type == c]
    idx = seg.loc[top_seg].blackspot_type.values == c
    prof = pd.Series(sv[top_seg][idx].mean(0), index=MF).sort_values(key=abs, ascending=False)
    print(f"\n  type {c}: {idx.sum():,} segments, mean predicted KSI {m.predicted_ksi.mean():.2f}")
    print(f"    drivers: {', '.join(f'{k} {v:+.3f}' for k, v in prof.head(4).items())}")

# ---------- output ----------
out = seg.sort_values("predicted_ksi", ascending=False).reset_index(drop=True)
out["rank"] = np.arange(1, len(out) + 1)
cols = ["rank", "segment_id", "lat", "lon", "predicted_ksi", "n_crashes", "n_ksi",
        "n_fatal", "crashes_per_year", "ksi_rate", "mean_p_ksi", "blackspot_type",
        "top_drivers", "future_ksi"]
out[cols].to_csv("blackspot_scored_segments.csv", index=False)
# full unsorted frame: downstream stages need every segment feature, and a
# sorted file would break positional train/test indices
seg.to_parquet("segment_features.parquet", index=False)
np.save("segment_split_test_idx.npy", te)
out[cols].head(500).to_json("blackspot_top500.json", orient="records", indent=2)
pd.DataFrame(rows).to_csv("blackspot_model_validation.csv", index=False)
imp.to_csv("blackspot_shap_importance.csv", index=False)

print("\n" + "=" * 88)
print("TOP 10 SEGMENTS")
print("=" * 88)
print(out[["rank", "segment_id", "lat", "lon", "predicted_ksi", "n_crashes",
           "n_ksi", "blackspot_type", "future_ksi"]].head(10).round(3).to_string(index=False))
print("\nSaved: blackspot_scored_segments.csv, blackspot_top500.json, "
      "blackspot_model_validation.csv, blackspot_shap_importance.csv")
