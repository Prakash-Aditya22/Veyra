"""
BLACKSPOT DETECTION -- 500m road segments with a risk score each.

This is the deliverable the severity model exists to serve. The classifier
answers "how bad is this crash likely to be"; a blackspot system answers
"which 500m stretches of road should be surveyed first", which is what a
highway authority can actually act on.

METHOD
  1. Project lat/long to metres and bin crashes into 500m x 500m segments.
  2. Train the severity model on 2009-2013 ONLY.
  3. For every crash in that period predict P(KSI) and P(Fatal).
  4. Per segment, sum those probabilities -> EXPECTED casualties, the segment's
     risk given its crash circumstances.
  5. Apply Empirical Bayes to combine expected with observed counts.
  6. Rank, then VALIDATE against 2014-2015 -- crashes the scoring never saw.

WHY EMPIRICAL BAYES
  Ranking raw crash counts is the classic blackspot error. A segment with 4
  crashes in five years may be genuinely dangerous or may have had bad luck;
  selecting on the high side guarantees the next period looks better whatever
  you do to the road ("regression to the mean"), which has caused real schemes
  to be credited with improvements they did not produce. EB shrinks each
  segment toward its model-expected value in proportion to how little evidence
  it has, which is the standard correction (Hauer).

WHY THE VALIDATION MATTERS
  Scoring on 2009-2013 and testing on 2014-2015 asks the only question that
  counts: do the segments this flags actually go on to have more serious
  crashes? A blackspot method that cannot beat "rank by past crash count" on
  future data is not earning its complexity.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder
from lightgbm import LGBMClassifier

RS = 42
SEG_M = 500                      # segment size in metres
BUILD_YEARS = [2009, 2010, 2011, 2012, 2013]
VALID_YEARS = [2014, 2015]
M_PER_DEG_LAT = 111_320.0

print("loading ...")
df = pd.read_csv("stats19_2009_2015.csv", low_memory=False)
print(f"  {len(df):,} crashes")

# ---------- 1. project to metres, bin into 500m segments ----------
# Equirectangular about each point's own latitude: 1 deg lat is ~111.32km
# everywhere, 1 deg lon shrinks by cos(lat). Over GB this is well within a
# few metres, far below the 500m bin size.
lat = df["latitude"].values
lon = df["longitude"].values
y_m = lat * M_PER_DEG_LAT
x_m = lon * M_PER_DEG_LAT * np.cos(np.radians(lat))
df["seg_x"] = np.floor(x_m / SEG_M).astype(np.int32)
df["seg_y"] = np.floor(y_m / SEG_M).astype(np.int32)
df["segment_id"] = df["seg_x"].astype(str) + "_" + df["seg_y"].astype(str)
print(f"  {df['segment_id'].nunique():,} distinct {SEG_M}m segments contain at least one crash")

df["is_ksi"] = (df["Accident_Severity"] != "Minor").astype(int)
df["is_fatal"] = (df["Accident_Severity"] == "Fatal").astype(int)

build = df[df.collision_year.isin(BUILD_YEARS)]
valid = df[df.collision_year.isin(VALID_YEARS)]
print(f"  build {len(build):,} crashes ({BUILD_YEARS[0]}-{BUILD_YEARS[-1]})  |  "
      f"validate {len(valid):,} ({VALID_YEARS[0]}-{VALID_YEARS[-1]})")

# ---------- 2-3. severity model, trained on build years only ----------
DROP = {"Accident_Severity", "collision_index", "collision_year", "segment_id",
        "seg_x", "seg_y", "is_ksi", "is_fatal",
        "did_police_officer_attend_scene_of_accident"}
FEATS = [c for c in df.columns if c not in DROP]

# Build straight into a preallocated float32 array. Selecting these columns as
# a DataFrame first would consolidate them into an int64 block (~1.8 GB for
# 1M x 246) before any dtype conversion could help.
X = np.empty((len(df), len(FEATS)), dtype=np.float32)
for i, c in enumerate(FEATS):
    col = df[c]
    if col.dtype == object:
        X[:, i] = LabelEncoder().fit_transform(col.fillna("NA").astype(str))
    else:
        X[:, i] = pd.to_numeric(col, errors="coerce").astype(np.float32)
X[~np.isfinite(X)] = np.nan
print(f"  feature matrix {X.shape} float32 ({X.nbytes/1e9:.2f} GB)")

bi = build.index.values  # positional: df has a clean RangeIndex
print("\ntraining severity models on build years ...")
m_ksi = LGBMClassifier(n_estimators=500, num_leaves=127, learning_rate=0.05,
                       colsample_bytree=0.5, reg_alpha=1.0, reg_lambda=1.0,
                       min_child_samples=40,
                       random_state=RS, n_jobs=-1, verbose=-1).fit(X[bi], df.loc[bi, "is_ksi"])
m_fat = LGBMClassifier(n_estimators=500, num_leaves=127, learning_rate=0.05,
                       colsample_bytree=0.5, reg_alpha=1.0, reg_lambda=1.0,
                       min_child_samples=40,
                       random_state=RS, n_jobs=-1, verbose=-1).fit(X[bi], df.loc[bi, "is_fatal"])
build = build.copy()
build["p_ksi"] = m_ksi.predict_proba(X[bi])[:, 1]
build["p_fatal"] = m_fat.predict_proba(X[bi])[:, 1]
# class_weight is deliberately NOT used here. Balanced weighting distorts
# predict_proba away from true prevalence, and these probabilities are SUMMED
# into expected casualty counts -- so they must be calibrated, not separated.
print(f"  calibration check  KSI: predicted mean {build.p_ksi.mean():.4f} vs actual "
      f"{df.loc[bi,'is_ksi'].mean():.4f}   Fatal: {build.p_fatal.mean():.4f} vs "
      f"{df.loc[bi,'is_fatal'].mean():.4f}")

# ---------- 4. aggregate to segments ----------
seg = build.groupby("segment_id").agg(
    n_crashes=("is_ksi", "size"),
    obs_ksi=("is_ksi", "sum"),
    obs_fatal=("is_fatal", "sum"),
    exp_ksi=("p_ksi", "sum"),
    exp_fatal=("p_fatal", "sum"),
    lat=("latitude", "mean"),
    lon=("longitude", "mean"),
).reset_index()
print(f"\n{len(seg):,} segments scored")

# ---------- 5. Empirical Bayes ----------
# Negative binomial moment estimate of the overdispersion parameter k:
#   Var = mu + mu^2 / k   ->   k = mu^2 / (Var - mu)
mu, var = seg.obs_ksi.mean(), seg.obs_ksi.var()
k = (mu ** 2) / (var - mu) if var > mu else 10.0
# Weight depends on how much evidence a segment has: with few expected
# casualties the estimate leans on the model, with many it leans on what was
# actually observed. This is the shrinkage that guards against ranking a
# segment highly on the strength of one unlucky year.
w = k / (k + seg.exp_ksi)
seg["eb_ksi"] = w * seg.exp_ksi + (1 - w) * seg.obs_ksi
seg["blackspot_score"] = seg["eb_ksi"]
print(f"  EB overdispersion k = {k:.3f}   (mean observed KSI/segment {mu:.3f}, var {var:.3f})")

# ---------- 6. validate on unseen years ----------
vs = valid.groupby("segment_id").agg(future_ksi=("is_ksi", "sum"),
                                     future_fatal=("is_fatal", "sum"),
                                     future_crashes=("is_ksi", "size"))
seg = seg.merge(vs, on="segment_id", how="left").fillna(
    {"future_ksi": 0, "future_fatal": 0, "future_crashes": 0})

total_future_ksi = seg.future_ksi.sum()
total_future_fatal = seg.future_fatal.sum()

print("\n" + "=" * 92)
print(f"VALIDATION -- segments ranked on {BUILD_YEARS[0]}-{BUILD_YEARS[-1]}, "
      f"scored against {VALID_YEARS[0]}-{VALID_YEARS[-1]}")
print("=" * 92)
print(f"{'method':26s} {'top 100':>10} {'top 500':>10} {'top 1000':>10} {'top 5000':>10}   (% of future KSI captured)")

methods = {
    "blackspot score (EB)": seg.blackspot_score,
    "expected KSI (model)": seg.exp_ksi,
    "observed KSI count": seg.obs_ksi,
    "raw crash count": seg.n_crashes,
}
rows = []
for name, score in methods.items():
    order = np.argsort(-score.values)
    caps = []
    for n in [100, 500, 1000, 5000]:
        idx = order[:n]
        caps.append(seg.future_ksi.values[idx].sum() / total_future_ksi * 100)
    rows.append({"method": name, **{f"top{n}": c for n, c in zip([100, 500, 1000, 5000], caps)}})
    print(f"{name:26s} {caps[0]:9.2f}% {caps[1]:9.2f}% {caps[2]:9.2f}% {caps[3]:9.2f}%")

print("\nsame, for future FATAL crashes:")
for name, score in methods.items():
    order = np.argsort(-score.values)
    caps = [seg.future_fatal.values[order[:n]].sum() / total_future_fatal * 100
            for n in [100, 500, 1000, 5000]]
    print(f"{name:26s} {caps[0]:9.2f}% {caps[1]:9.2f}% {caps[2]:9.2f}% {caps[3]:9.2f}%")

# ---------- 7. output ----------
seg = seg.sort_values("blackspot_score", ascending=False).reset_index(drop=True)
seg["rank"] = np.arange(1, len(seg) + 1)
out = seg[["rank", "segment_id", "lat", "lon", "n_crashes", "obs_ksi", "obs_fatal",
           "exp_ksi", "exp_fatal", "blackspot_score", "future_ksi", "future_fatal"]]
out.to_csv("blackspot_segments_ranked.csv", index=False)
out.head(100).to_csv("blackspot_top100.csv", index=False)
pd.DataFrame(rows).to_csv("blackspot_validation.csv", index=False)

print("\n" + "=" * 92)
print("TOP 15 BLACKSPOT SEGMENTS")
print("=" * 92)
print(out.head(15).round(3).to_string(index=False))
print(f"\nSaved: blackspot_segments_ranked.csv ({len(out):,} segments), "
      f"blackspot_top100.csv, blackspot_validation.csv")
