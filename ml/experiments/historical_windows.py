"""Phase 2: does more (or less, or re-weighted) history help prospective blackspot prediction?

    .venv/Scripts/python ml/experiments/historical_windows.py            (~2-3 h, background)
    .venv/Scripts/python ml/experiments/historical_windows.py --cutoffs 2021 --strategies REF_recent3_single

Every strategy is LightGBM with the FROZEN v2 hyperparameters and the same 45
inference features (history + road + context); only the history window used
to build predictors and/or the set of training pairs changes. All strategies at
a cutoff are scored on the same 1.83 M segments against the same two-year
adjusted-KSI target.

Roles of cutoffs (decided before running):
  2019, 2020, 2021  development  -> conclusions and the decay half-life choice
  2022, 2023        exploratory  -> targets 2023-24 / 2024-25 were ALREADY examined in v2;
                                    reported for robustness only, never used to choose
  2025              forecast     -> 2026-27 rankings for the ranking-sensitivity study (no target)

Outputs: ml/reports/historical_window_results.csv, historical_window_bootstrap.csv,
historical_window_calibration.csv, historical_window_context.csv; per-cutoff
checkpoints and forecast predictions in ml/interim/windows/.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import INTERIM, REPORTS  # noqa: E402
from blackspot.evaluation import calibration_table  # noqa: E402
from blackspot.experiment import _cols, evaluate, national_ksi  # noqa: E402
from blackspot.features import PRIMARY, Window  # noqa: E402
from blackspot.io_utils import setup_logging, write_csv, write_json  # noqa: E402
from blackspot.models import fit_lgbm  # noqa: E402
from blackspot.steps import _context, _load_frozen  # noqa: E402
from blackspot.windows import History, frame, strategies, training_target_ends  # noqa: E402

log = logging.getLogger("blackspot.windows_exp")
OUT = INTERIM / "windows"
ROLES = {2019: "development", 2020: "development", 2021: "development",
         2022: "exploratory", 2023: "exploratory", 2025: "forecast"}
GROUPS = ("history", "road", "context")


def regions_for(ctx) -> np.ndarray:
    import zipfile
    from scipy.spatial import cKDTree
    from blackspot.aadf import AADF_ZIP
    with zipfile.ZipFile(AADF_ZIP) as z, z.open("dft_traffic_counts_aadf.csv") as fh:
        cp = pd.read_csv(fh, usecols=["count_point_id", "region_name", "easting", "northing"]).drop_duplicates(
            "count_point_id")
    tree = cKDTree(cp[["easting", "northing"]].values)
    _, j = tree.query(np.column_stack([ctx.seg.mid_e.values, ctx.seg.mid_n.values]))
    return cp.region_name.values[j]


def run_cutoff(ctx, c, strats, params, regions, n_boot=200):
    role = ROLES[c]
    test_y = None if role == "forecast" else [c + 1, c + 2]
    seg, ac, road = ctx.seg, ctx.ac, ctx.road
    cache: dict = {}

    def get(history, k, ty):
        key = (history.label(), k, tuple(ty) if ty else None)
        if key not in cache:
            cache[key] = frame(seg, ac, road, history, k, ty)
        return cache[key]

    ref_test = get(History("recent", 3), c, test_y)
    cols = _cols(ref_test, GROUPS)
    preds, meta = {}, []
    for s in strats:
        ends = training_target_ends(s.pairs, c, s.history)
        if not ends or not s.history.feasible(c):
            meta.append({"cutoff": c, "strategy": s.name, "feasible": False})
            log.info("cutoff %s %-28s not feasible", c, s.name)
            continue
        t0 = time.time()
        parts = [get(s.history, e - 2, [e - 1, e]) for e in ends]
        Xtr = pd.concat([p[cols] for p in parts], ignore_index=True)
        ytr = np.concatenate([p[f"y_{PRIMARY}"].values for p in parts])
        m = fit_lgbm(Xtr.values.astype(np.float32), ytr, params)
        Xte = get(s.history, c, test_y)
        preds[s.name] = m.predict(Xte[cols].values.astype(np.float32))
        yw = s.history.years_weights(c)
        meta.append({"cutoff": c, "strategy": s.name, "feasible": True, "group": s.group,
                     "history_rule": s.history.label(), "pair_rule": s.pairs,
                     "predictor_years_test": f"{min(yw)}-{max(yw)}" + (" excl 2020-21" if "nocovid" in s.history.kind else ""),
                     "n_predictor_years_test": len(yw),
                     "training_target_windows": ";".join(f"{e-1}-{e}" for e in ends),
                     "training_predictor_years": ";".join(
                         f"{min(s.history.years_weights(e - 2))}-{max(s.history.years_weights(e - 2))}" for e in ends),
                     "n_training_rows": int(len(ytr)), "fit_seconds": round(time.time() - t0, 1)})
        log.info("cutoff %s %-28s pairs=%s rows=%d %.0fs", c, s.name, ends, len(ytr), time.time() - t0)
        del Xtr, ytr, m
    if role == "forecast":
        np.savez_compressed(OUT / f"forecast_preds_{c}.npz",
                            segment_id=np.array(seg.segment_id.tolist(), dtype=f"U{seg.segment_id.str.len().max()}"),
                            **{k: v.astype(np.float32) for k, v in preds.items()})
        return pd.DataFrame(meta), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    y = ref_test[f"y_{PRIMARY}"].values
    hist3 = ref_test.h_n_coll.values
    preds_all = dict(preds)
    preds_all["hist_collisions"] = hist3                         # ranking baseline (3-yr counts)
    # count forecast for the baseline: scale by the REF training pair ratio
    ref_tr = get(History("recent", 3), c - 2, [c - 1, c])
    k = ref_tr[f"y_{PRIMARY}"].sum() / max(ref_tr.h_n_coll.sum(), 1e-9)
    counts_fc = hist3 * k
    cls = seg.road_class.values
    pops = {"all": np.ones(len(seg), bool), "hist0": hist3 == 0, "hist1": hist3 > 0,
            "numbered": np.isin(cls, ["M", "A", "B"])}
    for cl in ["M", "A", "B", "C", "U", "N"]:
        pops[f"class_{cl}"] = cls == cl
    for r in sorted(set(regions)):
        pops[f"region_{r}"] = regions == r
    nat = national_ksi(ctx.coll, Window(c + 1, c + 2), PRIMARY)
    names = list(preds)
    pairs = [(n, "REF_recent3_single") for n in names if n != "REF_recent3_single"] + \
            [(n, "hist_collisions") for n in names]
    rows, boots, cal = [], [], []
    for pname, mask in pops.items():
        if y[mask].sum() <= 0:
            continue
        nb = n_boot if pname in ("all", "hist0", "hist1", "numbered") else 0
        pt, bs = evaluate({**{n: preds[n][mask] for n in names}, "hist_collisions": counts_fc[mask]},
                          y[mask], {n: preds_all[n][mask] for n in preds_all}, ctx.blocks[mask],
                          n_boot=nb, reference=None, length=seg.length_m.values[mask], pairs=pairs)
        pt.insert(0, "population", pname)
        pt["population_segments"] = int(mask.sum())
        pt["population_share_of_national_ksi"] = float(y[mask].sum() / nat)
        rows.append(pt)
        if len(bs):
            bs.insert(0, "population", pname)
            boots.append(bs)
    for n in names:
        t = calibration_table(y, preds[n]); t.insert(0, "strategy", n); cal.append(t)
    R = pd.concat(rows, ignore_index=True).rename(columns={"model": "strategy"})
    B = pd.concat(boots, ignore_index=True).rename(columns={"model": "strategy"}) if boots else pd.DataFrame()
    C = pd.concat(cal, ignore_index=True)
    for d in (R, B, C):
        if len(d):
            d.insert(0, "role", role); d.insert(0, "cutoff", c)
    return pd.DataFrame(meta), R, B, C


def context_table(ctx) -> pd.DataFrame:
    """COVID-era mobility and reporting context by year (all from local data)."""
    import zipfile
    from blackspot.aadf import AADF_ZIP, MAJOR_CATEGORIES
    with zipfile.ZipFile(AADF_ZIP) as z, z.open("dft_traffic_counts_aadf.csv") as fh:
        a = pd.read_csv(fh, usecols=["count_point_id", "year", "road_category", "link_length_km",
                                     "all_motor_vehicles", "estimation_method"])
    a = a[a.road_category.isin(MAJOR_CATEGORIES)]
    # a balanced panel of major-road links present in every year 2015-2025
    yrs = list(range(2015, 2026))
    panel = a[a.year.isin(yrs)].groupby("count_point_id").year.nunique()
    keep = panel[panel == len(yrs)].index
    p = a[a.count_point_id.isin(keep) & a.year.isin(yrs)]
    vkm = (p.all_motor_vehicles * p.link_length_km * 365).groupby(p.year).sum()
    counted = (p.estimation_method == "Counted").groupby(p.year).mean()
    c = ctx.coll
    t = pd.DataFrame({"major_road_vkm_index_2019_100": (vkm / vkm.loc[2019] * 100).round(1),
                      "share_aadf_counted": counted.round(3),
                      "collisions": c.groupby("collision_year").size(),
                      "adj_ksi_casualties": c.groupby("collision_year").adj_ksi_cas.sum().round(0),
                      "reported_ksi_casualties": c.groupby("collision_year").n_ksi_cas.sum()})
    t["adj_over_reported"] = (t.adj_ksi_casualties / t.reported_ksi_casualties).round(3)
    t["adj_ksi_per_bn_major_vkm_index"] = (t.adj_ksi_casualties / t.major_road_vkm_index_2019_100).round(1)
    t.attrs["n_panel_links"] = int(len(keep))
    return t.reset_index().rename(columns={"index": "year"})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoffs", nargs="*", type=int, default=[2019, 2020, 2021, 2022, 2023, 2025])
    ap.add_argument("--strategies", nargs="*", default=None)
    ap.add_argument("--n-boot", type=int, default=200)
    ap.add_argument("--fresh", action="store_true", help="ignore checkpoints")
    args = ap.parse_args(argv)
    setup_logging()
    OUT.mkdir(parents=True, exist_ok=True)
    spec = _load_frozen()
    params = spec["lgbm_params"]
    strats = [s for s in strategies() if args.strategies is None or s.name in args.strategies]
    ctx = _context(with_aadf=True)
    regions = regions_for(ctx)
    ctxt = context_table(ctx)
    write_csv(ctxt, REPORTS / "historical_window_context.csv")
    for c in args.cutoffs:
        ck = OUT / f"cutoff_{c}.pkl"
        if ck.exists() and not args.fresh:
            log.info("cutoff %s: checkpoint exists, skipping", c)
            continue
        t0 = time.time()
        res = run_cutoff(ctx, c, strats, params, regions, n_boot=args.n_boot)
        pd.to_pickle(res, ck)
        log.info("cutoff %s done in %.1f min", c, (time.time() - t0) / 60)
    # assemble everything checkpointed so far
    M, R, B, C = [], [], [], []
    for c in sorted(ROLES):
        ck = OUT / f"cutoff_{c}.pkl"
        if ck.exists():
            m, r, b, cal = pd.read_pickle(ck)
            M.append(m); R.append(r); B.append(b); C.append(cal)
    meta = pd.concat(M, ignore_index=True)
    res = pd.concat([r for r in R if len(r)], ignore_index=True)
    res = res.merge(meta.drop(columns=["feasible"], errors="ignore"), on=["cutoff", "strategy"], how="left")
    res["frozen_spec_sha256"] = spec["sha256"]
    write_csv(res, REPORTS / "historical_window_results.csv")
    write_csv(pd.concat([b for b in B if len(b)], ignore_index=True), REPORTS / "historical_window_bootstrap.csv")
    write_csv(pd.concat([c for c in C if len(c)], ignore_index=True), REPORTS / "historical_window_calibration.csv")
    write_csv(meta, REPORTS / "historical_window_design.csv")
    write_json({"roles": ROLES, "lgbm_params": params, "features": "history+road+context (45, as v2)",
                "n_boot": args.n_boot}, REPORTS / "historical_window_config.json")
    log.info("written results for cutoffs %s", sorted(res.cutoff.unique()))


if __name__ == "__main__":
    main()
