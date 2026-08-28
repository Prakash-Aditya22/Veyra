"""
Build the modelling dataset directly from the three STATS19 tables.

WHY REBUILD RATHER THAN EXTEND THE EARLIER JOIN:
Road_Accident_Data_Cleaned.csv only covers 2009-2010, so there is no base to
join 2011-2015 onto. Using the official collision table as the base instead
removes three problems at once:
  * no composite-key matching, so no 8.5% row loss
  * no corrupted Original_Accident_Index (a spreadsheet had mangled 36% of
    them into scientific notation)
  * one consistent coding scheme across every year

YEAR RANGE -- 2009 to 2015, and the reason matters:
From November 2016 police forces began moving to injury-based severity
reporting (CRASH and COPA). Severity stopped being an officer's judgement and
became automatic assignment from a recorded injury list, which roughly DOUBLED
reported serious casualties. DfT states pre- and post-change data are not
directly comparable. The rollout was staggered force by force, and police_force
is a model feature -- so pooling across the transition would let the model learn
which reporting system a force used rather than what makes crashes severe.
2009-2015 sits entirely before that, so the target means one thing throughout.
It also predates COVID, which collapsed traffic volumes in 2020-21.

LEAKAGE: collision_severity is the target. Nine other fields across the three
tables are derived from severity (the 'adjusted' and 'enhanced' variants encode
the same information). All are dropped and their absence is asserted.
"""
import warnings; warnings.filterwarnings("ignore")
import gc
import os
import numpy as np
import pandas as pd

RAW = "stats19_raw"
YEARS = list(range(2009, 2016))          # 2009..2015 inclusive
CHUNK = 500_000
OUT = "stats19_2009_2015.csv"
MAX_LEVELS_FOR_FLAGS = 30                # skip crosstabs on very high-cardinality codes

TARGET = "collision_severity"
LEAKY = {
    "casualty_severity", "enhanced_casualty_severity", "casualty_injury_based",
    "casualty_adjusted_severity_serious", "casualty_adjusted_severity_slight",
    "enhanced_severity_collision", "collision_injury_based",
    "collision_adjusted_severity_serious", "collision_adjusted_severity_slight",
}
SEVERITY_MAP = {1: "Fatal", 2: "Grievous", 3: "Minor"}   # STATS19: 1=Fatal 2=Serious 3=Slight


def path(t):
    return os.path.join(RAW, f"dft-road-casualty-statistics-{t}-1979-latest-published-year.csv")


def load_years(table):
    print(f"  reading {table} ", end="", flush=True)
    keep = []
    for i, ch in enumerate(pd.read_csv(path(table), chunksize=CHUNK, low_memory=False)):
        keep.append(ch[ch["collision_year"].isin(YEARS)])
        if i % 5 == 0:
            print(".", end="", flush=True)
    out = pd.concat(keep, ignore_index=True)
    print(f" {len(out):,} rows")
    del keep; gc.collect()
    return out


def presence_flags(df_, key, col, prefix):
    """One 0/1 column per code value: 'was any row in this collision coded X'.
    Code semantics are deliberately not assumed -- DfT publishes these
    numerically and guessing meanings without the data guide fails silently."""
    n = df_[col].nunique(dropna=True)
    if n > MAX_LEVELS_FOR_FLAGS or n < 2:
        return None
    d = pd.crosstab(df_[key], df_[col])
    d.columns = [f"{prefix}{col}_{c}" for c in d.columns]
    return (d > 0).astype(np.int8)


# ============================================================
# 1. COLLISION TABLE -- the base
# ============================================================
print("collision table:")
coll = load_years("collision")
coll = coll[coll[TARGET].isin(SEVERITY_MAP)]
print(f"  {len(coll):,} collisions with a valid severity")

DROP_COLL = {"collision_ref_no", "location_easting_osgr", "location_northing_osgr",
             "lsoa_of_accident_location", "local_authority_ons_district",
             "local_authority_highway", "local_authority_highway_current"} | LEAKY
base = coll[[c for c in coll.columns if c not in DROP_COLL]].copy()

base["Accident_Severity"] = base[TARGET].map(SEVERITY_MAP)
base = base.drop(columns=[TARGET])
base["Hour"] = pd.to_datetime(base["time"], format="%H:%M", errors="coerce").dt.hour
_d = pd.to_datetime(base["date"], errors="coerce", dayfirst=True)
base["Month"] = _d.dt.month
base["DayOfYear"] = _d.dt.dayofyear
base = base.drop(columns=["time", "date"])
print("  severity distribution:")
print((base["Accident_Severity"].value_counts(normalize=True) * 100).round(2).to_string())
del coll; gc.collect()

# ============================================================
# 2. VEHICLE TABLE -> one row per collision
# ============================================================
print("\nvehicle table:")
veh = load_years("vehicle")
veh = veh[[c for c in veh.columns if c not in LEAKY]]
veh = veh[veh["collision_index"].isin(set(base["collision_index"]))]
print(f"  {len(veh):,} vehicle rows in scope")

