"""
ROAD-SEGMENT BLACKSPOTS -- a road cut into 500m pieces ALONG ITS LENGTH.

This replaces the 500m x 500m grid. A grid bin is a square patch of the map:
it can hold two different roads at once, it ignores the direction the road
runs, and "cell -13_11468" means nothing to a highway engineer. What the
project actually needs is CHAINAGE -- distance measured along the road --
so a blackspot can be stated as "A38, km 128.4-128.9".

ISOLATING ONE ROAD
  first_road_class + first_road_number is a true identifier: class 3,
  number 38 is the A38 and nothing else. No string matching, no "AVE" vs
  "AVENUE". (class 1=Motorway, 2=A(M), 3=A, 4=B, 5=C, 6=Unclassified.)

DERIVING CHAINAGE WITHOUT ROAD GEOMETRY
  The proper way is to project each crash onto the road's polyline from
  OpenStreetMap. Without that dependency, the crashes themselves trace the
  road, so chainage is recovered from their own geometry:

    1. project lat/long to metres
    2. build a k-nearest-neighbour graph, dropping edges longer than
       MAX_EDGE_M so distinct stretches are not bridged across open country
    3. take each connected component separately (a road is often recorded in
       disconnected pieces)
    4. find the component's two ends by double sweep -- farthest node from an
       arbitrary start, then farthest from that: the graph diameter
    5. shortest-path distance from one end = chainage, which follows the
       road's curve rather than cutting across it
    6. bin chainage into 500m pieces

  This approximates the centreline from crash positions rather than surveying
  it, so it is honest to call it an approximation. It follows curves, which a
  straight-line projection (PCA) would not.

SCORING is prospective, exactly as before: features from 2019-2021, target is
2022-2023 KSI, and segments are split train/test so scores are measured on
pieces of road the model never saw.
"""
import warnings; warnings.filterwarnings("ignore")
import json
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra, minimum_spanning_tree
from scipy.spatial.distance import pdist, squareform
from sklearn.neighbors import NearestNeighbors
from sklearn.model_selection import train_test_split
from lightgbm import LGBMRegressor

RS = 42
SEG_M = 500                # segment length along the road
K_NN = 6                   # neighbours per crash when building the graph
MAX_DENSE  = 4000          # above this, kNN graph instead of a full distance matrix
MIN_CRASHES = 60           # roads with fewer crashes cannot support chainage
STRETCH_GAP_M = 10_000     # a gap this large means a separate stretch of road
BUILD, FUTURE = [2019, 2020, 2021], [2022, 2023]
M_PER_DEG_LAT = 111_320.0
CLS = {1: "M", 2: "A(M)", 3: "A", 4: "B", 5: "C", 6: "U"}

print("loading ...")
df = pd.read_csv("stats19_recent.csv", low_memory=False)
df = df[df.collision_year.isin(BUILD + FUTURE)]
df = df[np.isfinite(df.latitude) & np.isfinite(df.longitude)]
df = df[(df.first_road_class.isin(CLS)) & (df.first_road_number > 0)].reset_index(drop=True)
df["road_id"] = df.first_road_class.map(CLS) + df.first_road_number.astype(int).astype(str)
df["is_ksi"] = (df.Accident_Severity != "Minor").astype(int)
df["is_fatal"] = (df.Accident_Severity == "Fatal").astype(int)
print(f"  {len(df):,} crashes on numbered roads | {df.road_id.nunique():,} distinct roads")

counts = df.road_id.value_counts()
roads = counts[counts >= MIN_CRASHES].index.tolist()
print(f"  {len(roads):,} roads with >= {MIN_CRASHES} crashes -> "
      f"{counts[roads].sum():,} crashes covered")


def chainage(lat, lon):
    """Distance along the road for each point, in metres.

    A plain k-nearest-neighbour graph fragments badly: wherever crashes are
    more than a couple of kilometres apart the graph disconnects, and chainage
    then restarts at zero on every fragment. The A23 broke into 52 runs that
    way, giving 52 separate stretches all labelled "km 0.0".

    A MINIMUM SPANNING TREE over the road's crashes is connected by
    construction, and because it always joins nearest points it traces the
    road rather than cutting across it. Geodesic distance along that tree,
    measured from one end, is a continuous chainage for the whole road.
    """
    n = len(lat)
    y = lat * M_PER_DEG_LAT
    x = lon * M_PER_DEG_LAT * np.cos(np.radians(lat))
    P = np.column_stack([x, y])
    if n < 3:
        return np.zeros(n), np.zeros(n, dtype=int)

    # A road NUMBER is not a single stretch of road. Crashes tagged "A503"
    # appear from London to Scotland (543km end to end) although the A503 is a
    # 10km London road -- numbers are reused, or misrecorded. Connecting those
    # gave 576km of chainage on a 10km road. So split into geographically
    # separate stretches first, and measure chainage within each.
    kk = min(10, n - 1)
    nn0 = NearestNeighbors(n_neighbors=kk + 1).fit(P)
    d0_, i0_ = nn0.kneighbors(P)
    rr = np.repeat(np.arange(n), kk)
    ww = d0_[:, 1:].ravel()
    keep0 = ww <= STRETCH_GAP_M
    G0 = coo_matrix((ww[keep0], (rr[keep0], i0_[:, 1:].ravel()[keep0])), shape=(n, n))
    G0 = G0.maximum(G0.T)
    _, stretch = connected_components(G0, directed=False)

    ch_all = np.zeros(n)
    for st in np.unique(stretch):
        sel = np.where(stretch == st)[0]
        if len(sel) < 3:
            continue
        ch_all[sel] = _chain_one(P[sel])
    return ch_all, stretch


