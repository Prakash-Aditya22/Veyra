"""
Build a RECENT STATS19 dataset (2015-2023) for blackspot detection.

WHY RECENT DATA IS FINE HERE
  The 2016 move to injury-based severity reporting (CRASH/COPA) only breaks
  analysis that STRADDLES the boundary -- post-2016 data is internally
  consistent. And that change affected severity LABELS, not crash LOCATIONS,
  which is what blackspot detection runs on. So recent data is usable as long
  as the window sits entirely on one side.

  The rollout was staggered force by force, so rather than guess when it
  settled, this extracts 2015-2023 and PRINTS the severity share per year.
  The window gets chosen from that evidence.

  COVID (2020-2021) collapsed traffic volumes. Crash locations stay valid but
  counts drop, so those years are flagged rather than silently pooled.

LEAKAGE: collision_severity is the target; nine other severity-derived fields
across the three tables are dropped and their absence asserted.
"""
import warnings; warnings.filterwarnings("ignore")
import gc
import os
import numpy as np
import pandas as pd

RAW = "stats19_raw"
YEARS = list(range(2015, 2024))
CHUNK = 500_000
OUT = "stats19_recent.csv"
MAX_LEVELS = 30

TARGET = "collision_severity"
LEAKY = {"casualty_severity", "enhanced_casualty_severity", "casualty_injury_based",
         "casualty_adjusted_severity_serious", "casualty_adjusted_severity_slight",
         "enhanced_severity_collision", "collision_injury_based",
         "collision_adjusted_severity_serious", "collision_adjusted_severity_slight"}
SEV = {1: "Fatal", 2: "Grievous", 3: "Minor"}


def path(t):
    return os.path.join(RAW, f"dft-road-casualty-statistics-{t}-1979-latest-published-year.csv")


def load_years(table):
    print(f"  reading {table} ", end="", flush=True)
    keep = []
    for i, ch in enumerate(pd.read_csv(path(table), chunksize=CHUNK, low_memory=False)):
        keep.append(ch[ch.collision_year.isin(YEARS)])
        if i % 5 == 0:
            print(".", end="", flush=True)
    out = pd.concat(keep, ignore_index=True)
    print(f" {len(out):,} rows")
    del keep; gc.collect()
    return out


def flags(d, key, col, prefix):
    n = d[col].nunique(dropna=True)
    if n > MAX_LEVELS or n < 2:
        return None
    x = pd.crosstab(d[key], d[col])
    x.columns = [f"{prefix}{col}_{c}" for c in x.columns]
    return (x > 0).astype(np.int8)


# ---------- collision ----------
print("collision table:")
coll = load_years("collision")
coll = coll[coll[TARGET].isin(SEV)]
DROPC = {"collision_ref_no", "location_easting_osgr", "location_northing_osgr",
         "local_authority_ons_district", "local_authority_highway",
         "local_authority_highway_current"} | LEAKY
base = coll[[c for c in coll.columns if c not in DROPC]].copy()
base["Accident_Severity"] = base[TARGET].map(SEV)
base = base.drop(columns=[TARGET])

dt = pd.to_datetime(base.date, errors="coerce", dayfirst=True)
base["Hour"] = pd.to_datetime(base.time, format="%H:%M", errors="coerce").dt.hour
base["Month"] = dt.dt.month
base["DayOfYear"] = dt.dt.dayofyear
base = base.drop(columns=["time", "date"])
del coll; gc.collect()

print("\n" + "=" * 74)
print("SEVERITY SHARE BY YEAR -- where did the reporting transition settle?")
print("=" * 74)
pv = (base.groupby("collision_year").Accident_Severity.value_counts(normalize=True)
      .unstack() * 100).round(2)
pv["n_collisions"] = base.groupby("collision_year").size()
print(pv.to_string())
print("\nA jump in 'Grievous' marks a force adopting injury-based reporting.")
print("Pick a window where the share is stable.")

# ---------- vehicle ----------
print("\nvehicle table:")
veh = load_years("vehicle")
veh = veh[[c for c in veh.columns if c not in LEAKY]]
veh = veh[veh.collision_index.isin(set(base.collision_index))]
g = veh.groupby("collision_index")
vf = pd.DataFrame({"v_n_vehicles": g.size().astype(np.int16)})
for c in ["age_of_driver", "age_of_vehicle", "engine_capacity_cc", "driver_imd_decile"]:
    if c in veh.columns:
        s = veh[c].where(veh[c] > 0).groupby(veh.collision_index)
        vf[f"v_{c}_min"] = s.min().astype(np.float32)
        vf[f"v_{c}_max"] = s.max().astype(np.float32)
        vf[f"v_{c}_mean"] = s.mean().astype(np.float32)