g = veh.groupby("collision_index")
vf = pd.DataFrame(index=g.size().index)
vf["v_n_vehicles"] = g.size().astype(np.int16)

for col in ["age_of_driver", "age_of_vehicle", "engine_capacity_cc", "driver_imd_decile"]:
    if col in veh.columns:
        s = veh[col].where(veh[col] > 0)          # STATS19 encodes missing as -1/0
        gg = s.groupby(veh["collision_index"])
        vf[f"v_{col}_min"] = gg.min().astype(np.float32)
        vf[f"v_{col}_max"] = gg.max().astype(np.float32)
        vf[f"v_{col}_mean"] = gg.mean().astype(np.float32)

for col in ["first_point_of_impact", "vehicle_manoeuvre", "skidding_and_overturning",
            "vehicle_leaving_carriageway", "hit_object_in_carriageway",
            "hit_object_off_carriageway", "junction_location", "vehicle_type",
            "towing_and_articulation", "journey_purpose_of_driver", "sex_of_driver",
            "vehicle_left_hand_drive", "propulsion_code"]:
    if col in veh.columns:
        f = presence_flags(veh, "collision_index", col, "v_")
        if f is not None:
            vf = vf.join(f, how="left")

print(f"  {vf.shape[1]} vehicle features")
del veh, g; gc.collect()

# ============================================================
# 3. CASUALTY TABLE -> one row per collision (severity fields excluded)
# ============================================================
print("\ncasualty table:")
cas = load_years("casualty")
dropped = sorted(c for c in cas.columns if c in LEAKY)
print(f"  dropping outcome-derived: {dropped}")
cas = cas[[c for c in cas.columns if c not in LEAKY]]
cas = cas[cas["collision_index"].isin(set(base["collision_index"]))]
print(f"  {len(cas):,} casualty rows in scope")

g = cas.groupby("collision_index")
cf = pd.DataFrame(index=g.size().index)
cf["k_n_casualties"] = g.size().astype(np.int16)

s = cas["age_of_casualty"].where(cas["age_of_casualty"] > 0)
gg = s.groupby(cas["collision_index"])
cf["k_age_min"] = gg.min().astype(np.float32)
cf["k_age_max"] = gg.max().astype(np.float32)
cf["k_age_mean"] = gg.mean().astype(np.float32)
cf["k_any_child"] = (s < 16).groupby(cas["collision_index"]).max().astype(np.float32)
cf["k_any_elderly"] = (s >= 70).groupby(cas["collision_index"]).max().astype(np.float32)
if "casualty_imd_decile" in cas.columns:
    si = cas["casualty_imd_decile"].where(cas["casualty_imd_decile"] > 0)
    cf["k_imd_min"] = si.groupby(cas["collision_index"]).min().astype(np.float32)

for col in ["casualty_class", "casualty_type", "pedestrian_location",
            "pedestrian_movement", "car_passenger", "bus_or_coach_passenger",
            "sex_of_casualty", "age_band_of_casualty"]:
    if col in cas.columns:
        f = presence_flags(cas, "collision_index", col, "k_")
        if f is not None:
            cf = cf.join(f, how="left")

print(f"  {cf.shape[1]} casualty features")
del cas, g; gc.collect()

# ============================================================
# 4. MERGE + VALIDATE
# ============================================================
print("\nmerging ...")
out = base.set_index("collision_index").join(vf, how="left").join(cf, how="left")

leaked = [c for c in out.columns if any(l in c for l in LEAKY) or c == TARGET]
assert not leaked, f"LEAKAGE: {leaked}"

print(f"  {out.shape[0]:,} rows x {out.shape[1]} columns")
print(f"  vehicle data present for {out['v_n_vehicles'].notna().mean()*100:.1f}% of rows")
print(f"  casualty data present for {out['k_n_casualties'].notna().mean()*100:.1f}% of rows")

print("\nrows per year:")
print(out["collision_year"].value_counts().sort_index().to_string())

print("\nseverity share by year (should be stable -- a jump would signal the")
print("reporting change bleeding in):")
pv = (out.groupby("collision_year")["Accident_Severity"]
        .value_counts(normalize=True).unstack() * 100).round(2)
print(pv.to_string())

# sanity check against the original cleaned file for the overlapping years
if os.path.exists("Road_Accident_Data_Cleaned.csv"):
    orig = pd.read_csv("Road_Accident_Data_Cleaned.csv", low_memory=False,
                       usecols=["Accident_Severity"])
    a = (orig["Accident_Severity"].value_counts(normalize=True) * 100).round(2)
    b = (out[out.collision_year.isin([2009, 2010])]["Accident_Severity"]
         .value_counts(normalize=True) * 100).round(2)
    print("\nvalidation -- 2009/2010 rebuilt from source vs the original cleaned file:")
    print(pd.DataFrame({"original": a, "rebuilt": b}).to_string())

out.reset_index().to_csv(OUT, index=False)
print(f"\nwrote {OUT}  ({os.path.getsize(OUT)/1e6:.0f} MB)")
