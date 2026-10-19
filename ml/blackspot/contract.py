"""ML -> backend integration contract for the v2 outputs: field specifications and validators.

One source of truth for three things:
  - data/v2/INTEGRATION_CONTRACT.md (the human contract; a test checks every field here is in it),
  - data/v2/integration_schema_v2.json (machine-readable copy, written by ml/audit/release_manifest.py),
  - validation of a release directory laid out like data/v2/ (ml/audit/validate_contract.py, tests).

Validation reads only the exported files, never the national pipeline, so it runs on the small
fixture set in ml/tests/fixtures/integration/ as well as on the real data/v2/ files. Field
meanings were taken from the generating code (blackspot/outputs.py, features.py, models.py,
aadf.py, network.py, explain.py, stability.py, experiments/single_event_case.py), not from
column names.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

CONTRACT_VERSION = "1.0"
SCORE_VERSION = "v2.0"
MIN_RATE_LENGTH_M = 250.0          # below this the vehicle-km denominator is too small to show a rate
GB_BOUNDS = {"lon": (-8.7, 2.0), "lat": (49.8, 61.0)}          # WGS84, Great Britain incl. islands
SEGMENT_ID_RE = re.compile(r"^(?P<label>[A-Za-z0-9() ]+)-(?P<link>[0-9A-F]{12})-(?P<piece>[0-9]{2,})$")
FILES = {
    "ranked": "road_segments_ranked_v2.csv",
    "top500": "road_segments_top500_v2.json",
    "geojson": "road_segments_top5000_v2.geojson",
    "meta": "road_segments_meta_v2.json",
    "explanations": "extensions/segment_explanations_v2.csv",
    "explanations_map": "extensions/segment_explanations_top5000_v2.json",
    "stability": "extensions/segment_stability_v2.csv",
    "single_event": "extensions/segment_single_event_sensitivity_v2.csv",
}
REQUIRED_FILES = ("ranked", "meta")


@dataclass(frozen=True)
class Field:
    name: str
    type: str                     # int | float | str | bool
    nullable: bool
    meaning: str
    units: str = ""
    null_when: str = ""           # when a nullable field is empty
    allowed: tuple = ()           # closed set of values, if any
    range: tuple = ()             # (min, max), inclusive; None for an open end
    source: str = ""
    identifier: bool = False      # stable identifier (join key)
    changes_between_versions: bool = True


H = "2023-25 history window"
F = "2026-27 forecast"
# ------------------------------------------------------------------ base CSV (and top-500 JSON)
RANKED = [
    Field("rank", "int", False, "national rank among all 1,827,550 scored segments by blackspot_score, highest first; ties broken by segment_id ascending. Gaps occur because only some segments are exported", range=(1, None), source="outputs.assemble"),
    Field("segment_id", "str", False, "segment identifier: <road number or class>-<first 12 hex characters of the first OS Open Roads link identifier>-<piece, at least 2 digits>. Unique in the file", source="network.segment_network", identifier=True, changes_between_versions=False),
    Field("location", "str", False, "display label: road (name) from-to km of stretch run", source="outputs.assemble"),
    Field("road_id", "str", False, "road number (e.g. A23, A1(M), M6 TOLL), or the road class letter C, U or N for unnumbered roads", source="outputs.assemble"),
    Field("km_from", "float", False, "start of the segment along its junction-to-junction stretch (not a milepost)", units="km", range=(0, None), source="network.cut_strokes"),
    Field("km_to", "float", False, "end of the segment along its stretch", units="km", range=(0, None), source="network.cut_strokes"),
    Field("lat", "float", False, "segment midpoint latitude, WGS84 (EPSG:4326), converted from the BNG midpoint; CSV keeps 6 significant digits (about 10 m)", units="degrees", range=GB_BOUNDS["lat"], source="outputs._wgs84"),
    Field("lon", "float", False, "segment midpoint longitude, WGS84 (EPSG:4326)", units="degrees", range=GB_BOUNDS["lon"], source="outputs._wgs84"),
    Field("blackspot_score", "float", False, "PRIMARY SCORE. Expected killed-or-seriously-injured casualties (DfT severity-adjusted) on this segment over 2026 and 2027 combined, forecast by the frozen LightGBM (Poisson) from 2023-25 history. A burden, not a per-vehicle risk. CSV keeps 6 significant digits; order by rank, never by this rounded value", units="expected adjusted KSI casualties, 2-year total (2026-27)", range=(0, None), source="outputs.run_forecast"),
    Field("n_crashes", "int", False, "injury collisions snapped to this segment, all severities", units=f"collisions, {H}", range=(0, None), source="features.history_features (h_n_coll)"),
    Field("n_ksi", "int", False, "collisions whose STATS19 collision_severity is fatal or serious (reported, not adjusted)", units=f"collisions, {H}", range=(0, None), source="h_is_ksi_collision"),
    Field("n_fatal", "int", False, "fatal collisions", units=f"collisions, {H}", range=(0, None), source="h_is_fatal_collision"),
    Field("ksi_rate", "float", True, "n_ksi / n_crashes", units="share", null_when="n_crashes = 0", range=(0, 1), source="outputs.assemble"),
    Field("crashes_per_year", "float", False, "n_crashes / 3", units="collisions per year", range=(0, None), source="outputs.assemble"),
    Field("speed_max", "float", True, "highest speed limit recorded at this segment's collisions", units="mph", null_when="n_crashes = 0", allowed=(20.0, 30.0, 40.0, 50.0, 60.0, 70.0), source="STATS19 speed_limit (codes < 15 dropped)"),
    Field("pct_night", "float", True, "share of collisions between 22:00 and 05:59", units="share", null_when="n_crashes = 0", range=(0, 1), source="STATS19 time"),
    Field("pct_junction", "float", True, "v1 definition kept for compatibility: share with junction_detail != 0. Missing and unknown codes count as junction, and 2024-format roundabouts as non-junction. Use pct_junction_v2", units="share", null_when="n_crashes = 0", range=(0, 1), source="STATS19 junction_detail"),
    Field("future_ksi", "float", True, "always empty: the forecast period has not happened", null_when="always", source="outputs.assemble"),
    Field("future_fatal", "float", True, "always empty", null_when="always", source="outputs.assemble"),
    Field("run", "int", False, "stretch ordinal within road_id, for drawing a road in order only; not a risk feature", range=(0, None), source="network.segment_network"),
    Field("score_version", "str", False, "output version", allowed=(SCORE_VERSION,), source="outputs.SCORE_VERSION"),
    Field("score_model", "str", False, "model behind blackspot_score", allowed=("lgbm",), source="frozen_spec.json"),
    Field("score_definition", "str", False, "plain-text definition of blackspot_score", source="outputs.assemble"),
    Field("forecast_period", "str", False, "years the score forecasts", allowed=("2026-2027",), source="features.Fold(2025).test_y"),
    Field("history_period", "str", False, "years the history columns and model inputs cover", allowed=("2023-2025",), source="features.Fold(2025).test_x"),
    Field("road_class", "str", False, "OS Open Roads class by majority length: M motorway, A, B, C classified unnumbered, U unclassified, N not classified", allowed=("M", "A", "B", "C", "U", "N"), source="network.segment_network"),
    Field("road_number", "str", True, "road number", null_when="unnumbered road (empty cell)", source="OS Open Roads roadNumber"),
    Field("road_name", "str", True, "road name", null_when="unnamed (empty cell)", source="OS Open Roads name1"),
    Field("form_of_way", "str", False, "OS Open Roads formOfWay by majority length", allowed=("Single Carriageway", "Collapsed Dual Carriageway", "Dual Carriageway", "Roundabout", "Slip Road", "Shared Use Carriageway", "Guided Busway", "Layby", "Traffic Island Link", "Traffic Island Link At Junction"), source="OS Open Roads"),
    Field("length_m", "float", False, "planar length of the segment centreline in British National Grid", units="m", range=(0, None), source="network.cut_strokes"),
    Field("os_first_link_id", "str", False, "OS Open Roads RoadLink identifier of the segment's first link: a geometry reference into OS data", source="network.cut_strokes", changes_between_versions=False),
    Field("piece", "int", False, "piece index within the stroke (0-based); the last part of segment_id", range=(0, None), source="network.cut_strokes"),
    Field("pct_junction_v2", "float", True, "share of collisions at a junction: junction_detail in {13, 16, 17, 18, 19} (DfT 2024 coding) or road_type = roundabout", units="share", null_when="n_crashes = 0", range=(0, 1), source="features.assigned_collisions"),
    Field("n_ksi_casualties", "int", False, "killed or seriously injured casualties as reported", units=f"casualties, {H}", range=(0, None), source="casualty table"),
    Field("n_ksi_casualties_adjusted", "float", False, "KSI casualties on DfT's severity-adjusted scale (fatal + adjusted serious probability); the scale of the target", units=f"adjusted casualties, {H}", range=(0, None), source="casualty table"),
    Field("eb_expected_ksi", "float", False, "Empirical Bayes benchmark forecast (not the production score): EB estimate of history KSI x k, where k is the history-to-target scale estimated on the training pair", units=f"expected adjusted KSI casualties, 2-year total ({F})", range=(0, None), source="models.eb_forecast"),
    Field("spf_expected_ksi_history", "float", False, "KSI expected on similar roads (NB2 safety performance function on road attributes; no crash history, no traffic)", units=f"expected adjusted KSI casualties, {H}", range=(0, None), source="models.EmpiricalBayes"),
    Field("eb_ksi_history", "float", False, "EB estimate of this segment's KSI over the history window (weighted mix of SPF and observed)", units=f"adjusted KSI casualties, {H}", range=(0, None), source="models.EmpiricalBayes"),
    Field("eb_excess_ksi_history", "float", False, "eb_ksi_history - spf_expected_ksi_history: KSI above similar roads. Can be negative. A screening signal, not a cause", units=f"adjusted KSI casualties, {H}", source="models.eb_forecast"),
    Field("eb_weight", "float", False, "EB weight on the SPF prior, 1 / (1 + alpha x SPF)", units="share", range=(0, 1), source="models.EmpiricalBayes"),
    Field("aadf", "float", True, "mean annual average daily flow, all motor vehicles, at the matched DfT count point over 2023-25", units="vehicles per day", null_when="exposure_available is false", range=(0, None), source="aadf.window_flows / match_segments"),
    Field("aadf_count_point", "int", True, "DfT count_point_id used for aadf (stored as a float-formatted number in the CSV)", null_when="exposure_available is false", source="aadf.match_segments"),
    Field("aadf_share_counted", "float", True, "share of the count point's 2023-25 AADF years that were counted, not estimated, by DfT", units="share", null_when="exposure_available is false", range=(0, 1), source="aadf.window_flows"),
    Field("exposure_available", "bool", False, "true when a same-number DfT count point matched the segment (motorway and A roads only)", source="outputs.assemble"),
    Field("vehicle_km_history", "float", True, "aadf x 365 x 3 x length_m / 1000", units=f"vehicle-km, {H}", null_when="exposure_available is false", range=(0, None), source="outputs.assemble"),
    Field("ksi_per_100m_vkm_eb", "float", True, "EB-smoothed adjusted KSI per 100 million vehicle-km over the history window (exposure SPF), a per-vehicle risk rate, separate from blackspot_score. Do not display below 250 m length", units=f"adjusted KSI per 100 million vehicle-km, {H}", null_when="exposure_available is false (never imputed)", range=(0, None), source="outputs.run_forecast"),
    Field("eb_excess_ksi_exposure", "float", True, "EB KSI minus the exposure-SPF expectation (similar roads with similar traffic). Can be negative", units=f"adjusted KSI casualties, {H}", null_when="exposure_available is false", source="outputs.run_forecast"),
    Field("data_sufficiency", "str", False, "sufficient: >= 6 collisions; sparse: 1-5; none: 0. Scores for sparse/none lean on road type and neighbours", allowed=("sufficient", "sparse", "none"), source="outputs.assemble"),
    Field("max_single_collision_ksi", "float", False, "largest adjusted KSI from any one collision on the segment (0 when none)", units=f"adjusted KSI casualties, {H}", range=(0, None), source="outputs.assemble"),
    Field("single_event_share", "float", True, "max_single_collision_ksi / n_ksi_casualties_adjusted", units="share", null_when="n_ksi_casualties_adjusted = 0", range=(0, 1), source="outputs.assemble"),
    Field("single_event_flag", "bool", False, "true when one collision supplied >= 5 adjusted KSI and >= 50% of the segment's history KSI (mass-casualty events). Post-hoc annotation; changes no score", source="outputs.assemble"),
    Field("spatial_block", "int", False, "50 km British National Grid square used for spatial validation: floor(E/50000) x 1000 + floor(N/50000). Not an administrative area", source="experiment.block_id", changes_between_versions=False),
]
LEGACY = ["rank", "segment_id", "location", "road_id", "km_from", "km_to", "lat", "lon", "blackspot_score",
          "n_crashes", "n_ksi", "n_fatal", "ksi_rate", "crashes_per_year", "speed_max", "pct_night",
          "pct_junction", "future_ksi", "future_fatal"]
EXPOSURE_COLS = ["aadf", "aadf_count_point", "aadf_share_counted", "vehicle_km_history", "ksi_per_100m_vkm_eb",
                 "eb_excess_ksi_exposure"]
HISTORY_DESCRIPTORS = ["ksi_rate", "speed_max", "pct_night", "pct_junction", "pct_junction_v2"]

# ------------------------------------------------------------------ GeoJSON properties
GEOJSON = [
    Field("rank", "int", False, "as in the CSV", range=(1, None)),
    Field("segment_id", "str", False, "as in the CSV; join key", identifier=True, changes_between_versions=False),
    Field("road_id", "str", False, "as in the CSV"),
    Field("location", "str", False, "as in the CSV"),
    Field("blackspot_score", "float", False, "as in the CSV, rounded to 4 decimals", units="expected adjusted KSI casualties, 2-year total (2026-27)", range=(0, None)),
    Field("eb_excess_ksi_history", "float", True, "as in the CSV, rounded to 4 decimals", units=f"adjusted KSI casualties, {H}", null_when="never in the current file"),
    Field("n_crashes", "int", False, "as in the CSV", range=(0, None)),
    Field("data_sufficiency", "str", False, "as in the CSV", allowed=("sufficient", "sparse", "none")),
    Field("single_event_flag", "bool", False, "as in the CSV"),
]

# ------------------------------------------------------------------ optional extensions
EXPLANATIONS = [
    Field("segment_id", "str", False, "join key to the base CSV", identifier=True, changes_between_versions=False),
    Field("rank", "int", False, "production rank, copied from the base CSV", range=(1, None)),
    Field("contrib_rank", "int", False, "1 = largest absolute attribution for this segment", allowed=(1, 2, 3, 4, 5)),
    Field("feature", "str", False, "model input name (one of the 45 production features)"),
    Field("label", "str", False, "plain-English feature label"),
    Field("group", "str", False, "where the information comes from", allowed=("history", "road", "context")),
    Field("feature_value", "float", True, "raw model input value (log_length is log metres; shares 0-1)", null_when="the model input is missing (e.g. history descriptors with no collisions)"),
    Field("display_value", "str", True, "human-readable value (metres, yes/no, %, mph)", null_when="feature_value is null"),
    Field("shap_log", "float", False, "TreeSHAP attribution in log expected KSI (production model)", units="log expected adjusted KSI"),
    Field("factor", "float", False, "exp(shap_log): multiplies the model baseline; an attribution, not a causal effect", units="multiplicative factor", range=(0, None)),
]
STABILITY = [
    Field("segment_id", "str", False, "join key", identifier=True, changes_between_versions=False),
    Field("rank", "int", False, "production rank", range=(1, None)),
    Field("rank_median", "float", False, "median national rank across 20 spatial-block bootstrap refits", units="rank", range=(1, None)),
    Field("rank_p05", "float", False, "5th percentile rank across the 20 refits (interpolated)", units="rank", range=(1, None)),
    Field("rank_p95", "float", False, "95th percentile rank across the 20 refits (interpolated)", units="rank", range=(1, None)),
    Field("rank_iqr", "float", False, "interquartile range of the refit ranks", units="ranks", range=(0, None)),
    Field("freq_top100", "float", False, "share of the 20 refits ranking the segment in the national top 100 (5% steps)", units="share", range=(0, 1)),
    Field("freq_top1000", "float", False, "share of refits in the top 1,000", units="share", range=(0, 1)),
    Field("freq_top5pct", "float", False, "share of refits in the top 5% (91,377)", units="share", range=(0, 1)),
    Field("freq_top10pct", "float", False, "share of refits in the top 10%", units="share", range=(0, 1)),
    Field("freq_top20pct", "float", False, "share of refits in the top 20%", units="share", range=(0, 1)),
    Field("seed_rank_p05", "float", False, "5th percentile rank across 5 seed-only refits", units="rank", range=(1, None)),
    Field("seed_rank_p95", "float", False, "95th percentile rank across 5 seed-only refits", units="rank", range=(1, None)),
    Field("stability_class", "str", False, "robust top-1000: >= 90% of refits in the top 1,000; borderline top-1000: 50-90%; robust top-5%: otherwise in the top 5% in >= 90%; variable: the rest", allowed=("robust top-1000", "borderline top-1000", "robust top-5%", "variable")),
    Field("window_rank_min", "int", False, "best rank across the 12 historical-window rankings", units="rank", range=(1, None)),
    Field("window_rank_max", "int", False, "worst rank across the 12 historical-window rankings", units="rank", range=(1, None)),
    Field("rank_without_largest_collision", "float", True, "SIMULTANEOUS definition: national rank when every top-1,000 segment loses its own largest 2023-25 collision at once. For 'how much does this one collision matter' use segment_single_event_sensitivity_v2.csv", units="rank", null_when="rank > 1000 (not computed)", range=(1, None)),
]
SINGLE_EVENT = [
    Field("segment_id", "str", False, "join key", identifier=True, changes_between_versions=False),
    Field("rank", "int", False, "production rank (top 1,000 only)", range=(1, 1000)),
    Field("forecast", "float", False, "production blackspot_score, 4 decimals", units="expected adjusted KSI casualties, 2-year total (2026-27)", range=(0, None)),
    Field("forecast_without_largest_collision", "float", False, "the production model's forecast with the segment's largest 2023-25 collision (by adjusted KSI) removed from its own history features; road and context unchanged; no refit. Can be HIGHER than forecast (non-monotone model)", units="expected adjusted KSI casualties, 2-year total (2026-27)", range=(0, None)),
    Field("rank_without_largest_collision_one_at_a_time", "int", False, "national rank if only this segment changed; use this for per-segment wording", units="rank", range=(1, None)),
    Field("rank_without_largest_collision_simultaneous", "int", False, "national rank when all top-1,000 segments change at once (equals rank_without_largest_collision in the stability file)", units="rank", range=(1, None)),
    Field("largest_collision_adj_ksi", "float", False, "adjusted KSI of the removed collision", units="adjusted KSI casualties", range=(0, None)),
    Field("single_event_flag", "bool", False, "copied from the base CSV"),
]
EXPLANATION_JSON_KEYS = {"model", "explains", "how_to_read", "segments"}
SEGMENT_EXPLANATION_KEYS = {"rank", "forecast", "base", "groups", "top"}
TOP_FACTOR_KEYS = {"f", "label", "value", "display", "factor"}


def spec() -> dict:
    """Machine-readable contract (written to data/v2/integration_schema_v2.json)."""
    tables = {"road_segments_ranked_v2.csv": RANKED, "road_segments_top500_v2.json": RANKED,
              "road_segments_top5000_v2.geojson (feature properties)": GEOJSON,
              "extensions/segment_explanations_v2.csv": EXPLANATIONS,
              "extensions/segment_stability_v2.csv": STABILITY,
              "extensions/segment_single_event_sensitivity_v2.csv": SINGLE_EVENT}
    return {"contract_version": CONTRACT_VERSION, "score_version": SCORE_VERSION,
            "join_key": "segment_id", "required_files": [FILES[k] for k in REQUIRED_FILES],
            "min_length_m_for_rate_display": MIN_RATE_LENGTH_M,
            "geojson": {"crs": "WGS84 (EPSG:4326), RFC 7946 [longitude, latitude]; no 'crs' member",
                        "geometry": "LineString, >= 2 distinct positions, 6 decimals"},
            "tables": {k: [asdict(f) for f in v] for k, v in tables.items()}}


# ------------------------------------------------------------------ display rules (UI-facing helpers)
def per_vehicle_rate_for_display(row) -> tuple[float | None, str]:
    """The exposure rate to show, or None with the reason. Never substitutes a value."""
    rate = row.get("ksi_per_100m_vkm_eb")
    if not bool(row.get("exposure_available")) or rate is None or _isnull(rate):
        return None, "no matched DfT traffic count (motorways and A roads only); rate not available"
    if float(row.get("length_m")) < MIN_RATE_LENGTH_M:
        return None, f"segment shorter than {MIN_RATE_LENGTH_M:.0f} m; traffic denominator too small for a reliable rate"
    return float(rate), "ok"


def production_order(df: pd.DataFrame) -> pd.DataFrame:
    """Authoritative order: by `rank`. The CSV score is rounded, so do not re-rank from it."""
    return df.sort_values("rank", kind="mergesort")


def _isnull(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (v is pd.NA)


# ------------------------------------------------------------------ validators (return a list of problems)
def _check_fields(df: pd.DataFrame, fields: list[Field], where: str) -> list[str]:
    errs = []
    names = [f.name for f in fields]
    missing = [c for c in names if c not in df.columns]
    if missing:
        errs.append(f"{where}: missing columns {missing}")
    for f in fields:
        if f.name not in df.columns:
            continue
        s = df[f.name]
        nn = s.dropna()
        if not f.nullable and len(nn) != len(s):
            errs.append(f"{where}.{f.name}: {len(s) - len(nn)} empty values in a non-nullable field")
        if f.type == "int" and len(nn) and not np.all(np.mod(pd.to_numeric(nn, errors="coerce"), 1) == 0):
            errs.append(f"{where}.{f.name}: non-integer values")
        if f.type in ("int", "float") and len(nn) and not pd.api.types.is_numeric_dtype(nn):
            errs.append(f"{where}.{f.name}: not numeric")
        if f.type == "bool" and len(nn) and not set(nn.astype(str).str.lower()) <= {"true", "false"}:
            errs.append(f"{where}.{f.name}: not boolean")
        if f.allowed and len(nn):
            bad = set(nn.unique()) - set(f.allowed)
            if bad:
                errs.append(f"{where}.{f.name}: values outside the allowed set {sorted(map(str, bad))[:5]}")
        if f.range and len(nn) and f.type in ("int", "float"):
            v = pd.to_numeric(nn)
            lo, hi = f.range
            if lo is not None and (v < lo).any():
                errs.append(f"{where}.{f.name}: values below {lo}")
            if hi is not None and (v > hi).any():
                errs.append(f"{where}.{f.name}: values above {hi}")
    return errs


def validate_ranked(df: pd.DataFrame, where="road_segments_ranked_v2.csv") -> list[str]:
    errs = _check_fields(df, RANKED, where)
    if errs and any("missing columns" in e for e in errs):
        return errs
    if list(df.columns[:len(LEGACY)]) != LEGACY:
        errs.append(f"{where}: the 19 v1 columns are not first and in v1 order")
    if not df.segment_id.is_unique:
        errs.append(f"{where}: segment_id not unique")
    if not df["rank"].is_unique:
        errs.append(f"{where}: rank not unique")
    o = production_order(df)
    if not o.blackspot_score.is_monotonic_decreasing:
        errs.append(f"{where}: blackspot_score increases with rank")
    bad_id = ~df.segment_id.astype(str).str.match(SEGMENT_ID_RE)
    if bad_id.any():
        errs.append(f"{where}: {int(bad_id.sum())} segment_id values do not match <label>-<12 hex>-<piece>")
    else:
        parts = df.segment_id.str.extract(SEGMENT_ID_RE)
        if not (parts.piece.astype(int).values == df.piece.astype(int).values).all():
            errs.append(f"{where}: segment_id piece suffix != piece")
        if not (parts.label.values == df.road_id.astype(str).values).all():
            errs.append(f"{where}: segment_id label != road_id")
    noexp = ~df.exposure_available.astype(bool)
    for c in EXPOSURE_COLS:
        if df.loc[noexp, c].notna().any():
            errs.append(f"{where}.{c}: populated where exposure_available is false")
    exp = ~noexp
    if exp.any():
        if df.loc[exp, ["aadf", "ksi_per_100m_vkm_eb"]].isna().any().any():
            errs.append(f"{where}: exposure_available is true but aadf or the rate is empty")
        if not df.loc[exp, "road_class"].isin(["M", "A"]).all():
            errs.append(f"{where}: exposure on a road class other than M/A")
    none = df.n_crashes == 0
    if df.loc[none, HISTORY_DESCRIPTORS].notna().any().any() or df.loc[~none, HISTORY_DESCRIPTORS].isna().any().any():
        errs.append(f"{where}: history descriptors must be empty exactly when n_crashes = 0")
    want = np.select([df.n_crashes >= 6, df.n_crashes >= 1], ["sufficient", "sparse"], "none")
    if not (df.data_sufficiency.values == want).all():
        errs.append(f"{where}: data_sufficiency inconsistent with n_crashes")
    if ((df.n_fatal > df.n_ksi) | (df.n_ksi > df.n_crashes)).any():
        errs.append(f"{where}: n_fatal <= n_ksi <= n_crashes violated")
    if (df.km_to < df.km_from).any():
        errs.append(f"{where}: km_to < km_from")
    fl = df.single_event_flag.astype(bool)
    if ((df.loc[fl, "max_single_collision_ksi"] < 5) | (df.loc[fl, "single_event_share"] < 0.5)).any():
        errs.append(f"{where}: single_event_flag set without meeting its definition")
    return errs


def validate_geojson(obj: dict, base: pd.DataFrame | None = None, where="road_segments_top5000_v2.geojson") -> list[str]:
    errs = []
    if obj.get("type") != "FeatureCollection":
        return [f"{where}: not a FeatureCollection"]
    if "crs" in obj:
        errs.append(f"{where}: has a 'crs' member; RFC 7946 GeoJSON is WGS84 lon/lat without one")
    props, ids = [], []
    for i, f in enumerate(obj.get("features", [])):
        g = f.get("geometry") or {}
        c = np.asarray(g.get("coordinates", []), dtype=float)
        if g.get("type") != "LineString" or c.ndim != 2 or c.shape[0] < 2 or c.shape[1] != 2:
            errs.append(f"{where}[{i}]: geometry is not a LineString of [lon, lat] positions")
            continue
        if not np.isfinite(c).all():
            errs.append(f"{where}[{i}]: non-finite coordinate")
        if len({tuple(x) for x in c.tolist()}) < 2:
            errs.append(f"{where}[{i}]: fewer than 2 distinct positions")
        lo, la = c[:, 0], c[:, 1]
        if not ((lo >= GB_BOUNDS["lon"][0]) & (lo <= GB_BOUNDS["lon"][1]) &
                (la >= GB_BOUNDS["lat"][0]) & (la <= GB_BOUNDS["lat"][1])).all():
            errs.append(f"{where}[{i}]: positions outside Great Britain or in [lat, lon] order")
        props.append(f.get("properties", {}))
        ids.append(f.get("properties", {}).get("segment_id"))
    P = pd.DataFrame(props)
    errs += _check_fields(P, GEOJSON, where)
    if len(set(ids)) != len(ids):
        errs.append(f"{where}: duplicate segment_id")
    if base is not None and len(P):
        b = base.set_index("segment_id")
        unknown = set(ids) - set(b.index)
        if unknown:
            errs.append(f"{where}: {len(unknown)} segment_id not in the base CSV")
        else:
            if not (P.set_index("segment_id")["rank"] == b.loc[ids, "rank"]).all():
                errs.append(f"{where}: rank differs from the base CSV")
    return errs


def validate_explanations(df: pd.DataFrame, base: pd.DataFrame, where="segment_explanations_v2.csv") -> list[str]:
    from .explain import FEATURES
    errs = _check_fields(df, EXPLANATIONS, where)
    if errs and any("missing columns" in e for e in errs):
        return errs
    if not set(df.segment_id) <= set(base.segment_id):
        errs.append(f"{where}: segment_id not in the base CSV")
    n = df.groupby("segment_id").contrib_rank.agg(["count", "nunique", "min", "max"])
    if not ((n["count"] == 5) & (n["nunique"] == 5) & (n["min"] == 1) & (n["max"] == 5)).all():
        errs.append(f"{where}: each segment must have contrib_rank 1..5 exactly once")
    if not set(df.feature) <= set(FEATURES):
        errs.append(f"{where}: unknown feature names {sorted(set(df.feature) - set(FEATURES))[:5]}")
    if not np.allclose(np.exp(df.shap_log), df.factor, rtol=1e-4, atol=1e-6):
        errs.append(f"{where}: factor != exp(shap_log)")
    m = df.drop_duplicates("segment_id").merge(base[["segment_id", "rank"]], on="segment_id", suffixes=("", "_base"))
    if not (m["rank"] == m.rank_base).all():
        errs.append(f"{where}: rank differs from the base CSV")
    return errs


def validate_explanations_map(obj: dict, base: pd.DataFrame, where="segment_explanations_top5000_v2.json") -> list[str]:
    errs = []
    if not EXPLANATION_JSON_KEYS <= set(obj):
        return [f"{where}: missing keys {sorted(EXPLANATION_JSON_KEYS - set(obj))}"]
    b = base.set_index("segment_id")
    for sid, e in obj["segments"].items():
        if sid not in b.index:
            errs.append(f"{where}: {sid} not in the base CSV")
            continue
        if not SEGMENT_EXPLANATION_KEYS <= set(e) or any(not TOP_FACTOR_KEYS <= set(t) for t in e["top"]):
            errs.append(f"{where}: {sid} lacks required keys")
            continue
        if e["rank"] != b.loc[sid, "rank"]:
            errs.append(f"{where}: {sid} rank differs from the base CSV")
        if set(e["groups"]) != {"history", "road", "context"}:
            errs.append(f"{where}: {sid} groups must be history/road/context")
    return errs


def validate_stability(df: pd.DataFrame, base: pd.DataFrame, where="segment_stability_v2.csv") -> list[str]:
    errs = _check_fields(df, STABILITY, where)
    if errs and any("missing columns" in e for e in errs):
        return errs
    if not set(df.segment_id) <= set(base.segment_id) or not df.segment_id.is_unique:
        errs.append(f"{where}: segment_id must be unique and in the base CSV")
    m = df.merge(base[["segment_id", "rank"]], on="segment_id", suffixes=("", "_base"))
    if not (m["rank"] == m.rank_base).all():
        errs.append(f"{where}: rank differs from the base CSV")
    if not ((df.rank_p05 <= df.rank_median + 1e-9) & (df.rank_median <= df.rank_p95 + 1e-9)).all():
        errs.append(f"{where}: rank_p05 <= rank_median <= rank_p95 violated")
    if (df.window_rank_min > df.window_rank_max).any():
        errs.append(f"{where}: window_rank_min > window_rank_max")
    top = df["rank"] <= 1000
    if df.loc[top, "rank_without_largest_collision"].isna().any() or df.loc[~top, "rank_without_largest_collision"].notna().any():
        errs.append(f"{where}: rank_without_largest_collision must be present exactly for rank <= 1000")
    return errs


def validate_single_event(df: pd.DataFrame, base: pd.DataFrame, where="segment_single_event_sensitivity_v2.csv") -> list[str]:
    errs = _check_fields(df, SINGLE_EVENT, where)
    if errs and any("missing columns" in e for e in errs):
        return errs
    if not set(df.segment_id) <= set(base.segment_id) or not df.segment_id.is_unique:
        errs.append(f"{where}: segment_id must be unique and in the base CSV")
    m = df.merge(base[["segment_id", "rank", "single_event_flag"]], on="segment_id", suffixes=("", "_base"))
    if not (m["rank"] == m.rank_base).all():
        errs.append(f"{where}: rank differs from the base CSV")
    if not (m.single_event_flag.astype(bool) == m.single_event_flag_base.astype(bool)).all():
        errs.append(f"{where}: single_event_flag differs from the base CSV")
    return errs


def read_ranked(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def validate_release(root: Path) -> dict[str, list[str]]:
    """Validate a directory laid out like data/v2/. Optional files are validated only if present."""
    root = Path(root)
    out: dict[str, list[str]] = {}
    for k in REQUIRED_FILES:
        if not (root / FILES[k]).exists():
            out[FILES[k]] = ["required file missing"]
    if out:
        return out
    base = read_ranked(root / FILES["ranked"])
    out[FILES["ranked"]] = validate_ranked(base)
    meta = json.loads((root / FILES["meta"]).read_text(encoding="utf-8"))
    errs = []
    for k in ["score_version", "forecast_years", "history_years", "score_definition", "frozen_spec_sha256",
              "n_segments_scored_nationally", "legacy_columns_preserved"]:
        if k not in meta:
            errs.append(f"meta: missing {k}")
    if meta.get("score_version") != SCORE_VERSION:
        errs.append("meta: score_version differs from the contract")
    fy = meta.get("forecast_years", [])
    if fy and base.forecast_period.iloc[0] != f"{fy[0]}-{fy[-1]}":
        errs.append("meta: forecast_years disagree with forecast_period")
    out[FILES["meta"]] = errs
    if (root / FILES["top500"]).exists():
        t = pd.DataFrame(json.loads((root / FILES["top500"]).read_text(encoding="utf-8")))
        e = _check_fields(t, RANKED, FILES["top500"])
        sub = base.set_index("segment_id").loc[t.segment_id]
        if not (sub["rank"].values == t["rank"].values).all():
            e.append(f"{FILES['top500']}: rank differs from the base CSV")
        out[FILES["top500"]] = e
    if (root / FILES["geojson"]).exists():
        out[FILES["geojson"]] = validate_geojson(json.loads((root / FILES["geojson"]).read_text(encoding="utf-8")), base)
    if (root / FILES["explanations"]).exists():
        out[FILES["explanations"]] = validate_explanations(pd.read_csv(root / FILES["explanations"]), base)
    if (root / FILES["explanations_map"]).exists():
        out[FILES["explanations_map"]] = validate_explanations_map(
            json.loads((root / FILES["explanations_map"]).read_text(encoding="utf-8")), base)
    if (root / FILES["stability"]).exists():
        out[FILES["stability"]] = validate_stability(pd.read_csv(root / FILES["stability"]), base)
    if (root / FILES["single_event"]).exists():
        out[FILES["single_event"]] = validate_single_event(pd.read_csv(root / FILES["single_event"]), base)
    return out
