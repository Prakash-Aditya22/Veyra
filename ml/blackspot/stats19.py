"""STATS19 loading, schema normalisation and casualty aggregation.

GRAIN
  collision table : one row per collision            (key: collision_index)
  vehicle table   : one row per vehicle in a collision
  casualty table  : one row per casualty             (key: collision_index + casualty_reference)

Casualty rows are aggregated to collision grain BEFORE any join, so a collision
with three casualties is never tripled. The join is then one-to-one and is
asserted to be so.

SOURCES AND HARMONISATION
  2015-2020  collision fields from the v1 extract (stats19_recent.csv), which
             already carries the revised (2024 data guide) code lists, e.g.
             junction_detail 0/13/16-19 with junction_detail_historic beside it.
  2021-2025  collision fields from the per-year DfT files, which carry the same
             schema plus OSGR eastings/northings.
  2015-2025  casualty severity (and DfT's severity adjustment) from the casualty
             table, aggregated here.
  Overlapping years (2021-2023) are compared in `compare_overlap`; DfT revises
  past years in each release, so small differences are expected and reported.

OUTCOME vs FEATURE FIELDS
  Fields describing how badly people were hurt are OUTCOMES. They are kept in
  `OUTCOME_COLS` and only ever used (a) as targets for a later period or
  (b) as history counts for an earlier period. They never describe the same
  collision they are used to predict.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .config import FATAL, INTERIM, LEGACY_CSV, RAW, SERIOUS, SLIGHT
from .io_utils import write_parquet

log = logging.getLogger("blackspot.stats19")

STATS19_DIR = RAW / "stats19"
RAW_YEARS = range(2021, 2026)
CASUALTY_ALL = STATS19_DIR / "dft-road-casualty-statistics-casualty-1979-latest-published-year.csv"
COLLISIONS_PARQUET = INTERIM / "collisions.parquet"

# canonical collision-level fields (all numerically coded, see DfT data guide)
COLLISION_FIELDS = [
    "collision_index", "collision_year", "latitude", "longitude",
    "police_force", "number_of_vehicles", "number_of_casualties", "day_of_week",
    "first_road_class", "first_road_number", "second_road_class", "second_road_number",
    "road_type", "speed_limit", "junction_detail", "junction_detail_historic",
    "junction_control", "pedestrian_crossing", "light_conditions", "weather_conditions",
    "road_surface_conditions", "special_conditions_at_site", "carriageway_hazards",
    "urban_or_rural_area", "trunk_road_flag", "local_authority_district", "hour", "month", "day_of_year",
    "collision_severity",
]
# casualty-derived outcome fields added by aggregate_casualties()
OUTCOME_COLS = ["collision_severity", "n_cas", "n_fatal_cas", "n_serious_cas", "n_slight_cas",
                "n_ksi_cas", "adj_serious_cas", "adj_ksi_cas", "is_ksi_collision",
                "injury_based_share"]

LEGACY_SEV = {"Fatal": FATAL, "Grievous": SERIOUS, "Minor": SLIGHT}


# ------------------------------------------------------------------ collisions
def load_legacy_collisions(years=range(2015, 2021), path: Path = LEGACY_CSV) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing -- run ml/build_recent.py (v1) first")
    want = [c for c in COLLISION_FIELDS if c not in ("hour", "month", "day_of_year", "collision_severity")]
    df = pd.read_csv(path, usecols=want + ["Hour", "Month", "DayOfYear", "Accident_Severity"],
                     low_memory=False, dtype={"collision_index": str})
    df = df[df.collision_year.isin(list(years))].copy()
    df["collision_severity"] = df.pop("Accident_Severity").map(LEGACY_SEV)
    df = df.rename(columns={"Hour": "hour", "Month": "month", "DayOfYear": "day_of_year"})
    df["source"] = "v1_extract"
    df["easting"] = np.nan
    df["northing"] = np.nan
    return df


def load_raw_collisions(years=RAW_YEARS) -> pd.DataFrame:
    parts = []
    for y in years:
        p = STATS19_DIR / f"dft-road-casualty-statistics-collision-{y}.csv"
        if not p.exists():
            raise FileNotFoundError(f"{p} missing -- run ml/blackspot/download.py stats19")
        d = pd.read_csv(p, low_memory=False, dtype={"collision_index": str, "collision_ref_no": str})
        d["hour"] = pd.to_datetime(d.time, format="%H:%M", errors="coerce").dt.hour
        dt_ = pd.to_datetime(d.date, format="%d/%m/%Y", errors="coerce")
        d["month"], d["day_of_year"] = dt_.dt.month, dt_.dt.dayofyear
        d = d.rename(columns={"location_easting_osgr": "easting", "location_northing_osgr": "northing"})
        d = d[[c for c in COLLISION_FIELDS if c in d.columns] + ["easting", "northing"]]
        d["source"] = f"dft_{y}"
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def compare_overlap(legacy: pd.DataFrame, raw: pd.DataFrame) -> dict:
    """Compare the v1 extract and the current DfT release on the years both cover."""
    out = {}
    for y in sorted(set(legacy.collision_year) & set(raw.collision_year)):
        a = legacy[legacy.collision_year == y].set_index("collision_index")
        b = raw[raw.collision_year == y].set_index("collision_index")
        common = a.index.intersection(b.index)
        sev_diff = int((a.loc[common, "collision_severity"] != b.loc[common, "collision_severity"]).sum())
        loc_diff = int(((a.loc[common, "latitude"] - b.loc[common, "latitude"]).abs() > 1e-4).sum())
        out[int(y)] = {"v1_rows": len(a), "current_rows": len(b), "common": len(common),
                       "only_v1": int(len(a.index.difference(b.index))),
                       "only_current": int(len(b.index.difference(a.index))),
                       "severity_changed": sev_diff, "location_changed": loc_diff}
    return out


# ------------------------------------------------------------------ casualties
CAS_COLS = ["collision_index", "collision_year", "vehicle_reference", "casualty_reference",
            "casualty_severity",
            "casualty_injury_based", "casualty_adjusted_severity_serious"]


def load_casualties(years=range(2015, 2026), path: Path = CASUALTY_ALL) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing -- run ml/blackspot/download.py stats19")
    keep = []
    for ch in pd.read_csv(path, usecols=CAS_COLS, chunksize=2_000_000, low_memory=False,
                          dtype={"collision_index": str}):
        keep.append(ch[ch.collision_year.isin(list(years))])
    cas = pd.concat(keep, ignore_index=True)
    # casualty_reference alone is not unique in the source (one 2016 collision
    # reuses it for two different people), so the key includes the vehicle.
    dup = cas.duplicated(["collision_index", "vehicle_reference", "casualty_reference"]).sum()
    if dup:
        raise ValueError(f"casualty table has {dup} duplicate casualty keys")
    cas.attrs["casualty_reference_reused"] = int(
        cas.duplicated(["collision_index", "casualty_reference"]).sum())
    return cas


def aggregate_casualties(cas: pd.DataFrame) -> pd.DataFrame:
    """Casualty grain -> collision grain.

    adj_ksi_cas follows DfT's severity adjustment: a fatal casualty counts 1;
    every non-fatal casualty counts its modelled probability of being recorded
    as serious under injury-based reporting (exactly 0/1 where the force
    already used injury-based reporting).
    """
    sev = cas.casualty_severity
    adj = cas.casualty_adjusted_severity_serious.where(sev != FATAL, 0.0).fillna(
        (sev == SERIOUS).astype(float))                    # missing adjustment -> as reported
    g = pd.DataFrame({
        "collision_index": cas.collision_index,
        "n_cas": 1,
        "n_fatal_cas": (sev == FATAL).astype(int),
        "n_serious_cas": (sev == SERIOUS).astype(int),
        "n_slight_cas": (sev == SLIGHT).astype(int),
        "adj_serious_cas": adj,
        "injury_based": cas.casualty_injury_based.clip(lower=0),
    }).groupby("collision_index", sort=False)
    agg = g.agg(n_cas=("n_cas", "sum"), n_fatal_cas=("n_fatal_cas", "sum"),
                n_serious_cas=("n_serious_cas", "sum"), n_slight_cas=("n_slight_cas", "sum"),
                adj_serious_cas=("adj_serious_cas", "sum"),
                injury_based_share=("injury_based", "mean"))
    agg["n_ksi_cas"] = agg.n_fatal_cas + agg.n_serious_cas
    agg["adj_ksi_cas"] = agg.n_fatal_cas + agg.adj_serious_cas
    return agg.reset_index()


def check_collision_casualty_consistency(coll: pd.DataFrame) -> dict:
    """Checks that only hold if the join and aggregation are right."""
    has = coll.n_cas.notna()
    worst = np.select([coll.n_fatal_cas > 0, coll.n_serious_cas > 0], [FATAL, SERIOUS], SLIGHT)
    return {
        "collisions": int(len(coll)),
        "with_casualty_rows": int(has.sum()),
        "without_casualty_rows": int((~has).sum()),
        "n_cas_equals_number_of_casualties": float((coll.n_cas[has] == coll.number_of_casualties[has]).mean()),
        "worst_casualty_equals_collision_severity": float((worst[has] == coll.collision_severity[has]).mean()),
    }


# ------------------------------------------------------------------ coordinates
def to_bng(lon, lat):
    """WGS84 lon/lat -> British National Grid (EPSG:27700) metres."""
    from pyproj import Transformer
    t = Transformer.from_crs(4326, 27700, always_xy=True)
    return t.transform(np.asarray(lon, float), np.asarray(lat, float))


def fill_bng(df: pd.DataFrame) -> pd.DataFrame:
    """Use published OSGR where present; otherwise project lat/lon."""
    miss = df.easting.isna() & df.latitude.notna() & df.longitude.notna()
    if miss.any():
        e, n = to_bng(df.loc[miss, "longitude"], df.loc[miss, "latitude"])
        df.loc[miss, "easting"], df.loc[miss, "northing"] = e, n
        df.loc[miss, "bng_source"] = "projected_from_latlon"
    df.loc[~miss & df.easting.notna(), "bng_source"] = "published_osgr"
    return df


def bng_projection_check(raw: pd.DataFrame, n: int = 50_000, seed: int = 42) -> dict:
    """How far is our lat/lon->BNG projection from DfT's published OSGR?"""
    s = raw.dropna(subset=["easting", "northing", "latitude", "longitude"])
    s = s.sample(min(n, len(s)), random_state=seed)
    e, nn = to_bng(s.longitude, s.latitude)
    d = np.hypot(e - s.easting.values, nn - s.northing.values)
    return {"n": int(len(s)), "median_m": float(np.median(d)), "p95_m": float(np.percentile(d, 95)),
            "p99_m": float(np.percentile(d, 99)), "max_m": float(d.max())}