def _chain_one(P):
    """Continuous chainage within one connected stretch, via its MST."""
    n = len(P)
    if n <= MAX_DENSE:
        mst = minimum_spanning_tree(squareform(pdist(P)))   # exact
    else:
        # busiest roads: MST over a kNN graph, stitching any components first
        k = min(15, n - 1)
        nn = NearestNeighbors(n_neighbors=k + 1).fit(P)
        dist, idx = nn.kneighbors(P)
        rows = np.repeat(np.arange(n), k)
        G = coo_matrix((dist[:, 1:].ravel(), (rows, idx[:, 1:].ravel())), shape=(n, n))
        G = G.maximum(G.T)
        ncomp, comp = connected_components(G, directed=False)
        if ncomp > 1:
            er, ec, ew = [], [], []
            reps = [np.where(comp == c)[0] for c in range(ncomp)]
            for c in range(1, ncomp):
                a, bb = reps[c - 1], reps[c]
                d = np.linalg.norm(P[a][:, None, :] - P[bb][None, :, :], axis=2)
                i, j = np.unravel_index(np.argmin(d), d.shape)
                er.append(a[i]); ec.append(bb[j]); ew.append(d[i, j])
            G = G.tocoo()
            G = coo_matrix((np.r_[G.data, ew], (np.r_[G.row, er], np.r_[G.col, ec])),
                           shape=(n, n)).maximum(
                 coo_matrix((np.r_[G.data, ew], (np.r_[G.col, ec], np.r_[G.row, er])),
                            shape=(n, n)))
        mst = minimum_spanning_tree(G)

    mst = mst.maximum(mst.T)                      # undirected
    ncomp, comp = connected_components(mst, directed=False)
    ch = np.zeros(n)
    for c in range(ncomp):
        m = np.where(comp == c)[0]
        if len(m) < 2:
            continue
        sub = mst.tocsr()[m][:, m]
        # double sweep: farthest node from an arbitrary start is one end of
        # the stretch, farthest from THAT is the other -- the tree's diameter
        d0 = dijkstra(sub, indices=0); d0[~np.isfinite(d0)] = -1
        a = int(np.argmax(d0))
        da = dijkstra(sub, indices=a); da[~np.isfinite(da)] = 0
        ch[m] = da
    return ch


print("\ncomputing chainage per road ...")
parts = []
for i, rid in enumerate(roads, 1):
    r = df[df.road_id == rid]
    ch, comp = chainage(r.latitude.values, r.longitude.values)
    parts.append(pd.DataFrame({
        "idx": r.index.values, "road_id": rid, "chainage_m": ch, "run": comp}))
    if i % 100 == 0:
        print(f"  {i}/{len(roads)} roads")
ch_df = pd.concat(parts).set_index("idx")
df = df.join(ch_df[["road_id", "chainage_m", "run"]].rename(
    columns={"road_id": "_rid"}), how="inner")
df["seg_km"] = np.floor(df.chainage_m / SEG_M) * SEG_M / 1000
df["segment_id"] = (df.road_id + "_run" + df.run.astype(str)
                    + "_km" + df.seg_km.round(1).astype(str))
print(f"  {df.segment_id.nunique():,} road segments of {SEG_M}m")

b = df[df.collision_year.isin(BUILD)]
f = df[df.collision_year.isin(FUTURE)]

g = b.groupby("segment_id")
seg = pd.DataFrame({
    "road_id": g.road_id.first(), "run": g.run.first(), "km_from": g.seg_km.first(),
    "n_crashes": g.size(), "n_ksi": g.is_ksi.sum(), "n_fatal": g.is_fatal.sum(),
    "lat": g.latitude.mean(), "lon": g.longitude.mean(),
    "lat_min": g.latitude.min(), "lat_max": g.latitude.max(),
    "lon_min": g.longitude.min(), "lon_max": g.longitude.max(),
    "speed_max": g.speed_limit.max(), "speed_mean": g.speed_limit.mean(),
    "n_veh_mean": g.number_of_vehicles.mean(),
    "n_cas_mean": g.number_of_casualties.mean(),
    "pct_night": g.Hour.agg(lambda s: ((s >= 22) | (s <= 5)).mean()),
    "pct_junction": g.junction_detail.agg(lambda s: (s != 0).mean()),
    "n_years": g.collision_year.nunique(),
}).reset_index()
for c in ["road_type", "urban_or_rural_area", "light_conditions", "junction_detail"]:
    if c in b.columns:
        seg[f"mode_{c}"] = g[c].agg(lambda s: s.mode().iloc[0] if len(s.mode()) else np.nan).values
