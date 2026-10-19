"""DfT Annual Average Daily Flow (AADF) as a traffic-exposure denominator.

WHAT THE DATA COVERS
  Major roads (motorways and A roads): every link between major junctions has
  an AADF for every year, either counted or estimated by DfT from earlier
  counts and regional growth. Minor roads (B, C, unclassified): only a sample
  of count points, a few thousand a year across Great Britain, so most minor
  road segments have no measured flow nearby.

  Exposure is therefore attached only to motorway, A(M) and A road segments,
  and only where a count point on the SAME road number lies close enough to
  stand for the segment's link. Everything else is left without exposure and
  says so; historical crash counts are never substituted for traffic.

MATCHING RULE
  Segment midpoint -> nearest count point with identical road name, accepted
  if within max(1 km, 0.5 * link_length + 0.5 km). DfT count points sit
  somewhere on their link, so half a link plus a margin covers the link while
  rejecting matches that would borrow flow from a different stretch.

TIMING
  The AADF used for a forecast is the mean over the history window only, so a
  fold never sees traffic for its target years.
"""
from __future__ import annotations

import logging
import zipfile

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .config import RAW

log = logging.getLogger("blackspot.aadf")
AADF_ZIP = RAW / "aadf" / "dft_traffic_counts_aadf.zip"
MAJOR_CATEGORIES = {"PM", "TM", "PA", "TA"}     # (principal|trunk) (motorway|A road)


def load_aadf() -> pd.DataFrame:
    if not AADF_ZIP.exists():
        raise FileNotFoundError(f"{AADF_ZIP} missing -- run ml/blackspot/download.py aadf")
    with zipfile.ZipFile(AADF_ZIP) as z, z.open("dft_traffic_counts_aadf.csv") as fh:
        d = pd.read_csv(fh, low_memory=False,
                        usecols=["count_point_id", "year", "road_name", "road_category", "road_type",
                                 "easting", "northing", "link_length_km", "estimation_method",
                                 "all_motor_vehicles"])
    d["road_name"] = d.road_name.astype(str).str.strip().str.upper()
    return d


def window_flows(aadf: pd.DataFrame, years) -> pd.DataFrame:
    """Mean AADF per major-road count point over `years` (history window only)."""
    w = aadf[aadf.year.isin(list(years)) & aadf.road_category.isin(MAJOR_CATEGORIES)]
    g = w.groupby("count_point_id")
    out = pd.DataFrame({
        "road_name": g.road_name.last(), "easting": g.easting.last(), "northing": g.northing.last(),
        "link_length_km": g.link_length_km.last(), "aadf": g.all_motor_vehicles.mean(),
        "share_counted": g.estimation_method.agg(lambda s: (s == "Counted").mean()),
        "n_years": g.year.nunique()})
    return out[out.aadf > 0].reset_index()


def match_segments(seg: pd.DataFrame, flows: pd.DataFrame) -> pd.DataFrame:
    """Attach AADF to segments. `seg` needs segment_id, road_number, mid_e, mid_n.

    Returns one row per input segment: aadf (NaN where unmatched), the count
    point used, its distance, and the counted share of the AADF years.
    """
    res = pd.DataFrame({"segment_id": seg.segment_id.values, "aadf": np.nan,
                        "aadf_count_point": pd.array([pd.NA] * len(seg), dtype="Int64"),
                        "aadf_distance_m": np.nan, "aadf_share_counted": np.nan})
    road = seg.road_number.fillna("").astype(str).str.upper().values
    for name, cps in flows.groupby("road_name"):
        idx = np.flatnonzero(road == name)
        if not len(idx):
            continue
        tree = cKDTree(cps[["easting", "northing"]].values)
        d, j = tree.query(np.column_stack([seg.mid_e.values[idx], seg.mid_n.values[idx]]))
        lim = np.maximum(1000.0, 500.0 * cps.link_length_km.values[j] + 500.0)
        ok = d <= lim
        res.loc[idx[ok], "aadf"] = cps.aadf.values[j[ok]]
        res.loc[idx[ok], "aadf_count_point"] = cps.count_point_id.values[j[ok]]
        res.loc[idx[ok], "aadf_distance_m"] = d[ok]
        res.loc[idx[ok], "aadf_share_counted"] = cps.share_counted.values[j[ok]]
    return res
