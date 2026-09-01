"""
SEVERITY AS A CONTINUOUS SPECTRUM -- casualty cost rather than class labels.

Classification forces the model to fight a 1.16% minority. Road safety
practice does not classify crashes, it COSTS them: DfT assigns a monetary
value to each prevented casualty and authorities rank sites by expected
casualty cost. That converts a hopeless imbalanced-classification problem
into a well-behaved continuous regression.

    Fatal    GBP 2,834,336 per collision
    Serious  GBP   324,895 per collision
    Slight   GBP    32,502 per collision

Source: DfT table RAS4001 "Cost of prevention of collisions", 2024 prices,
downloaded and read directly rather than estimated. Per-COLLISION values are
used because this data is collision-level -- they already account for the
average number of casualties and for damage costs, so no assumption is needed
about how casualties are distributed within a crash.

TESTED AGAINST the KSI-count formulation on the same held-out segments, so
this is a measured comparison rather than an assertion.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder
from lightgbm import LGBMRegressor

RS = 42
SEG_M = 500
BUILD = [2009, 2010, 2011, 2012, 2013]
FUTURE = [2014, 2015]
M_PER_DEG_LAT = 111_320.0

# DfT RAS4001, 2024 prices, "Cost per collision" column. Verified against the
# published spreadsheet rather than estimated. Per-COLLISION values are used
# (not per-casualty) because this data is collision-level: they already fold in
# the average number of casualties plus damage costs, which removes the need to
# approximate how casualties are distributed within a crash.
#   Fatal 2,834,335.82 | Serious 324,894.76 | Slight 32,502.25
COST = {"Fatal": 2_834_335.82, "Grievous": 324_894.76, "Minor": 32_502.25}

print("loading ...")
df = pd.read_csv("stats19_2009_2015.csv", low_memory=False)
lat, lon = df.latitude.values, df.longitude.values
df["seg_x"] = np.floor(lon * M_PER_DEG_LAT * np.cos(np.radians(lat)) / SEG_M).astype(np.int32)
df["seg_y"] = np.floor(lat * M_PER_DEG_LAT / SEG_M).astype(np.int32)
df["segment_id"] = df.seg_x.astype(str) + "_" + df.seg_y.astype(str)
df["is_ksi"] = (df.Accident_Severity != "Minor").astype(int)

df["cost"] = df.Accident_Severity.map(COST)   # per-collision value; casualty count already embedded
print(f"  total casualty cost 2009-2015: GBP {df.cost.sum()/1e9:.1f}bn")
print(f"  mean per crash: GBP {df.cost.mean():,.0f}")

b = df[df.collision_year.isin(BUILD)].copy()
f = df[df.collision_year.isin(FUTURE)]

# ---------- segment features (same construction as the KSI model) ----------
def mode_or_nan(s):
    m = s.mode()
    return m.iloc[0] if len(m) else np.nan


g = b.groupby("segment_id")
seg = pd.DataFrame({
    "n_crashes": g.size(),
    "n_ksi": g.is_ksi.sum(),
    "past_cost": g.cost.sum(),
    "mean_cost": g.cost.mean(),
    "lat": g.latitude.mean(), "lon": g.longitude.mean(),
    "speed_max": g.speed_limit.max(), "speed_mean": g.speed_limit.mean(),
    "n_veh_mean": g.number_of_vehicles.mean(),
    "n_cas_mean": g.number_of_casualties.mean(),
    "n_years_active": g.collision_year.nunique(),
    "n_roads": g.first_road_number.nunique(),
})
for col in ["road_type", "junction_detail", "urban_or_rural_area", "light_conditions",
            "first_road_class", "speed_limit", "junction_control"]:
    if col in b.columns:
        seg[f"mode_{col}"] = g[col].agg(mode_or_nan)
seg["crashes_per_year"] = seg.n_crashes / len(BUILD)
seg = seg.reset_index()

fut = f.groupby("segment_id").agg(future_cost=("cost", "sum"),
                                  future_ksi=("is_ksi", "sum")).reset_index()
seg = seg.merge(fut, on="segment_id", how="left").fillna({"future_cost": 0, "future_ksi": 0})
print(f"  {len(seg):,} segments | future cost to predict: GBP {seg.future_cost.sum()/1e9:.2f}bn")

MDROP = {"segment_id", "future_cost", "future_ksi"}
MF = [c for c in seg.columns if c not in MDROP]
X = seg[MF].apply(pd.to_numeric, errors="coerce").astype(np.float32)

te = np.load("segment_split_test_idx.npy")          # identical split to the KSI model
tr = np.setdiff1d(np.arange(len(seg)), te)

# Tweedie: casualty cost is zero for most segments and continuous-positive
# otherwise -- exactly the compound Poisson-gamma shape Tweedie is built for.
# Poisson would treat cost as a count; squared error would be swamped by the
# handful of very expensive segments.
print("\ntraining cost model (Tweedie) ...")
cost_m = LGBMRegressor(objective="tweedie", tweedie_variance_power=1.5,
                       n_estimators=600, num_leaves=63, learning_rate=0.05,
                       min_child_samples=40, colsample_bytree=0.7, reg_lambda=1.0,
                       random_state=RS, n_jobs=-1, verbose=-1)
cost_m.fit(X.iloc[tr], seg.future_cost.values[tr])
seg["pred_cost"] = cost_m.predict(X)

print("training KSI-count model for comparison (Poisson) ...")
ksi_m = LGBMRegressor(objective="poisson", n_estimators=600, num_leaves=63,
                      learning_rate=0.05, min_child_samples=40, colsample_bytree=0.7,
                      reg_lambda=1.0, random_state=RS, n_jobs=-1, verbose=-1)
ksi_m.fit(X.iloc[tr], seg.future_ksi.values[tr])
seg["pred_ksi"] = ksi_m.predict(X)

# ---------- compare on held-out segments ----------
t = seg.iloc[te]
tot_cost, tot_ksi = t.future_cost.sum(), t.future_ksi.sum()

print("\n" + "=" * 96)
print("RANKING COMPARISON -- held-out segments")
print("=" * 96)
scores = {"cost model (Tweedie)": t.pred_cost.values,
          "KSI count model (Poisson)": t.pred_ksi.values,
          "past casualty cost": t.past_cost.values,
          "raw crash count": t.n_crashes.values}

print("\n% of future CASUALTY COST captured  <- the money-weighted objective")
print(f"{'score':30s} {'top 1%':>9} {'top 5%':>9} {'top 10%':>9} {'top 20%':>9}")
for name, sc in scores.items():
    o = np.argsort(-sc)
    caps = [t.future_cost.values[o[:int(len(t)*p)]].sum()/tot_cost*100 for p in [.01,.05,.1,.2]]
    print(f"{name:30s} {caps[0]:8.2f}% {caps[1]:8.2f}% {caps[2]:8.2f}% {caps[3]:8.2f}%")

print("\n% of future KSI captured  <- the old objective, for continuity")
for name, sc in scores.items():
    o = np.argsort(-sc)
    caps = [t.future_ksi.values[o[:int(len(t)*p)]].sum()/tot_ksi*100 for p in [.01,.05,.1,.2]]
    print(f"{name:30s} {caps[0]:8.2f}% {caps[1]:8.2f}% {caps[2]:8.2f}% {caps[3]:8.2f}%")

# ---------- what the top segments are worth ----------
out = seg.sort_values("pred_cost", ascending=False).reset_index(drop=True)
out["rank"] = np.arange(1, len(out)+1)
out["pred_cost_per_year"] = out.pred_cost / len(FUTURE)
print("\n" + "=" * 96)
print("TOP 10 BY PREDICTED CASUALTY COST")
print("=" * 96)
show = out.head(10)[["rank","segment_id","lat","lon","n_crashes","n_ksi",
                     "pred_cost_per_year","future_cost"]].copy()
show["pred_cost_per_year"] = show.pred_cost_per_year.map(lambda v: f"GBP {v:,.0f}")
show["future_cost"] = show.future_cost.map(lambda v: f"GBP {v:,.0f}")
print(show.to_string(index=False))

top1 = out.head(int(len(out)*0.01))
print(f"\nTop 1% of segments ({len(top1):,}) carry a predicted "
      f"GBP {top1.pred_cost_per_year.sum()/1e6:,.0f}m/year in casualty cost")

out[["rank","segment_id","lat","lon","pred_cost","pred_cost_per_year","pred_ksi",
     "n_crashes","n_ksi","past_cost","future_cost"]].to_csv("blackspot_cost_ranked.csv", index=False)
print("\nSaved: blackspot_cost_ranked.csv")
