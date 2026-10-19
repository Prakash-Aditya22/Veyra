"""Fold execution: fit every model on the training pair, score the test pair,
evaluate on identical populations with clustered (spatial-block) uncertainty.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import aadf as aadf_mod
from .evaluation import FRACS, WeightedRanker, block_weights, count_metrics, weighted_deviance
from .features import (PRIMARY, SCORED_CLASSES, TARGETS, Fold, Window, build_frame,
                       feature_groups, road_features)
from .models import (CountGLM, Design, eb_forecast, fit_lgbm, overdispersion_test, scaled_history)

log = logging.getLogger("blackspot.experiment")

LOG1P = {"n_junctions", "net_km_1km", "net_km_3km", "nb_adj_ksi_3km", "nb_coll_3km",
         "stroke_adj_ksi_other", "stroke_pieces"}


def block_id(e, n, size: float = 50_000.0) -> np.ndarray:
    """50 km British National Grid square: the unit of spatial CV and of the bootstrap."""
    return (np.floor(np.asarray(e) / size).astype(int) * 1000 + np.floor(np.asarray(n) / size).astype(int))


@dataclass
class Context:
    seg: pd.DataFrame
    ac: pd.DataFrame                      # assigned collisions
    coll: pd.DataFrame                    # all collisions (national denominators)
    road: pd.DataFrame
    blocks: np.ndarray
    scored: np.ndarray                    # bool mask over segments
    aadf_raw: pd.DataFrame | None = None
    _flows: dict = field(default_factory=dict)

    def flows(self, w: Window) -> pd.DataFrame | None:
        if self.aadf_raw is None:
            return None
        if str(w) not in self._flows:
            fl = aadf_mod.window_flows(self.aadf_raw, w.years)
            s = self.seg[["segment_id", "mid_e", "mid_n"]].copy()
            s["road_number"] = self.seg.road_number.where(self.seg.road_class.isin(["M", "A"]), "")
            self._flows[str(w)] = aadf_mod.match_segments(s, fl)
        return self._flows[str(w)]


def make_context(seg, coll, assign, with_aadf=True) -> Context:
    """Restrict to scored road classes; collisions snapped to other segments drop out of
    segment counts but stay in `coll`, so national denominators still include them."""
    from .features import assigned_collisions
    keep = seg.road_class.isin(SCORED_CLASSES).values
    new_idx = np.full(len(seg), -1); new_idx[keep] = np.arange(keep.sum())
    assign = assign.copy()
    assign["seg_idx"] = np.where(assign.seg_idx >= 0, new_idx[assign.seg_idx.clip(lower=0)], -1)
    seg = seg[keep].reset_index(drop=True)
    ac = assigned_collisions(coll, assign)
    raw = aadf_mod.load_aadf() if with_aadf else None
    return Context(seg=seg, ac=ac, coll=coll, road=road_features(seg).astype(np.float32),
                   blocks=block_id(seg.mid_e, seg.mid_n), scored=np.ones(len(seg), bool), aadf_raw=raw)


# ------------------------------------------------------------------ model specs
@dataclass
class Spec:
    name: str
    kind: str                     # baseline | poisson | nb2 | eb | lgbm
    groups: tuple = ()            # feature groups for glm/lgbm
    score_col: str = ""           # for baselines
    params: dict = field(default_factory=dict)
    exposure: bool = False        # requires AADF; evaluated on the exposure population


def standard_specs(lgbm_params=None) -> list[Spec]:
    p = lgbm_params or {}
    return [
        Spec("hist_adj_ksi", "baseline", score_col="h_adj_ksi_cas"),
        Spec("hist_ksi_cas", "baseline", score_col="h_n_ksi_cas"),
        Spec("hist_collisions", "baseline", score_col="h_n_coll"),
        Spec("hist_ksi_collisions", "baseline", score_col="h_is_ksi_collision"),
        # historical RATE baselines (per km of road); added after the dev run started, so they
        # appear in holdout results only -- baselines are not fitted and play no part in selection
        Spec("hist_adj_ksi_per_km", "baseline", score_col="h_adj_ksi_per_km"),
        Spec("hist_collisions_per_km", "baseline", score_col="h_coll_per_km"),
        Spec("poisson_glm", "poisson", groups=("history", "road", "context")),
        Spec("nb_glm", "nb2", groups=("history", "road", "context")),
        Spec("eb", "eb"),
        Spec("lgbm", "lgbm", groups=("history", "road", "context"), params=p),
    ]


MAIN_CANDIDATES = ["eb", "nb_glm", "poisson_glm", "lgbm"]          # simplest first
MAIN_PAIRS = [(a, b) for a in MAIN_CANDIDATES for b in MAIN_CANDIDATES if a != b] + \
             [(m, "hist_collisions") for m in MAIN_CANDIDATES]
EXPOSURE_PAIRS = [("eb_aadf", "eb"), ("nb_glm_aadf", "nb_glm"), ("lgbm_aadf", "lgbm")]
ABLATION_PAIRS = [(a, "lgbm") for a in ["lgbm+coords", "lgbm-context", "lgbm-road", "lgbm_history_only",
                                         "lgbm-history", "lgbm_road_only"]] + [("lgbm", "hist_collisions")]


def ablation_specs(lgbm_params=None) -> list[Spec]:
    p = lgbm_params or {}
    return [
        Spec("hist_collisions", "baseline", score_col="h_n_coll"),
        Spec("lgbm", "lgbm", groups=("history", "road", "context"), params=p),
        Spec("lgbm+coords", "lgbm", groups=("history", "road", "context", "coords"), params=p),
        Spec("lgbm-context", "lgbm", groups=("history", "road"), params=p),
        Spec("lgbm-road", "lgbm", groups=("history", "context"), params=p),
        Spec("lgbm_history_only", "lgbm", groups=("history",), params=p),
        Spec("lgbm-history", "lgbm", groups=("road", "context"), params=p),
        Spec("lgbm_road_only", "lgbm", groups=("road",), params=p),
    ]


def exposure_specs(lgbm_params=None) -> list[Spec]:
    """Same model with and without AADF, evaluated on the AADF-matched population."""
    p = lgbm_params or {}
    return [
        Spec("hist_collisions", "baseline", score_col="h_n_coll", exposure=True),
        Spec("hist_adj_ksi", "baseline", score_col="h_adj_ksi_cas", exposure=True),
        Spec("eb", "eb", exposure=True, params={"aadf_in_spf": False}),
        Spec("eb_aadf", "eb", exposure=True, params={"aadf_in_spf": True}),
        Spec("nb_glm", "nb2", groups=("history", "road", "context"), exposure=True),
        Spec("nb_glm_aadf", "nb2", groups=("history", "road", "context", "exposure"), exposure=True),
        Spec("lgbm", "lgbm", groups=("history", "road", "context"), params=p, exposure=True),
        Spec("lgbm_aadf", "lgbm", groups=("history", "road", "context", "exposure"), params=p, exposure=True),
    ]


# ------------------------------------------------------------------ fitting
def _cols(X, groups):
    g = feature_groups(X)
    return [c for grp in groups for c in g[grp]]


def fit_predict(spec: Spec, Xtr, ytr, Xte, target=PRIMARY, train_rows=None) -> tuple[np.ndarray, dict]:
    """Fit on training rows of the training pair, predict every test row."""
    info: dict = {}
    tr = np.ones(len(Xtr), bool) if train_rows is None else train_rows
    if spec.kind == "baseline":
        h_tr, h_te = Xtr[spec.score_col].values, Xte[spec.score_col].values
        # count forecast = history x (train target / train history); ranking uses the raw history
        return scaled_history(h_tr[tr], ytr[tr], h_te), info
    if spec.kind in ("poisson", "nb2"):
        cols = _cols(Xtr, spec.groups)
        logc = LOG1P | {c for c in cols if c.startswith("h_") and not c.startswith("h_share")
                        and c not in ("h_speed_median", "h_ksi_share")}
        d = Design(cols, log1p_cols=logc).fit(Xtr[tr])
        m = CountGLM(spec.kind).fit(d.transform(Xtr[tr]), ytr[tr])
        info = {"alpha": m.alpha, "converged": m.converged, "n_coef": len(m.coef_)}
        if spec.kind == "poisson":
            info["overdispersion"] = overdispersion_test(ytr[tr], m.predict(d.transform(Xtr[tr])))
        return m.predict(d.transform(Xte)), info
    if spec.kind == "eb":
        x_col = f"h_{target}"
        expo = spec.params.get("aadf_in_spf", False)
        out = eb_forecast(Xtr[tr], Xtr[x_col].values[tr], ytr[tr], Xte, Xte[x_col].values, exposure=expo,
                          spf_rows=tr)
        info = {"k": out["k"], "alpha": out["alpha"], "spf_coef": out["spf_coef"]}
        info["_extra"] = {"eb_history": out["eb_history"], "spf_history": out["spf_history"],
                          "excess_history": out["excess_history"], "weight": out["weight"]}
        return out["forecast"], info
    if spec.kind == "lgbm":
        cols = _cols(Xtr, spec.groups)
        m = fit_lgbm(Xtr.loc[tr, cols].values.astype(np.float32), ytr[tr], spec.params)
        imp = pd.Series(m.booster_.feature_importance("gain"), index=cols)
        info = {"gain_share": (imp / imp.sum()).sort_values(ascending=False).round(4).head(15).to_dict(),
                "_model": m, "_cols": cols}
        return m.predict(Xte[cols].values.astype(np.float32)), info
    raise ValueError(spec.kind)


# ------------------------------------------------------------------ evaluation
def evaluate(pred: dict[str, np.ndarray], y: np.ndarray, rank_scores: dict[str, np.ndarray],
             blocks: np.ndarray, n_boot: int = 200, reference: str | None = None, seed: int = 42,
             length: np.ndarray | None = None, pairs: list[tuple[str, str]] = ()):
    """Metrics for every model on the SAME rows; CIs by spatial-block bootstrap.

    `pred` holds count forecasts (for deviance/MAE); `rank_scores` the score
    each method ranks by (a baseline ranks by its raw history count).
    Returns (point estimates, bootstrap summaries incl. paired differences vs `reference`).
    """
    rows, rankers = [], {k: WeightedRanker(s) for k, s in rank_scores.items()}
    ones = np.ones(len(y))
    for k in pred:
        r = {"model": k, "n_rows": int(len(y)), "target_sum": float(y.sum()), **count_metrics(y, pred[k])}
        for f in FRACS:
            r[f"capture_top{int(f*100)}"] = rankers[k].capture(y, ones, f)
        if length is not None:
            for f in (0.01, 0.05, 0.10):
                r[f"capture_km_top{int(f*100)}"] = rankers[k].capture(y, ones, f, size=length)
        rows.append(r)
    point = pd.DataFrame(rows)
    if n_boot <= 0:
        return point, pd.DataFrame()
    samples = {k: {m: [] for m in ["dev", "c5", "c10", "c20"]} for k in pred}
    # per-row deviance contributions and pre-sorted targets are computed once;
    # a replicate is then a weighted mean and a weight gather (same values as
    # weighted_deviance / capture, much less work)
    dev_i = {}
    for k in pred:
        mu = np.clip(np.asarray(pred[k], float), 1e-9, None)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(y > 0, y * np.log(y / mu), 0.0)
        dev_i[k] = 2 * (t - (y - mu))
        rankers[k].prepare(y)
    for w in block_weights(blocks, n_boot, seed):
        sw = w.sum()
        for k in pred:
            samples[k]["dev"].append(float(np.dot(w, dev_i[k]) / sw))
            samples[k]["c5"].append(rankers[k].capture_fast(w, 0.05))
            samples[k]["c10"].append(rankers[k].capture_fast(w, 0.10))
            samples[k]["c20"].append(rankers[k].capture_fast(w, 0.20))
    brow = []
    for k in pred:
        for m, v in samples[k].items():
            v = np.asarray(v)
            r = {"model": k, "metric": m, "ci_low": np.percentile(v, 2.5), "ci_high": np.percentile(v, 97.5)}
            if reference and k != reference:
                d = v - np.asarray(samples[reference][m])
                r.update({"diff_vs_ref_mean": d.mean(), "diff_ci_low": np.percentile(d, 2.5),
                          "diff_ci_high": np.percentile(d, 97.5), "share_diff_le_0": float((d <= 0).mean())})
            brow.append(r)
    for a, b in pairs:                                  # explicit paired comparisons (same resamples)
        if a in samples and b in samples:
            for m in samples[a]:
                d = np.asarray(samples[a][m]) - np.asarray(samples[b][m])
                brow.append({"model": a, "metric": m, "pair_reference": b, "diff_vs_ref_mean": d.mean(),
                             "diff_se": d.std(ddof=1), "diff_ci_low": np.percentile(d, 2.5),
                             "diff_ci_high": np.percentile(d, 97.5), "share_diff_le_0": float((d <= 0).mean())})
    return point, pd.DataFrame(brow)


def national_ksi(coll: pd.DataFrame, w: Window, target=PRIMARY) -> float:
    return float(coll.loc[coll.collision_year.isin(w.years), target].sum())


def run_fold(ctx: Context, fold: Fold, specs: list[Spec], target=PRIMARY, populations=("all",),
             n_boot=200, reference="hist_collisions", spatial_groups: np.ndarray | None = None,
             keep_predictions=False, pairs=()):
    """Fit/score every spec on one fold. Returns dict of DataFrames.

    spatial_groups: if given (array of group labels per segment), each model is
    refitted once per group on the OTHER groups' training rows, and every test
    row is predicted by a model that never saw its group.
    """
    t0 = time.time()
    need_aadf = any(s.exposure for s in specs)
    Xtr = build_frame(ctx.seg, ctx.ac, fold.train_x, fold.train_y, ctx.road,
                      ctx.flows(fold.train_x) if need_aadf else None)
    Xte = build_frame(ctx.seg, ctx.ac, fold.test_x, fold.test_y, ctx.road,
                      ctx.flows(fold.test_x) if need_aadf else None)
    ytr, yte = Xtr[f"y_{target}"].values, Xte[f"y_{target}"].values
    base_rows = ctx.scored.copy()
    if need_aadf:
        # exposure population: M/A segments with AADF in BOTH windows (so train and test align)
        base_rows &= Xtr.log_aadf.notna().values & Xte.log_aadf.notna().values
    log.info("fold %s: %d rows in population, %.0fs to build", fold.cutoff, base_rows.sum(), time.time() - t0)

    preds, infos, rank_scores = {}, {}, {}
    for s in specs:
        t1 = time.time()
        if spatial_groups is None:
            p, info = fit_predict(s, Xtr, ytr, Xte, target, train_rows=base_rows)
        else:
            p = np.full(len(Xte), np.nan); info = {}
            for g in np.unique(spatial_groups[base_rows]):
                tr_rows = base_rows & (spatial_groups != g)
                pg, _ = fit_predict(s, Xtr, ytr, Xte, target, train_rows=tr_rows)
                te = base_rows & (spatial_groups == g)
                p[te] = pg[te]
        preds[s.name] = p
        infos[s.name] = info
        rank_scores[s.name] = Xte[s.score_col].values if s.kind == "baseline" else p
        log.info("  %-22s %.0fs", s.name, time.time() - t1)

    pops = population_masks(ctx, Xte, base_rows, populations)
    out_pt, out_bs, cover = [], [], []
    nat = national_ksi(ctx.coll, fold.test_y, target)
    for pname, mask in pops.items():
        y = yte[mask]
        if y.sum() <= 0:
            continue
        pt, bs = evaluate({k: v[mask] for k, v in preds.items()}, y,
                          {k: v[mask] for k, v in rank_scores.items()}, ctx.blocks[mask],
                          n_boot=n_boot if pname in ("all", "exposure") else 0,
                          reference=reference if reference in preds else None,
                          length=ctx.seg.length_m.values[mask], pairs=pairs)
        for d in (pt, bs):
            if len(d):
                d.insert(0, "population", pname); d.insert(0, "cutoff", fold.cutoff)
                d.insert(1, "target", target)
        out_pt.append(pt); out_bs.append(bs)
        cover.append({"cutoff": fold.cutoff, "target": target, "population": pname,
                      "segments": int(mask.sum()), "km": float(ctx.seg.length_m.values[mask].sum() / 1000),
                      "target_ksi": float(y.sum()), "national_ksi": nat,
                      "share_of_national": float(y.sum() / nat)})
    res = {"metrics": pd.concat(out_pt, ignore_index=True),
           "bootstrap": pd.concat([b for b in out_bs if len(b)], ignore_index=True) if any(len(b) for b in out_bs) else pd.DataFrame(),
           "coverage": pd.DataFrame(cover), "info": infos, "fold": fold.describe()}
    if keep_predictions:
        res["predictions"] = preds; res["Xte"] = Xte; res["yte"] = yte; res["rows"] = base_rows
    log.info("fold %s done in %.1f min", fold.cutoff, (time.time() - t0) / 60)
    return res


def population_masks(ctx, Xte, base_rows, names) -> dict[str, np.ndarray]:
    cls = ctx.seg.road_class.values
    m = {}
    for n in names:
        if n in ("all", "exposure"):
            m[n] = base_rows
        elif n == "numbered":
            m[n] = base_rows & np.isin(cls, ["M", "A", "B"])
        elif n == "hist1":
            m[n] = base_rows & (Xte.h_n_coll.values > 0)
        elif n.startswith("class_"):
            m[n] = base_rows & (cls == n.split("_", 1)[1])
        elif n.startswith("aadf_q"):
            q = int(n[-1])
            la = Xte.log_aadf.values
            qs = np.nanquantile(la[base_rows], [0, .2, .4, .6, .8, 1])
            m[n] = base_rows & (la >= qs[q - 1]) & (la <= qs[q])
    return m