# ------------------------------------------------------------------ build
def build_collisions(write: bool = True) -> tuple[pd.DataFrame, dict]:
    """Canonical collision table 2015-2025 with casualty outcomes. Returns (df, quality report)."""
    q: dict = {}
    legacy_all = load_legacy_collisions(years=range(2015, 2024))
    raw = load_raw_collisions()
    q["overlap_v1_vs_current"] = compare_overlap(legacy_all, raw)
    q["bng_projection_check"] = bng_projection_check(raw)

    legacy = legacy_all[legacy_all.collision_year <= 2020]
    coll = pd.concat([legacy, raw], ignore_index=True)
    if coll.collision_index.duplicated().any():
        raise ValueError("duplicate collision_index after combining sources")

    cas = load_casualties()
    q["casualty_rows_by_year"] = cas.groupby("collision_year").size().to_dict()
    q["casualty_reference_reused_within_collision"] = cas.attrs.get("casualty_reference_reused")
    q["casualty_all_vs_per_year_files"] = {
        y: {"all_years_file": int((cas.collision_year == y).sum()),
            "per_year_file": int(sum(1 for _ in open(
                STATS19_DIR / f"dft-road-casualty-statistics-casualty-{y}.csv", encoding="utf-8")) - 1)}
        for y in RAW_YEARS}
    agg = aggregate_casualties(cas)
    n0 = len(coll)
    coll = coll.merge(agg, on="collision_index", how="left", validate="one_to_one")
    assert len(coll) == n0, "casualty join changed the number of collisions"
    q["consistency"] = check_collision_casualty_consistency(coll)
    orphan = set(agg.collision_index) - set(coll.collision_index)
    q["casualty_collisions_without_collision_row"] = len(orphan)

    coll["is_ksi_collision"] = coll.collision_severity.isin([FATAL, SERIOUS]).astype(int)
    for c in ["n_cas", "n_fatal_cas", "n_serious_cas", "n_slight_cas", "n_ksi_cas"]:
        coll[c] = coll[c].fillna(0).astype(int)
    coll["adj_serious_cas"] = coll.adj_serious_cas.fillna(0.0)
    coll["adj_ksi_cas"] = coll.adj_ksi_cas.fillna(0.0)

    # coordinates
    bad = coll.latitude.isna() | coll.longitude.isna() | (coll.latitude == -1)
    coll.loc[bad, ["latitude", "longitude"]] = np.nan
    coll = fill_bng(coll)
    q["missing_coordinates_by_year"] = coll[coll.easting.isna()].groupby("collision_year").size().to_dict()
    inside = coll.easting.between(0, 700_000) & coll.northing.between(0, 1_300_000)
    q["coordinates_outside_gb_extent"] = int((coll.easting.notna() & ~inside).sum())
    coll.loc[coll.easting.notna() & ~inside, ["easting", "northing"]] = np.nan

    q["rows_by_year"] = coll.groupby("collision_year").size().to_dict()
    q["ksi_casualties_by_year"] = coll.groupby("collision_year").n_ksi_cas.sum().to_dict()
    q["adj_ksi_casualties_by_year"] = coll.groupby("collision_year").adj_ksi_cas.sum().round(1).to_dict()
    q["ksi_collisions_by_year"] = coll.groupby("collision_year").is_ksi_collision.sum().to_dict()

    for c in ["first_road_class", "first_road_number", "speed_limit", "police_force", "hour", "month"]:
        coll[c] = pd.to_numeric(coll[c], errors="coerce")
    if write:
        write_parquet(coll, COLLISIONS_PARQUET)
    return coll, q


# columns the modelling steps read; loading only these roughly halves memory
MODEL_COLUMNS = ["collision_index", "collision_year", "junction_detail", "road_type", "light_conditions",
                 "urban_or_rural_area", "road_surface_conditions", "speed_limit", "number_of_vehicles",
                 "collision_severity", "hour", "adj_ksi_cas", "n_ksi_cas", "n_fatal_cas", "n_cas",
                 "is_ksi_collision"]


def load_collisions(columns=None) -> pd.DataFrame:
    if not COLLISIONS_PARQUET.exists():
        raise FileNotFoundError(f"{COLLISIONS_PARQUET} missing -- run: python ml/pipeline.py data")
    return pd.read_parquet(COLLISIONS_PARQUET, columns=columns)