for c in ["first_point_of_impact", "vehicle_manoeuvre", "skidding_and_overturning",
          "vehicle_leaving_carriageway", "hit_object_in_carriageway",
          "hit_object_off_carriageway", "junction_location", "vehicle_type",
          "towing_and_articulation", "journey_purpose_of_driver", "sex_of_driver"]:
    if c in veh.columns:
        fl = flags(veh, "collision_index", c, "v_")
        if fl is not None:
            vf = vf.join(fl, how="left")
# motorcycle / HGV / cycle involvement -- drives what intervention is appropriate
if "vehicle_type" in veh.columns:
    vt = veh.groupby("collision_index").vehicle_type
    vf["v_any_motorcycle"] = vt.agg(lambda s: s.between(2, 5).any()).astype(np.int8)
    vf["v_any_cycle"] = vt.agg(lambda s: (s == 1).any()).astype(np.int8)
    vf["v_any_hgv"] = vt.agg(lambda s: s.between(19, 21).any()).astype(np.int8)
print(f"  {vf.shape[1]} vehicle features")
del veh, g; gc.collect()

# ---------- casualty ----------
print("\ncasualty table:")
cas = load_years("casualty")
print(f"  dropping: {sorted(c for c in cas.columns if c in LEAKY)}")
cas = cas[[c for c in cas.columns if c not in LEAKY]]
cas = cas[cas.collision_index.isin(set(base.collision_index))]
g = cas.groupby("collision_index")
cf = pd.DataFrame({"k_n_casualties": g.size().astype(np.int16)})
s = cas.age_of_casualty.where(cas.age_of_casualty > 0).groupby(cas.collision_index)
cf["k_age_min"], cf["k_age_max"], cf["k_age_mean"] = (s.min().astype(np.float32),
                                                      s.max().astype(np.float32),
                                                      s.mean().astype(np.float32))
cf["k_any_child"] = (cas.age_of_casualty.where(cas.age_of_casualty > 0) < 16
                     ).groupby(cas.collision_index).max().astype(np.float32)
cf["k_any_elderly"] = (cas.age_of_casualty.where(cas.age_of_casualty > 0) >= 70
                       ).groupby(cas.collision_index).max().astype(np.float32)
# vulnerable road users: casualty_class 3 = pedestrian
if "casualty_class" in cas.columns:
    cf["k_any_pedestrian"] = g.casualty_class.agg(lambda s: (s == 3).any()).astype(np.int8)
    cf["k_n_pedestrians"] = g.casualty_class.agg(lambda s: (s == 3).sum()).astype(np.int16)
for c in ["casualty_class", "casualty_type", "pedestrian_location", "pedestrian_movement",
          "car_passenger", "sex_of_casualty"]:
    if c in cas.columns:
        fl = flags(cas, "collision_index", c, "k_")
        if fl is not None:
            cf = cf.join(fl, how="left")
if "casualty_imd_decile" in cas.columns:
    cf["k_imd_min"] = (cas.casualty_imd_decile.where(cas.casualty_imd_decile > 0)
                       .groupby(cas.collision_index).min().astype(np.float32))
print(f"  {cf.shape[1]} casualty features")
del cas, g; gc.collect()

# ---------- merge ----------
out = base.set_index("collision_index").join(vf, how="left").join(cf, how="left")
leaked = [c for c in out.columns if any(l in c for l in LEAKY)] + \
         ([TARGET] if TARGET in out.columns else [])
assert not leaked, f"LEAKAGE: {leaked}"
print(f"\n{out.shape[0]:,} collisions x {out.shape[1]} columns")
print(f"  vehicle data {out.v_n_vehicles.notna().mean()*100:.1f}%  |  "
      f"casualty data {out.k_n_casualties.notna().mean()*100:.1f}%")
out.reset_index().to_csv(OUT, index=False)
print(f"wrote {OUT} ({os.path.getsize(OUT)/1e6:.0f} MB)")
