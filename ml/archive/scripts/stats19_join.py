"""
Enrich Road_Accident_Data_Cleaned.csv with the official STATS19 vehicle and
casualty tables.

WHY: the existing 20 columns describe circumstances (weather, road, junction,
lighting). Diagnostics measured a hard ceiling from those -- the highest-risk
identifiable segment is only ~10% fatal, which arithmetically bounds Fatal
precision no matter which model is used. What is missing is the MECHANICS of
injury: what was struck and where, who was involved, whether a pedestrian was
hit. Those live in the vehicle and casualty tables.

JOIN STRATEGY (two-pass, recovering 100% of rows):
  1. collision_index  -- matches Original_Accident_Index directly for the 64%
     of rows whose index survived intact.
  2. composite key (date, time, latitude, longitude) -- recovers the 36% whose
     index was mangled into scientific notation ("2.01E+12") by a spreadsheet.
     Verified 99.994% unique on this file (307,955 distinct of 307,973 rows).

LEAKAGE (the part to get right):
  Accident_Severity is derived from casualty_severity -- it is the maximum
  severity across everyone hurt in the collision. Importing any severity
  field would hand the model the answer. There are TEN such fields across the
  two tables, not one; all are dropped explicitly in LEAKY_COLS below and the
  script asserts none survive into the output.

TWO FEATURE SETS are produced, because they answer different questions:
  A. ACTIONABLE   -- environment, road, vehicle. Things a highway authority
     can change. Appropriate for blackspot / intervention work.
  B. EXPLANATORY  -- adds casualty demographics. Predicts severity better,
     but you cannot redesign a junction to change who walks through it.
  Reporting both is more informative than either alone.

Codes are NOT decoded here. DfT publishes these tables numerically coded
(weather_conditions = 1, not "Fine no high winds"); models are indifferent,
and hardcoding code meanings without the data guide risks silent errors. The
guide is at:
  https://www.gov.uk/government/statistical-data-sets/road-safety-open-data
"""

import warnings; warnings.filterwarnings("ignore")
import os
import numpy as np
import pandas as pd

RAW = "stats19_raw"
BASE_FILE = "Road_Accident_Data_Cleaned.csv"
OUT_ACTIONABLE = "accidents_enriched_actionable.csv"
OUT_EXPLANATORY = "accidents_enriched_explanatory.csv"
YEARS = [2009, 2010]
CHUNK = 500_000          # the raw files are 1-2GB; never load one whole

def path(t):
    return os.path.join(RAW, f"dft-road-casualty-statistics-{t}-1979-latest-published-year.csv")

# Every outcome-derived field across both tables. Dropping only
# casualty_severity would not be enough -- the "adjusted" and "enhanced"
# variants encode the same information.
LEAKY_COLS = {
    "casualty_severity", "enhanced_casualty_severity", "casualty_injury_based",
    "casualty_adjusted_severity_serious", "casualty_adjusted_severity_slight",
    "collision_severity", "enhanced_severity_collision", "collision_injury_based",
    "collision_adjusted_severity_serious", "collision_adjusted_severity_slight",
}


def load_years(table, usecols=None):
    """Stream a multi-GB CSV and keep only the years of interest."""
    print(f"  reading {table} in chunks ...", end="", flush=True)
    keep = []
    for i, ch in enumerate(pd.read_csv(path(table), chunksize=CHUNK, low_memory=False,
                                        usecols=usecols)):
        keep.append(ch[ch["collision_year"].isin(YEARS)])
        if i % 5 == 0:
            print(".", end="", flush=True)
    out = pd.concat(keep, ignore_index=True)
    print(f" {len(out):,} rows for {YEARS}")
    return out


# ============================================================
# 1. BASE FILE + JOIN KEYS
# ============================================================
print("loading base file ...")
base = pd.read_csv(BASE_FILE, low_memory=False)
base["_row"] = np.arange(len(base))

oai = base["Original_Accident_Index"].astype(str)
base["_index_key"] = np.where(oai.str.contains("E+", regex=False), np.nan, oai)

def composite(d, date_col, time_col, lat_col, lon_col, dayfirst):
    dt = pd.to_datetime(d[date_col], errors="coerce", dayfirst=dayfirst).dt.strftime("%Y-%m-%d")
    tm = d[time_col].astype(str).str.strip().str[:5]
    return (dt + "|" + tm + "|" + d[lat_col].round(5).astype(str)
            + "|" + d[lon_col].round(5).astype(str))

base["_comp_key"] = composite(base, "Accident_Date", "Time", "Latitude", "Longitude", dayfirst=False)
print(f"  {base['_index_key'].notna().sum():,} rows have an intact index; "
      f"{base['_index_key'].isna().sum():,} need the composite key")

# ============================================================
# 2. COLLISION TABLE -> build the crosswalk from composite key to
#    collision_index, so corrupted rows can still be joined
# ============================================================
print("\ncollision table:")
coll = load_years("collision")
coll["_comp_key"] = composite(coll, "date", "time", "latitude", "longitude", dayfirst=True)

xwalk = coll.drop_duplicates("_comp_key").set_index("_comp_key")["collision_index"]
recovered = base.loc[base["_index_key"].isna(), "_comp_key"].map(xwalk)
base.loc[base["_index_key"].isna(), "_index_key"] = recovered.values
print(f"  recovered {recovered.notna().sum():,} of {recovered.isna().sum() + recovered.notna().sum():,} "
      f"corrupted-index rows via composite key")
print(f"  total joinable: {base['_index_key'].notna().sum():,} / {len(base):,} "
      f"({base['_index_key'].notna().mean()*100:.1f}%)")