seg["crashes_per_year"] = seg.n_crashes / len(BUILD)
seg["ksi_rate"] = seg.n_ksi / seg.n_crashes

fut = f.groupby("segment_id").agg(future_ksi=("is_ksi", "sum"),
                                  future_fatal=("is_fatal", "sum"),
                                  future_crashes=("is_ksi", "size")).reset_index()
seg = seg.merge(fut, on="segment_id", how="left").fillna(
    {"future_ksi": 0, "future_fatal": 0, "future_crashes": 0})
print(f"  {len(seg):,} segments carry crashes in {BUILD[0]}-{BUILD[-1]}")

DROPM = {"segment_id", "road_id", "future_ksi", "future_fatal", "future_crashes"}
MF = [c for c in seg.columns if c not in DROPM]
X = seg[MF].apply(pd.to_numeric, errors="coerce").astype(np.float32)
tr, te = train_test_split(np.arange(len(seg)), test_size=0.3, random_state=RS)

print("\ntraining segment model (Poisson) ...")
m = LGBMRegressor(objective="poisson", n_estimators=500, num_leaves=63, learning_rate=0.05,
                  min_child_samples=30, colsample_bytree=0.7, reg_lambda=1.0,
                  random_state=RS, n_jobs=-1, verbose=-1).fit(X.iloc[tr], seg.future_ksi.values[tr])
seg["blackspot_score"] = m.predict(X)

t = seg.iloc[te]
tot = t.future_ksi.sum()
print("\n" + "=" * 84)
print(f"VALIDATION -- held-out road segments, predicting {FUTURE[0]}-{FUTURE[1]} KSI")
print("=" * 84)
print(f"{'score':26s} {'top 1%':>9} {'top 5%':>9} {'top 10%':>9} {'top 20%':>9}")
for name, sc in {"blackspot score (model)": t.blackspot_score.values,
                 "past crash count": t.n_crashes.values,
                 "past KSI count": t.n_ksi.values}.items():
    o = np.argsort(-sc)
    caps = [t.future_ksi.values[o[:int(len(t)*p)]].sum()/tot*100 for p in [.01, .05, .1, .2]]
    print(f"{name:26s} {caps[0]:8.2f}% {caps[1]:8.2f}% {caps[2]:8.2f}% {caps[3]:8.2f}%")

out = seg.sort_values("blackspot_score", ascending=False).reset_index(drop=True)
out["rank"] = np.arange(1, len(out) + 1)
out["km_to"] = out.km_from + SEG_M / 1000
out["location"] = (out.road_id + " km " + out.km_from.round(1).astype(str)
                   + "-" + out.km_to.round(1).astype(str)
                   + np.where(out.run > 0, " (seg " + out.run.astype(int).astype(str) + ")", ""))
cols = ["rank", "segment_id", "location", "road_id", "km_from", "km_to", "lat", "lon",
        "blackspot_score", "n_crashes", "n_ksi", "n_fatal", "ksi_rate", "crashes_per_year",
        "speed_max", "pct_night", "pct_junction", "future_ksi", "future_fatal"]
out[cols].to_csv("road_segments_ranked.csv", index=False)
out[cols].head(500).to_json("road_segments_top500.json", orient="records", indent=2)

print("\n" + "=" * 84)
print("TOP 20 BLACKSPOT SEGMENTS")
print("=" * 84)
print(out[["rank", "location", "lat", "lon", "blackspot_score", "n_crashes",
           "n_ksi", "speed_max", "future_ksi"]].head(20).round(3).to_string(index=False))

print("\nworst segment on each of the 10 busiest roads:")
top_roads = seg.groupby("road_id").n_crashes.sum().nlargest(10).index
w = out[out.road_id.isin(top_roads)].groupby("road_id").head(1).sort_values("blackspot_score", ascending=False)
print(w[["location", "lat", "lon", "blackspot_score", "n_crashes", "n_ksi",
         "future_ksi"]].round(3).to_string(index=False))

json.dump({"segment_length_m": SEG_M, "n_roads": len(roads), "n_segments": int(len(seg)),
           "build_years": BUILD, "future_years": FUTURE,
           "method": "kNN-graph geodesic chainage along road, binned to 500m"},
          open("road_segments_meta.json", "w"), indent=2)
print("\nSaved: road_segments_ranked.csv, road_segments_top500.json, road_segments_meta.json")
