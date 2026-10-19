"""Historical-window strategies for the blackspot model (phase 2 research, not production).

Two separate choices, implemented separately:

  history rule  H(k): which collision years (and with what weight) build the
                PREDICTORS for a forecast made at cutoff k. Never includes a
                year after k.
  pair rule     T(c): which (history -> two-year target) pairs, all with targets
                ending at or before the cutoff c, train the MODEL PARAMETERS.

A training pair with target end e uses history H(e-2) and target years
(e-1, e). The test pair at cutoff c uses H(c) and target years (c+1, c+2),
which only evaluation code reads.

Count features are put on one scale: the reference (three contiguous,
equally weighted years) is left exactly as v2 builds it, and any other window
is rescaled to "three-year equivalent" counts (weighted sum x 3 / sum of
weights). So a feature means the same thing whatever window built it, and the
reference reproduces v2 bit for bit.

COVID-19: 2020 and 2021 had far less traffic. "Excluding" them means dropping
their collisions from aggregation (history rules *_nocovid) or dropping
training pairs whose TARGET years touch them (pair rule "noncovid").
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import FIRST_YEAR, TARGET_YEARS
from .features import (COUNT_COLS, Window, context_features, road_features, window_sums)

COVID_YEARS = (2020, 2021)


# ------------------------------------------------------------------ history rules
@dataclass(frozen=True)
class History:
    """Years and per-year weights used to build predictors at cutoff k."""
    kind: str                 # recent | all | recent_nocovid | all_nocovid | decay
    length: int = 3           # for recent rules
    half_life: float = 2.0    # for decay

    def years_weights(self, k: int, first: int = FIRST_YEAR) -> dict[int, float]:
        if self.kind == "recent":
            ys = list(range(k - self.length + 1, k + 1))
        elif self.kind == "all":
            ys = list(range(first, k + 1))
        elif self.kind == "recent_nocovid":
            ys, y = [], k
            while len(ys) < self.length and y >= first:
                if y not in COVID_YEARS:
                    ys.append(y)
                y -= 1
            ys = sorted(ys)
        elif self.kind == "all_nocovid":
            ys = [y for y in range(first, k + 1) if y not in COVID_YEARS]
        elif self.kind == "decay":
            ys = list(range(first, k + 1))
            return {y: float(0.5 ** ((k - y) / self.half_life)) for y in ys}
        else:
            raise ValueError(self.kind)
        return {y: 1.0 for y in ys}

    def feasible(self, k: int, first: int = FIRST_YEAR) -> bool:
        yw = self.years_weights(k, first)
        if not yw or min(yw) < first or max(yw) > k:
            return False
        if self.kind in ("recent", "recent_nocovid"):
            return len(yw) == self.length
        return True

    @property
    def is_reference(self) -> bool:
        return self.kind == "recent" and self.length == 3

    def label(self) -> str:
        return {"recent": f"recent{self.length}", "all": "all", "recent_nocovid": f"recent{self.length}_nocovid",
                "all_nocovid": "all_nocovid", "decay": f"decay_h{self.half_life:g}"}[self.kind]


# ------------------------------------------------------------------ pair rules
def training_target_ends(rule: str, c: int, history: History, first: int = FIRST_YEAR) -> list[int]:
    """Target end years e (<= c) of the training pairs used at cutoff c."""
    feasible = [e for e in range(first + 1, c + 1) if history.feasible(e - TARGET_YEARS, first)]
    noncovid = [e for e in feasible if not set(range(e - TARGET_YEARS + 1, e + 1)) & set(COVID_YEARS)]
    if rule == "single":
        return [c] if c in feasible else []
    if rule == "stacked":
        return feasible
    if rule == "noncovid":                       # most recent pair whose target avoids 2020-21
        return noncovid[-1:] if noncovid else []
    if rule == "stacked_noncovid":
        return noncovid
    raise ValueError(rule)


# ------------------------------------------------------------------ features
def history_features_w(ac: pd.DataFrame, seg: pd.DataFrame, yw: dict[int, float]) -> pd.DataFrame:
    """v2 history features from weighted years, on the three-year-equivalent scale.

    With three contiguous years of weight 1 this returns exactly
    features.history_features(ac, seg, Window(...)).
    """
    years = sorted(yw)
    contiguous = years == list(range(years[0], years[-1] + 1))
    uniform = len(set(yw.values())) == 1 and next(iter(yw.values())) == 1.0
    if contiguous and uniform and len(years) == 3:
        from .features import history_features
        return history_features(ac, seg, Window(years[0], years[-1]))

    n = len(seg)
    scale = 3.0 / sum(yw.values())
    sub = ac[ac.collision_year.isin(years)].copy()
    sub["_w"] = sub.collision_year.map(yw).astype(float)
    f = pd.DataFrame(index=pd.RangeIndex(n))
    wsum = sub[COUNT_COLS].multiply(sub._w, axis=0).groupby(sub.seg_idx).sum() * scale
    for c in COUNT_COLS:
        f[f"h_{c}"] = 0.0
        f.loc[wsum.index, f"h_{c}"] = wsum[c].values
    last = window_sums(ac, n, Window(years[-1], years[-1]), ["n_coll", "adj_ksi_cas"])
    f["h_last_n_coll"] = last.n_coll.values
    f["h_last_adj_ksi_cas"] = last.adj_ksi_cas.values
    yrs = sub.groupby("seg_idx").collision_year.nunique()
    f["h_years_with_crash"] = 0.0
    f.loc[yrs.index, "h_years_with_crash"] = yrs.values * 3.0 / len(years)
    g = sub.assign(**{c: sub[c] * sub._w for c in ["at_junction", "dark", "urban", "wet", "single_vehicle"]})
    gs = g.groupby("seg_idx")
    wtot = gs._w.sum()
    for src, dst in [("at_junction", "h_share_junction"), ("dark", "h_share_dark"), ("urban", "h_share_urban"),
                     ("wet", "h_share_wet"), ("single_vehicle", "h_share_single_vehicle")]:
        f[dst] = np.nan
        f.loc[wtot.index, dst] = (gs[src].sum() / wtot).values
    med = sub.groupby("seg_idx").speed.median()
    f["h_speed_median"] = np.nan
    f.loc[med.index, "h_speed_median"] = med.values
    f["h_ksi_share"] = np.where(f.h_n_coll > 0, f.h_is_ksi_collision / f.h_n_coll.clip(lower=1e-9), np.nan)
    per_km = 1000.0 / seg.length_m.clip(lower=50).values
    f["h_adj_ksi_per_km"] = f.h_adj_ksi_cas * per_km
    f["h_coll_per_km"] = f.h_n_coll * per_km
    return f[_V2_HISTORY_ORDER]


_V2_HISTORY_ORDER = [f"h_{c}" for c in COUNT_COLS] + [
    "h_last_n_coll", "h_last_adj_ksi_cas", "h_years_with_crash", "h_share_junction", "h_share_dark",
    "h_share_urban", "h_share_wet", "h_speed_median", "h_share_single_vehicle", "h_ksi_share",
    "h_adj_ksi_per_km", "h_coll_per_km"]


def frame(seg, ac, road, history: History, k: int, target_years: list[int] | None,
          targets=("adj_ksi_cas",)) -> pd.DataFrame:
    """Feature frame at cutoff k under `history` (+ y_ columns for target_years)."""
    yw = history.years_weights(k)
    if max(yw) > k:
        raise AssertionError("history rule produced a year after the cutoff")
    hist = history_features_w(ac, seg, yw)
    X = pd.concat([road, context_features(seg, hist), hist], axis=1)
    X["mid_e"] = seg.mid_e.values
    X["mid_n"] = seg.mid_n.values
    X = X.astype(np.float32)
    if target_years is not None:
        if min(target_years) <= k:
            raise AssertionError("target years must be after the cutoff")
        y = window_sums(ac, len(seg), Window(min(target_years), max(target_years)), list(targets))
        for t in targets:
            X[f"y_{t}"] = y[t].values
    return X


@dataclass
class Strategy:
    name: str
    history: History
    pairs: str = "single"
    description: str = ""
    group: str = ""
    extra: dict = field(default_factory=dict)


def strategies(decay_half_lives=(1.0, 2.0, 4.0)) -> list[Strategy]:
    S = [
        Strategy("REF_recent3_single", History("recent", 3), "single",
                 "v2 production configuration: 3 most recent years, most recent training pair", "reference"),
        Strategy("A_all_single", History("all"), "single",
                 "predictors from every year since 2015 (3-yr-equivalent scale); most recent pair", "A full history"),
        Strategy("A_recent3_stacked", History("recent", 3), "stacked",
                 "3-yr predictors; ALL feasible training pairs stacked (more parameter-fitting history)",
                 "A full history"),
        Strategy("B_nocovid3_single", History("recent_nocovid", 3), "single",
                 "predictors from the 3 most recent non-2020/21 years; most recent pair", "B COVID exclusion"),
        Strategy("B_recent3_noncovidpair", History("recent", 3), "noncovid",
                 "3-yr predictors; most recent training pair whose TARGET avoids 2020-21", "B COVID exclusion"),
        Strategy("B_nocovid3_noncovidpair", History("recent_nocovid", 3), "noncovid",
                 "both exclusions", "B COVID exclusion"),
        Strategy("C_recent2_single", History("recent", 2), "single", "2 most recent years", "C recent window"),
        Strategy("C_recent4_single", History("recent", 4), "single", "4 most recent years", "C recent window"),
        Strategy("C_recent5_single", History("recent", 5), "single", "5 most recent years", "C recent window"),
    ]
    for h in decay_half_lives:
        S.append(Strategy(f"D_decay_h{h:g}_single", History("decay", half_life=h), "single",
                          f"all years since 2015, weight 0.5^(age/{h:g})", "D recency weighting"))
    return S
