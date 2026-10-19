"""Folds, segment features and targets.

TIME CONVENTION
  A fold has a cutoff year c: everything up to the end of c is known.
    training pair : features from years c-4..c-2  ->  target in years c-1..c
    test pair     : features from years c-2..c    ->  target in years c+1..c+2
  The model is fitted on the training pair (whose target is already observed
  at the cutoff) and applied to the test pair. The test target is touched only
  by the evaluation code.

  Development folds: c = 2019, 2020, 2021 (test targets 2020-21 .. 2022-23).
  Final holdout:     c = 2023 (test target 2024-25), run once with a frozen spec.
  Post-hoc fold:     c = 2022 (test target 2023-24, overlaps the holdout year
                     2024, so it is reported only after the spec is frozen).
  Production:        trained on 2021-23 -> 2024-25, applied to 2023-25 -> 2026-27.

POPULATION
  Every network segment exists in every fold, whether or not it ever had a
  crash, and its geometry comes from the road network, not from crashes. So
  eligibility never depends on outcomes.

FEATURE GROUPS (used by ablations)
  history  : counts and crash descriptors from the window's collisions
  road     : OS Open Roads attributes (class, form of way, junctions, length ...)
  context  : network density around the segment and neighbouring history
  coords   : segment midpoint easting/northing
  exposure : AADF (motorway / A roads only; NaN elsewhere)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import HISTORY_YEARS, TARGET_YEARS

DEV_CUTOFFS = (2019, 2020, 2021)
HOLDOUT_CUTOFF = 2023
POSTHOC_CUTOFFS = (2022,)
FORECAST_CUTOFF = 2025

# what each target column means; "primary" is the product's blackspot score
TARGETS = {
    "adj_ksi_cas": "KSI casualties, DfT severity-adjusted (primary)",
    "n_ksi_cas": "KSI casualties as reported",
    "is_ksi_collision": "KSI collisions (collisions with >= 1 killed or seriously injured)",
}
PRIMARY = "adj_ksi_cas"
SCORED_CLASSES = ("M", "A", "B", "C", "U", "N")    # OS "Unknown" (private/service access) excluded


@dataclass(frozen=True)
class Window:
    start: int
    end: int

    @property
    def years(self):
        return list(range(self.start, self.end + 1))

    def __str__(self):
        return f"{self.start}-{self.end}"


@dataclass(frozen=True)
class Fold:
    cutoff: int

    @property
    def train_x(self):
        return Window(self.cutoff - HISTORY_YEARS - TARGET_YEARS + 1, self.cutoff - TARGET_YEARS)

    @property
    def train_y(self):
        return Window(self.cutoff - TARGET_YEARS + 1, self.cutoff)

    @property
    def test_x(self):
        return Window(self.cutoff - HISTORY_YEARS + 1, self.cutoff)

    @property
    def test_y(self):
        return Window(self.cutoff + 1, self.cutoff + TARGET_YEARS)

    def describe(self) -> dict:
        return {"cutoff": self.cutoff, "train_features": str(self.train_x), "train_target": str(self.train_y),
                "test_features": str(self.test_x), "test_target": str(self.test_y)}


# ------------------------------------------------------------------ inputs
COUNT_COLS = ["n_coll", "adj_ksi_cas", "n_ksi_cas", "n_fatal_cas", "n_cas", "is_ksi_collision",
              "is_fatal_collision"]


def assigned_collisions(coll: pd.DataFrame, assign: pd.DataFrame) -> pd.DataFrame:
    """Collision rows joined to their segment (unassigned rows dropped)."""
    a = assign[["collision_index", "seg_idx"]]
    d = coll.merge(a, on="collision_index", how="inner", validate="one_to_one")
    d = d[d.seg_idx >= 0].copy()
    d["n_coll"] = 1
    d["is_fatal_collision"] = (d.collision_severity == 1).astype(int)
    # Junction flag from fields coded the same way in every year. junction_detail_historic
    # is blank for 59% of 2024 and 87% of 2025 records, so it would drift in recent windows.
    # 2024-format junction_detail folds roundabouts into 0, so road_type == 1 adds them back.
    jd = pd.to_numeric(d.junction_detail, errors="coerce")
    d["at_junction"] = (jd.isin([13, 16, 17, 18, 19]) | (pd.to_numeric(d.road_type, errors="coerce") == 1)
                        ).astype(float)
    d["dark"] = d.light_conditions.isin([4, 5, 6, 7]).astype(float)
    d["urban"] = (d.urban_or_rural_area == 1).astype(float)
    d["wet"] = d.road_surface_conditions.isin([2, 3, 4, 5]).astype(float)
    sl = pd.to_numeric(d.speed_limit, errors="coerce")
    d["speed"] = sl.where(sl >= 15)
    d["multi_vehicle"] = (d.number_of_vehicles >= 2).astype(float)
    d["single_vehicle"] = (d.number_of_vehicles == 1).astype(float)
    return d


def window_sums(ac: pd.DataFrame, n_seg: int, w: Window, cols=COUNT_COLS) -> pd.DataFrame:
    """Per-segment sums over window `w` (all segments, zeros where nothing happened)."""
    sub = ac[ac.collision_year.isin(w.years)]
    s = sub.groupby("seg_idx")[cols].sum()
    out = pd.DataFrame(0.0, index=pd.RangeIndex(n_seg), columns=cols)
    out.loc[s.index] = s.values
    return out


def history_features(ac: pd.DataFrame, seg: pd.DataFrame, w: Window) -> pd.DataFrame:
    """Everything here is computed from collisions in window `w` only."""
    n = len(seg)
    tot = window_sums(ac, n, w)
    f = pd.DataFrame(index=pd.RangeIndex(n))
    for c in COUNT_COLS:
        f[f"h_{c}"] = tot[c].values
    last = window_sums(ac, n, Window(w.end, w.end), ["n_coll", "adj_ksi_cas"])
    f["h_last_n_coll"] = last.n_coll.values
    f["h_last_adj_ksi_cas"] = last.adj_ksi_cas.values
    sub = ac[ac.collision_year.isin(w.years)]
    yrs = sub.groupby("seg_idx").collision_year.nunique()
    f["h_years_with_crash"] = 0.0
    f.loc[yrs.index, "h_years_with_crash"] = yrs.values
    g = sub.groupby("seg_idx")
    desc = pd.DataFrame({"h_share_junction": g.at_junction.mean(), "h_share_dark": g.dark.mean(),
                         "h_share_urban": g.urban.mean(), "h_share_wet": g.wet.mean(),
                         "h_speed_median": g.speed.median(), "h_share_single_vehicle": g.single_vehicle.mean()})
    for c in desc:
        f[c] = np.nan
        f.loc[desc.index, c] = desc[c].values
    f["h_ksi_share"] = np.where(f.h_n_coll > 0, f.h_is_ksi_collision / f.h_n_coll.clip(lower=1), np.nan)
    per_km = 1000.0 / seg.length_m.clip(lower=50).values
    f["h_adj_ksi_per_km"] = f.h_adj_ksi_cas * per_km
    f["h_coll_per_km"] = f.h_n_coll * per_km
    return f


ROAD_FEATURES = ["log_length", "cls_M", "cls_A", "cls_B", "cls_C", "cls_U", "cls_N",
                 "fw_collapsed_dual", "fw_dual", "fw_roundabout", "fw_slip", "fw_single",
                 "share_roundabout", "share_slip", "n_junctions", "junctions_per_km",
                 "primary_route", "trunk_road", "tunnel", "named", "stroke_pieces"]
CONTEXT_FEATURES = ["net_km_1km", "net_km_3km", "nb_adj_ksi_3km", "nb_coll_3km", "stroke_adj_ksi_other"]
COORD_FEATURES = ["mid_e", "mid_n"]


def road_features(seg: pd.DataFrame) -> pd.DataFrame:
    """Static road attributes from OS Open Roads (no crash information)."""
    f = pd.DataFrame(index=seg.index)
    f["log_length"] = np.log(seg.length_m.clip(lower=10))
    for c in ["M", "A", "B", "C", "U", "N"]:
        f[f"cls_{c}"] = (seg.road_class == c).astype(float)
    fw = seg.form_of_way.fillna("")
    f["fw_collapsed_dual"] = (fw == "Collapsed Dual Carriageway").astype(float)
    f["fw_dual"] = (fw == "Dual Carriageway").astype(float)
    f["fw_roundabout"] = (fw == "Roundabout").astype(float)
    f["fw_slip"] = (fw == "Slip Road").astype(float)
    f["fw_single"] = (fw == "Single Carriageway").astype(float)
    f["share_roundabout"] = seg.share_roundabout.fillna(0).values
    f["share_slip"] = seg.share_slip.fillna(0).values
    f["n_junctions"] = seg.n_junctions.values.astype(float)
    f["junctions_per_km"] = seg.n_junctions.values / (seg.length_m.clip(lower=50).values / 1000)
    f["primary_route"] = seg.primary_route.astype(float).values
    f["trunk_road"] = seg.trunk_road.astype(float).values
    f["tunnel"] = seg.tunnel.astype(float).values
    f["named"] = (seg.road_name.fillna("") != "").astype(float).values
    f["stroke_pieces"] = seg.n_pieces.values.astype(float)
    return f


def _grid_sum(e, n, val, cell, radius_cells):
    """Sum of `val` over the (2r+1)^2 grid cells around each point's cell."""
    ix = np.floor(e / cell).astype(np.int64); iy = np.floor(n / cell).astype(np.int64)
    key = ix * 100_000 + iy
    s = pd.Series(val).groupby(key).sum()
    out = np.zeros(len(e))
    for dx in range(-radius_cells, radius_cells + 1):
        for dy in range(-radius_cells, radius_cells + 1):
            out += s.reindex((ix + dx) * 100_000 + (iy + dy)).fillna(0).values
    return out


