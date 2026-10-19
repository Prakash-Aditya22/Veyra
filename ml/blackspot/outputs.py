"""Production forecast and backend-facing v2 outputs.

Compatibility: every column of the v1 file (data/road_segments_ranked.csv) is
present with its v1 meaning, in its v1 order, first; v2 columns are appended.
v1 files are left untouched. Differences that a consumer must know about are
listed in road_segments_meta_v2.json -> legacy_column_notes.
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from .config import BACKEND_DATA, OUTPUTS
from .io_utils import write_csv, write_json, write_parquet, write_text

log = logging.getLogger("blackspot.outputs")
SCORE_VERSION = "v2.0"
LEGACY_COLS = ["rank", "segment_id", "location", "road_id", "km_from", "km_to", "lat", "lon",
               "blackspot_score", "n_crashes", "n_ksi", "n_fatal", "ksi_rate", "crashes_per_year",
               "speed_max", "pct_night", "pct_junction", "future_ksi", "future_fatal"]
BACKEND_TOP_N = 50_000


def run_forecast(ctx, spec) -> pd.DataFrame:
    """Fit the frozen model on 2021-23 -> 2024-25 and forecast 2026-27 from 2023-25 history."""
    from .experiment import fit_predict, standard_specs
    from .features import FORECAST_CUTOFF, PRIMARY, Fold, build_frame
    from .models import EmpiricalBayes, eb_forecast

    seg = ctx.seg
    fold = Fold(FORECAST_CUTOFF)                  # train_x 2021-23, train_y 2024-25, test_x 2023-25
    Xtr = build_frame(seg, ctx.ac, fold.train_x, fold.train_y, ctx.road, ctx.flows(fold.train_x))
    Xte = build_frame(seg, ctx.ac, fold.test_x, None, ctx.road, ctx.flows(fold.test_x))
    ytr = Xtr[f"y_{PRIMARY}"].values
    chosen = [s for s in standard_specs(spec["lgbm_params"]) if s.name == spec["selected_model"]][0]
    score, info = fit_predict(chosen, Xtr, ytr, Xte, PRIMARY)
    eb = eb_forecast(Xtr, Xtr[f"h_{PRIMARY}"].values, ytr, Xte, Xte[f"h_{PRIMARY}"].values)

    # exposure: an SPF with log AADF, on M/A segments with a matched count point only
    fl = ctx.flows(fold.test_x)
    has = Xte.log_aadf.notna().values
    eb_x = {"eb": np.full(len(seg), np.nan), "spf": np.full(len(seg), np.nan)}
    expo_info = {}
    if has.sum() > 1000:
        e = EmpiricalBayes(exposure=True).fit_spf(Xte[has], Xte[f"h_{PRIMARY}"].values[has])
        m, mu, _ = e.posterior(Xte[has], Xte[f"h_{PRIMARY}"].values[has])
        eb_x["eb"][has], eb_x["spf"][has] = m, mu
        expo_info = {"alpha": e.glm.alpha, "coef": dict(zip(["intercept"] + e.design.names,
                                                             np.round(e.glm.coef_, 4)))}
    out = assemble(seg, ctx, Xte, score, eb, eb_x, fl, fold, spec)
    write_parquet(out, OUTPUTS / "road_segments_v2_full.parquet")
    write_backend_files(out, ctx, fold, spec)
    write_json({"selected_model": spec["selected_model"], "eb_k": eb["k"], "eb_alpha": eb["alpha"],
                "eb_spf_coef": eb["spf_coef"], "exposure_spf": expo_info,
                "model_info": {k: v for k, v in info.items() if not k.startswith("_")}},
               OUTPUTS / "forecast_model_info.json")
    return out


def _wgs84(e, n):
    from pyproj import Transformer
    t = Transformer.from_crs(27700, 4326, always_xy=True)
    lon, lat = t.transform(np.asarray(e, float), np.asarray(n, float))
    return lat, lon


def assemble(seg, ctx, X, score, eb, eb_x, fl, fold, spec) -> pd.DataFrame:
    hist = fold.test_x
    n = len(seg)
    ac = ctx.ac[ctx.ac.collision_year.isin(hist.years)]
    lat, lon = _wgs84(seg.mid_e, seg.mid_n)
    name = seg.road_name.fillna("")
    o = pd.DataFrame({"segment_id": seg.segment_id.values})
    o["road_id"] = np.where(seg.road_number.fillna("") != "", seg.road_number.fillna(""), seg.road_class)
    o["location"] = (o.road_id + np.where(name != "", " (" + name + ")", "") + " "
                     + (seg.from_m / 1000).round(1).astype(str).values + "-"
                     + (seg.to_m / 1000).round(1).astype(str).values
                     + " km of stretch " + seg.run.astype(str).values)
    o["km_from"] = (seg.from_m.values / 1000).round(3)
    o["km_to"] = (seg.to_m.values / 1000).round(3)
    o["lat"], o["lon"] = lat, lon
    o["blackspot_score"] = score
    # legacy history columns, v1 meanings: collisions, KSI collisions, fatal collisions
    o["n_crashes"] = X.h_n_coll.values.astype(int)
    o["n_ksi"] = X.h_is_ksi_collision.values.astype(int)
    o["n_fatal"] = X.h_is_fatal_collision.values.astype(int)
    o["ksi_rate"] = np.where(o.n_crashes > 0, o.n_ksi / o.n_crashes.clip(lower=1), np.nan)
    o["crashes_per_year"] = o.n_crashes / len(hist.years)
    o["speed_max"] = ac.groupby("seg_idx").speed.max().reindex(range(n)).values
    night = (ac.hour >= 22) | (ac.hour <= 5)
    o["pct_night"] = night.groupby(ac.seg_idx).mean().reindex(range(n)).values
    jd = pd.to_numeric(ac.junction_detail, errors="coerce")
    o["pct_junction"] = (jd != 0).groupby(ac.seg_idx).mean().reindex(range(n)).values
    o["future_ksi"] = np.nan          # the forecast period has not happened
    o["future_fatal"] = np.nan
    # ---- v2 additions
    o["run"] = seg.run.values
    o["score_version"] = SCORE_VERSION
    o["score_model"] = spec["selected_model"]
    o["score_definition"] = ("expected KSI casualties (DfT severity-adjusted) on this segment, "
                             f"{fold.test_y.start}-{fold.test_y.end}")
    o["forecast_period"] = str(fold.test_y)
    o["history_period"] = str(hist)
    o["road_class"] = seg.road_class.values
    o["road_number"] = seg.road_number.fillna("").values
    o["road_name"] = name.values
    o["form_of_way"] = seg.form_of_way.values
    o["length_m"] = seg.length_m.round(1).values
    o["os_first_link_id"] = seg.first_link.values
    o["piece"] = seg.piece.values
    o["pct_junction_v2"] = X.h_share_junction.values     # junction codes 13-19 or roundabout road type
    o["n_ksi_casualties"] = X.h_n_ksi_cas.values.astype(int)
    o["n_ksi_casualties_adjusted"] = X.h_adj_ksi_cas.values.round(3)
    o["eb_expected_ksi"] = eb["forecast"]
    o["spf_expected_ksi_history"] = eb["spf_history"]
    o["eb_ksi_history"] = eb["eb_history"]
    o["eb_excess_ksi_history"] = eb["excess_history"]
    o["eb_weight"] = eb["weight"]
    o["aadf"] = fl.aadf.values
    o["aadf_count_point"] = fl.aadf_count_point.values
    o["aadf_share_counted"] = fl.aadf_share_counted.values
    o["exposure_available"] = fl.aadf.notna().values
    vkm = fl.aadf.values * 365.0 * len(hist.years) * seg.length_m.values / 1000.0
    o["vehicle_km_history"] = vkm
    o["ksi_per_100m_vkm_eb"] = eb_x["eb"] / vkm * 1e8
    o["eb_excess_ksi_exposure"] = eb_x["eb"] - eb_x["spf"]
    o["data_sufficiency"] = np.select([o.n_crashes >= 6, o.n_crashes >= 1], ["sufficient", "sparse"], "none")
    # One mass-casualty collision (a coach crash, the May 2025 Liverpool parade incident) can
    # dominate a segment's history and lift its forecast without saying anything about the road.
    mx = ac.groupby("seg_idx").adj_ksi_cas.max().reindex(range(n)).fillna(0).values
    hist_ksi = X.h_adj_ksi_cas.values.astype(float)
    o["max_single_collision_ksi"] = np.round(mx, 3)
    o["single_event_share"] = np.where(hist_ksi > 0, mx / np.where(hist_ksi > 0, hist_ksi, 1), np.nan)
    o["single_event_flag"] = (mx >= 5) & (o.single_event_share.fillna(0).values >= 0.5)
    o["spatial_block"] = ctx.blocks
    o = o.sort_values(["blackspot_score", "segment_id"], ascending=[False, True]).reset_index(drop=True)
    o.insert(0, "rank", np.arange(1, len(o) + 1))
    return o


def write_backend_files(out: pd.DataFrame, ctx, fold, spec) -> None:
    d = BACKEND_DATA / "v2"
    d.mkdir(parents=True, exist_ok=True)
    # The national table (every scored segment) is regenerable and too large for git.
    # The backend file holds the top 50,000 by score plus every segment with >= 6
    # crashes in the history window (the threshold below which scores are noisy).
    keep = (out["rank"] <= BACKEND_TOP_N) | (out.n_crashes >= 6)
    sub = out[keep]
    extra = [c for c in out.columns if c not in LEGACY_COLS]
    cols = LEGACY_COLS + extra
    write_csv(sub[cols], d / "road_segments_ranked_v2.csv", float_format="%.6g")
    write_text(sub[cols].head(500).to_json(orient="records", indent=1), d / "road_segments_top500_v2.json")
    meta = {
        "score_version": SCORE_VERSION,
        "segment_length_target_m": 500,
        "segmentation": "OS Open Roads centrelines (2026-04 release); junction-to-junction strokes of one "
                        "road cut into round(L/500) equal pieces; independent of crash data",
        "history_years": fold.test_x.years, "forecast_years": fold.test_y.years,
        "model": spec["selected_model"], "frozen_spec_sha256": spec["sha256"],
        "score_definition": out.score_definition.iloc[0],
        "n_segments_scored_nationally": int(len(out)), "n_rows_in_this_file": int(len(sub)),
        "selection_of_rows": f"rank <= {BACKEND_TOP_N} or n_crashes >= 6 (history window)",
        "legacy_columns_preserved": LEGACY_COLS,
        "legacy_column_notes": {
            "segment_id": "new v2 identifiers (network-based, stable for a network release); "
                          "v1 IDs are not comparable",
            "location": "road, name, distance along the junction-to-junction stretch",
            "n_crashes": "collisions in the history window",
            "n_ksi": "KSI collisions in the history window (v1 meaning); casualties in n_ksi_casualties*",
            "n_fatal": "fatal collisions in the history window (v1 meaning)",
            "pct_junction": "share of history crashes with junction_detail != 0 (v1 definition; roundabouts "
                            "count as non-junction under the 2024 coding); corrected value: pct_junction_v2",
            "future_ksi, future_fatal": "empty: the forecast period has not happened; holdout outcomes "
                                        "are in ml/reports/model_comparison.csv",
            "run": "stretch ordinal within road_id (drawing order only); not a risk feature",
            "km_from, km_to": "distance along the OS stretch, not an official milepost",
            "blackspot_score": "now expected KSI CASUALTIES (severity-adjusted) for the next two years; "
                               "v1 was an in-sample fit of KSI COLLISIONS"},
        "columns_needing_care": {
            "eb_excess_ksi_history": "expected KSI above similar roads (SPF without traffic) over the history "
                                     "window; a screening signal, not a cause",
            "ksi_per_100m_vkm_eb, eb_excess_ksi_exposure": "only where exposure_available (M/A roads with a "
                                                           "matched DfT count point)",
            "data_sufficiency": "'sufficient' = >= 6 crashes in the history window; grey out others in the UI",
            "single_event_flag": "true when one collision supplied >= 5 KSI casualties and >= 50% of the "
                                 "segment's history KSI (mass-casualty events, e.g. the May 2025 Liverpool "
                                 "parade incident on Water Street); label such segments, do not present them "
                                 "as road-design blackspots"},
    }
    write_json(meta, d / "road_segments_meta_v2.json")
    write_geojson(sub.head(5000), d / "road_segments_top5000_v2.geojson")


def write_geojson(rows: pd.DataFrame, path) -> None:
    from pyproj import Transformer
    from . import network
    seg_all, verts, off = network.load_segments()
    pos = pd.Series(np.arange(len(seg_all)), index=seg_all.segment_id.values)
    t = Transformer.from_crs(27700, 4326, always_xy=True)
    feats = []
    for r in rows.itertuples(index=False):
        i = int(pos[r.segment_id])
        xy = verts[off[i]:off[i + 1]]
        lon, lat = t.transform(xy[:, 0], xy[:, 1])
        exc = getattr(r, "eb_excess_ksi_history")
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString",
                                   "coordinates": [[round(float(a), 6), round(float(b), 6)] for a, b in zip(lon, lat)]},
                      "properties": {"rank": int(r.rank), "segment_id": r.segment_id, "road_id": r.road_id,
                                     "location": r.location, "blackspot_score": round(float(r.blackspot_score), 4),
                                     "eb_excess_ksi_history": None if pd.isna(exc) else round(float(exc), 4),
                                     "n_crashes": int(r.n_crashes), "data_sufficiency": r.data_sufficiency,
                                     "single_event_flag": bool(r.single_event_flag)}})
    write_text(json.dumps({"type": "FeatureCollection", "features": feats}), path)
