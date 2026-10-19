"""Where does the national KSI total go? Covered vs uncovered, with reasons.

Every collision in Great Britain ends up in exactly one bucket:
  scored      assigned to a segment of a scored class (M, A, B, C, U, N)
  access_road assigned to an OS "Unknown" class link (private / service access roads), not scored
  no_road     coordinates present but no centreline within 50 m (often roads changed since, car parks, data errors)
  no_coords   no usable location
The denominator is always the national total for the window.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import SCORED_CLASSES

STATS19_CLASS = {1: "M", 2: "A(M)", 3: "A", 4: "B", 5: "C", 6: "U", -1: "missing"}


def coverage_table(coll: pd.DataFrame, assign: pd.DataFrame, seg: pd.DataFrame,
                   years, target="adj_ksi_cas") -> pd.DataFrame:
    a = assign.set_index("collision_index").reindex(coll.collision_index)
    idx = a.seg_idx.fillna(-1).astype(int).values
    os_cls = np.where(idx >= 0, seg.road_class.values[np.clip(idx, 0, None)], "")
    scored = (idx >= 0) & np.isin(os_cls, list(SCORED_CLASSES))
    bucket = np.select(
        [scored, idx >= 0, a.unassigned_reason.fillna("").str.startswith("no_road").values],
        ["scored", "access_road", "no_road"], "no_coords")
    d = pd.DataFrame({"year": coll.collision_year.values, "bucket": bucket, "os_class": os_cls,
                      "stats19_class": pd.to_numeric(coll.first_road_class, errors="coerce").fillna(-1)
                      .astype(int).map(STATS19_CLASS).fillna("other").values,
                      "y": coll[target].values})
    return d[d.year.isin(list(years))]


def summarise(d: pd.DataFrame) -> dict:
    tot = d.y.sum()
    out = {"national_total": float(tot),
           "by_bucket": (d.groupby("bucket").y.sum() / tot).round(4).to_dict(),
           "scored_by_os_class": (d[d.bucket == "scored"].groupby("os_class").y.sum() / tot).round(4).to_dict(),
           "by_stats19_class_share_scored": (d.groupby("stats19_class")
                                             .apply(lambda g: g.y[g.bucket == "scored"].sum() / g.y.sum())
                                             .round(4).to_dict()),
           "stats19_class_share_of_national": (d.groupby("stats19_class").y.sum() / tot).round(4).to_dict()}
    return out