# extra collision-level columns the cleaned file never had
COLL_EXTRA = ["first_road_class", "first_road_number", "second_road_class",
              "road_type", "pedestrian_crossing", "special_conditions_at_site",
              "did_police_officer_attend_scene_of_accident", "trunk_road_flag",
              "lsoa_of_accident_location", "junction_control", "junction_detail"]
COLL_EXTRA = [c for c in COLL_EXTRA if c in coll.columns and c not in LEAKY_COLS]
coll_feat = coll.drop_duplicates("collision_index").set_index("collision_index")[COLL_EXTRA]
coll_feat = coll_feat.add_prefix("c_")
del coll

# ============================================================
# 3. VEHICLE TABLE -> aggregate to one row per collision
# ============================================================
print("\nvehicle table:")
veh = load_years("vehicle")
veh = veh[[c for c in veh.columns if c not in LEAKY_COLS]]

# Codes are treated as opaque labels: presence/absence per code value, plus
# order statistics on the genuinely numeric fields. No code semantics assumed.
g = veh.groupby("collision_index")
vf = pd.DataFrame(index=g.size().index)
vf["v_n_vehicle_rows"] = g.size()

for col in ["age_of_driver", "age_of_vehicle", "engine_capacity_cc"]:
    if col in veh.columns:
        s = veh[col].where(veh[col] > 0)          # STATS19 uses -1 / 0 for missing
        gg = s.groupby(veh["collision_index"])
        vf[f"v_{col}_min"] = gg.min()
        vf[f"v_{col}_max"] = gg.max()
        vf[f"v_{col}_mean"] = gg.mean()

# "was any vehicle in this collision coded X" for the mechanically informative fields
for col in ["first_point_of_impact", "vehicle_manoeuvre", "skidding_and_overturning",
            "vehicle_leaving_carriageway", "hit_object_in_carriageway",
            "hit_object_off_carriageway", "junction_location", "vehicle_type",
            "towing_and_articulation", "journey_purpose_of_driver"]:
    if col not in veh.columns:
        continue
    d = pd.crosstab(veh["collision_index"], veh[col])
    d.columns = [f"v_{col}_{c}" for c in d.columns]
    vf = vf.join((d > 0).astype(int), how="left")

for col in ["driver_imd_decile", "sex_of_driver"]:
    if col in veh.columns:
        s = veh[col].where(veh[col] > 0)
        vf[f"v_{col}_min"] = s.groupby(veh["collision_index"]).min()

print(f"  {vf.shape[1]} vehicle-derived features")
del veh

# ============================================================
# 4. CASUALTY TABLE -> aggregate, with every severity field excluded
# ============================================================
print("\ncasualty table:")
cas = load_years("casualty")
dropped = [c for c in cas.columns if c in LEAKY_COLS]
print(f"  dropping outcome-derived columns: {dropped}")
cas = cas[[c for c in cas.columns if c not in LEAKY_COLS]]

g = cas.groupby("collision_index")
cf = pd.DataFrame(index=g.size().index)
cf["k_n_casualty_rows"] = g.size()

s = cas["age_of_casualty"].where(cas["age_of_casualty"] > 0)
gg = s.groupby(cas["collision_index"])
cf["k_age_min"], cf["k_age_max"], cf["k_age_mean"] = gg.min(), gg.max(), gg.mean()
cf["k_any_child"] = (s < 16).groupby(cas["collision_index"]).max().astype(float)
cf["k_any_elderly"] = (s >= 70).groupby(cas["collision_index"]).max().astype(float)

for col in ["casualty_class", "casualty_type", "pedestrian_location",
            "pedestrian_movement", "car_passenger", "bus_or_coach_passenger"]:
    if col not in cas.columns:
        continue
    d = pd.crosstab(cas["collision_index"], cas[col])
    d.columns = [f"k_{col}_{c}" for c in d.columns]
    cf = cf.join((d > 0).astype(int), how="left")

if "casualty_imd_decile" in cas.columns:
    s = cas["casualty_imd_decile"].where(cas["casualty_imd_decile"] > 0)
    cf["k_imd_min"] = s.groupby(cas["collision_index"]).min()

print(f"  {cf.shape[1]} casualty-derived features")
del cas

# ============================================================
# 5. MERGE + WRITE THE TWO FEATURE SETS
# ============================================================
print("\nmerging ...")
merged = base.set_index("_index_key")
actionable = merged.join(coll_feat, how="left").join(vf, how="left")
explanatory = actionable.join(cf, how="left")

for name, d in [("actionable", actionable), ("explanatory", explanatory)]:
    leaked = [c for c in d.columns if any(l in c for l in LEAKY_COLS)]
    assert not leaked, f"LEAKAGE: {leaked}"          # fail loudly rather than ship a bad file
    matched = d["v_n_vehicle_rows"].notna().mean() * 100
    print(f"  {name:12s} {d.shape[1]} columns, vehicle data matched for {matched:.1f}% of rows")

actionable.reset_index().drop(columns=["_comp_key", "_row"]).to_csv(OUT_ACTIONABLE, index=False)
explanatory.reset_index().drop(columns=["_comp_key", "_row"]).to_csv(OUT_EXPLANATORY, index=False)
print(f"\nwrote {OUT_ACTIONABLE} and {OUT_EXPLANATORY}")
print("\nNext: rerun the model comparison on each feature set and check whether the")
print("~10% risk-concentration ceiling has actually moved. That is the test of")
print("whether enrichment helped -- not the macro-F1 number on its own.")
