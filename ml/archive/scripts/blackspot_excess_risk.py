"""
EXCESS-RISK MODEL + WORKING SHAP TYPOLOGY

Two problems with the plain segment model:

  1. It beat raw crash counting by only 0.76pp, because n_crashes dominates
     (mean|SHAP| 0.498, three times the next feature). Past crash volume is
     mostly a proxy for traffic exposure, so the model largely re-learns
     "busy places have more crashes" -- true, but not a blackspot insight.

  2. SHAP clustering produced five clusters that were all the same profile at
     different magnitudes, for the same reason: cluster on a SHAP vector
     dominated by one feature and you cluster on that feature.

Both are fixed by putting crash volume in as a POISSON OFFSET instead of a
feature. With log(crashes) as an offset the model must explain KSI *per
crash* -- the residual risk that exposure does not account for. That directly
asks the blackspot question: which segments are more dangerous than their
traffic volume implies?

This yields two complementary scores for the service:
    expected_ksi  -- where the most casualties occur      (budget targeting)
    excess_risk   -- where the road itself is worse than expected (engineering)

A quiet rural bend killing two people in five years can have low expected_ksi
and very high excess_risk. That segment is invisible to crash-count ranking
and is exactly what a blackspot programme exists to find.
"""
import warnings; warnings.filterwarnings("ignore")
import json
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from lightgbm import LGBMRegressor
import shap

RS = 42
seg = pd.read_parquet("segment_features.parquet")   # full, unsorted
print(f"{len(seg):,} segments")

# rebuild the modelling frame (top_drivers/type are outputs, not inputs)
DROP = {"segment_id", "future_ksi", "future_fatal", "rank", "top_drivers",
        "blackspot_type", "predicted_ksi"}
FEATS = [c for c in seg.columns if c not in DROP]

# Exposure proxies go into the offset, NOT the feature set -- otherwise the
# model simply reads crash volume again and the typology collapses.
EXPOSURE = {"n_crashes", "crashes_per_year", "n_ksi", "n_fatal", "n_years_active"}
RISK_FEATS = [c for c in FEATS if c not in EXPOSURE]
print(f"  {len(RISK_FEATS)} risk features (exposure moved to offset): "
      f"{', '.join(RISK_FEATS[:8])}...")

X = seg[RISK_FEATS].apply(pd.to_numeric, errors="coerce").astype(np.float32)
y = seg.future_ksi.values
offset = np.log(seg.n_crashes.values.clip(min=1))     # log-exposure

te = np.load("segment_split_test_idx.npy")          # same split as the SPF stage
tr = np.setdiff1d(np.arange(len(seg)), te)

print("\ntraining excess-risk model (Poisson, log-crashes offset) ...")
m = LGBMRegressor(objective="poisson", n_estimators=600, num_leaves=63,
                  learning_rate=0.05, min_child_samples=40, colsample_bytree=0.7,
                  reg_lambda=1.0, random_state=RS, n_jobs=-1, verbose=-1)
m.fit(X.iloc[tr], y[tr], init_score=offset[tr])
# raw prediction excludes the offset -> KSI per crash, i.e. risk net of exposure
seg["excess_risk"] = np.exp(m.predict(X, raw_score=True))
seg["expected_ksi_offset"] = seg.excess_risk * seg.n_crashes

t = seg.iloc[te]
tot = t.future_ksi.sum()
print("\n" + "=" * 90)
print("RANKING COMPARISON -- held-out segments, future KSI captured")
print("=" * 90)
print(f"{'score':34s} {'top 1%':>9} {'top 5%':>9} {'top 10%':>9} {'top 20%':>9}")
methods = {
    "expected KSI (offset model)": t.expected_ksi_offset.values,
    "expected KSI (plain SPF)": t.predicted_ksi.values,
    "raw crash count": t.n_crashes.values,
    "excess risk (per-crash danger)": t.excess_risk.values,
}
for name, sc in methods.items():
    o = np.argsort(-sc)
    caps = [t.future_ksi.values[o[:int(len(t) * p)]].sum() / tot * 100 for p in [.01, .05, .1, .2]]
    print(f"{name:34s} {caps[0]:8.2f}% {caps[1]:8.2f}% {caps[2]:8.2f}% {caps[3]:8.2f}%")
print("\nexcess risk SHOULD rank poorly here -- this metric rewards volume, and")
print("excess risk deliberately removes it. It answers a different question.")

# ---------- SHAP on the risk model ----------
print("\nSHAP on the excess-risk model ...")
sv = shap.TreeExplainer(m).shap_values(X)
imp = pd.DataFrame({"feature": RISK_FEATS, "mean_abs_shap": np.abs(sv).mean(0)}
                   ).sort_values("mean_abs_shap", ascending=False)
print(imp.head(12).round(4).to_string(index=False))

order = np.argsort(-np.abs(sv), axis=1)[:, :3]
seg["risk_drivers"] = [json.dumps([{"feature": RISK_FEATS[j], "shap": round(float(sv[i, j]), 4)}
                                   for j in order[i]]) for i in range(len(seg))]

# ---------- typology, now on exposure-free SHAP ----------
print("\nclustering on exposure-free SHAP profiles ...")
top = seg.nlargest(20000, "expected_ksi_offset").index
Z = StandardScaler().fit_transform(sv[top])
km = KMeans(n_clusters=5, random_state=RS, n_init=10).fit(Z)
seg["blackspot_type"] = -1
seg.loc[top, "blackspot_type"] = km.labels_

names = {}
print()
for c in range(5):
    idx = seg.loc[top].blackspot_type.values == c
    prof = pd.Series(sv[top][idx].mean(0), index=RISK_FEATS).sort_values(key=abs, ascending=False)
    sub = seg.loc[top][idx]
    top3 = list(prof.head(3).items())
    names[c] = " / ".join(k for k, _ in top3)
    print(f"  type {c}: {idx.sum():,} segments | excess risk {sub.excess_risk.mean():.3f} | "
          f"speed {sub.speed_max.mean():.0f} | urban_rural {sub.mode_urban_or_rural_area.mean():.2f}")
    print(f"    {', '.join(f'{k} {v:+.3f}' for k, v in top3)}")

seg["blackspot_type_name"] = seg.blackspot_type.map(names).fillna("unranked")

out = seg.sort_values("expected_ksi_offset", ascending=False).reset_index(drop=True)
out["rank"] = np.arange(1, len(out) + 1)
cols = ["rank", "segment_id", "lat", "lon", "expected_ksi_offset", "excess_risk",
        "n_crashes", "n_ksi", "n_fatal", "ksi_rate", "blackspot_type",
        "blackspot_type_name", "risk_drivers", "future_ksi"]
out[cols].to_csv("blackspot_final_segments.csv", index=False)
out[cols].head(500).to_json("blackspot_api_top500.json", orient="records", indent=2)
imp.to_csv("blackspot_risk_shap.csv", index=False)

print("\n" + "=" * 90)
print("TOP 10 BY EXCESS RISK (dangerous per crash, not merely busy)")
print("=" * 90)
hi = seg[seg.n_crashes >= 5].nlargest(10, "excess_risk")
print(hi[["segment_id", "lat", "lon", "n_crashes", "n_ksi", "excess_risk",
          "speed_max", "future_ksi"]].round(3).to_string(index=False))
print("\nSaved: blackspot_final_segments.csv, blackspot_api_top500.json, blackspot_risk_shap.csv")