def context_features(seg: pd.DataFrame, hist: pd.DataFrame | None) -> pd.DataFrame:
    """Network density (static) and neighbouring crash history (history window only)."""
    e, n = seg.mid_e.values, seg.mid_n.values
    f = pd.DataFrame(index=seg.index)
    f["net_km_1km"] = _grid_sum(e, n, seg.length_m.values / 1000, 1000.0, 0)
    f["net_km_3km"] = _grid_sum(e, n, seg.length_m.values / 1000, 1000.0, 1)
    if hist is not None:
        own_k, own_c = hist.h_adj_ksi_cas.values, hist.h_n_coll.values
        f["nb_adj_ksi_3km"] = _grid_sum(e, n, own_k, 1000.0, 1) - own_k
        f["nb_coll_3km"] = _grid_sum(e, n, own_c, 1000.0, 1) - own_c
        st = pd.Series(own_k).groupby(seg.stroke.values).transform("sum").values
        f["stroke_adj_ksi_other"] = st - own_k
    return f


def build_frame(seg: pd.DataFrame, ac: pd.DataFrame, xw: Window, yw: Window | None,
                road: pd.DataFrame, flows=None) -> pd.DataFrame:
    """Feature frame for one (history window, target window) pair.

    `yw=None` builds features only (production forecast). Targets are added as
    `y_<name>` columns and are never consulted by feature code.
    """
    hist = history_features(ac, seg, xw)
    ctx = context_features(seg, hist)
    X = pd.concat([road, ctx, hist], axis=1)
    X["mid_e"] = seg.mid_e.values
    X["mid_n"] = seg.mid_n.values
    if flows is not None:
        X["log_aadf"] = np.log(flows.aadf.values)
        X["log_vkm"] = np.log(flows.aadf.values * 365.0 * HISTORY_YEARS * seg.length_m.values / 1000.0)
    X = X.astype(np.float32)
    if yw is not None:
        y = window_sums(ac, len(seg), yw, list(TARGETS))
        for c in TARGETS:
            X[f"y_{c}"] = y[c].values
    return X


def feature_groups(X: pd.DataFrame) -> dict[str, list[str]]:
    hist = [c for c in X.columns if c.startswith("h_")]
    return {"history": hist, "road": [c for c in ROAD_FEATURES if c in X],
            "context": [c for c in CONTEXT_FEATURES if c in X], "coords": COORD_FEATURES,
            "exposure": [c for c in ["log_aadf"] if c in X]}
