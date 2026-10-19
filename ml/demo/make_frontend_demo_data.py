"""Build the compact Great Britain demo bundle that the React frontend loads in local mode.

    .venv/Scripts/python ml/demo/make_frontend_demo_data.py --out <frontend>/public/data/demo-v2
    .venv/Scripts/python ml/demo/make_frontend_demo_data.py --out <dir> --top 5000     (bigger, do not commit)

Source of truth: the v2 release in data/v2/ (INTEGRATION_CONTRACT.md). The script refuses to
run if the release fails the contract validator or its files no longer match
release_manifest_v2.json. Every value is copied from a release record: CSV fields as parsed
from the CSV text, GeoJSON features and explanation objects unchanged. Nothing is computed
except the documented selection, rank tiers and counts.

Selection (deterministic, recorded in manifest.json):
  - the national top N segments by `rank` (default 1,000), complete;
  - plus the reference cases of the integration fixture (ml/tests/fixtures/integration) that
    fall outside the top N: no history, sparse history, a tied pair, rank 50,000, the
    lowest-ranked exported row, a segment outside the line-geometry file.
Line geometry exists only for ranks <= 5,000 (the release GeoJSON); others get a midpoint.

Files written: manifest.json, segments.json, geometry.geojson, explanations.json,
stability.json, single_event.json, context.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot import contract  # noqa: E402
from blackspot.config import BACKEND_DATA, ML_DIR, REPO, REPORTS  # noqa: E402
from blackspot.io_utils import atomic_path, file_hash  # noqa: E402

V2 = BACKEND_DATA / "v2"
FIXTURE = ML_DIR / "tests" / "fixtures" / "integration" / "fixture_manifest.json"
F = contract.FILES
BUNDLE_VERSION = 1
# Fields the UI reads, under their contract names (INTEGRATION_CONTRACT.md 2.1). Release-wide
# constants (score_version, forecast_period, history_period, score_definition) go into
# manifest.json once, after checking they are constant across the release.
SEGMENT_FIELDS = ["rank", "segment_id", "location", "road_id", "road_class", "road_number", "road_name",
                  "form_of_way", "length_m", "lat", "lon", "blackspot_score", "n_crashes", "n_ksi", "n_fatal",
                  "n_ksi_casualties", "n_ksi_casualties_adjusted", "speed_max", "pct_night", "pct_junction_v2",
                  "eb_expected_ksi", "eb_excess_ksi_history", "exposure_available", "aadf", "aadf_share_counted",
                  "ksi_per_100m_vkm_eb", "data_sufficiency", "max_single_collision_ksi", "single_event_share",
                  "single_event_flag"]
CONSTANT_FIELDS = ["score_version", "score_model", "score_definition", "forecast_period", "history_period"]
EXPLANATION_FIELDS = ["contrib_rank", "feature", "label", "group", "display_value", "shap_log", "factor"]
STABILITY_FIELDS = ["rank_median", "rank_p05", "rank_p95", "freq_top100", "freq_top1000", "freq_top5pct",
                    "stability_class", "window_rank_min", "window_rank_max"]
SINGLE_EVENT_FIELDS = ["forecast_without_largest_collision", "rank_without_largest_collision_one_at_a_time",
                       "rank_without_largest_collision_simultaneous", "largest_collision_adj_ksi"]


def write_text(text: str, dest: Path) -> None:
    """LF line endings on every platform: the frontend branch stores text as LF (.gitattributes),
    so CRLF bytes would no longer match the hashes recorded in manifest.json after a commit."""
    with atomic_path(dest) as tmp:
        tmp.write_bytes(text.encode("utf-8"))


def _clean(v):
    """CSV value -> JSON value: NaN -> null, numpy scalars -> Python."""
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in r.items()} for r in df.to_dict(orient="records")]


def top1pct_cutoff(n_national: int) -> int:
    """National top-1% cutoff rank: 1% of all scored segments, rounded DOWN (floor), so the group
    never holds more than 1% of segments. 1,827,550 segments -> floor(18,275.5) = 18,275."""
    return n_national // 100


def tiers(n_national: int) -> list[dict]:
    """Rank groups for the UI legend: four contiguous, mutually exclusive bands of national rank
    (one per colour of the design system's four-colour ramp). Labels state the exact ranks, so
    no group reads as containing another. Boundaries are published, fixed, never rescaled per
    view. The 1,000 boundary is the tier the stability analysis found robust
    (ranking_stability.md). Keys are internal identifiers, not display text."""
    t1 = top1pct_cutoff(n_national)
    if t1 <= 1000:
        raise ValueError("top-1% cutoff must exceed rank 1,000 for these groups")
    f = "{:,}".format
    return [
        {"key": "top100", "min_rank": 1, "max_rank": 100, "label": "Ranks 1–100", "short": "1–100",
         "description": "the national top 100"},
        {"key": "top1000", "min_rank": 101, "max_rank": 1000, "label": "Ranks 101–1,000", "short": "101–1,000",
         "description": "the rest of the national top 1,000"},
        {"key": "top1pct", "min_rank": 1001, "max_rank": t1, "label": f"Ranks 1,001–{f(t1)}", "short": f"1,001–{f(t1)}",
         "description": "the rest of the national top 1%"},
        {"key": "below1pct", "min_rank": t1 + 1, "max_rank": n_national, "label": f"Ranks {f(t1 + 1)}–{f(n_national)}",
         "short": f"{f(t1 + 1)}+", "description": "all remaining scored segments"},
    ]


def git_head() -> dict:
    def run(*a):
        return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True).stdout.strip()
    untracked = run("status", "--porcelain", "--", "data/v2")
    return {"ml_branch": run("rev-parse", "--abbrev-ref", "HEAD"), "ml_head": run("rev-parse", "HEAD"),
            "release_files_committed": not bool(untracked)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--top", type=int, default=1000)
    args = ap.parse_args(argv)

    problems = {k: v for k, v in contract.validate_release(V2).items() if v}
    if problems:
        raise SystemExit(f"release fails the contract: {problems}")
    rel = json.loads((V2 / "release_manifest_v2.json").read_text(encoding="utf-8"))
    for f in rel["files"]:
        if f.get("present") and file_hash(REPO / f["path"]) != f["sha256"]:
            raise SystemExit(f"{f['path']} no longer matches release_manifest_v2.json; rerun ml/audit/release_manifest.py")
    meta = json.loads((V2 / F["meta"]).read_text(encoding="utf-8"))
    n_nat = int(meta["n_segments_scored_nationally"])

    base = pd.read_csv(V2 / F["ranked"], low_memory=False)
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case_of: dict[str, list[str]] = {}
    for c in fx["cases"]:
        for s in c["segments"]:
            case_of.setdefault(s["segment_id"], []).append(c["case"])
    top = set(base.loc[base["rank"] <= args.top, "segment_id"])
    ref = set(case_of) - top
    constants = {}
    for c in CONSTANT_FIELDS:
        if base[c].nunique() != 1:
            raise SystemExit(f"{c} is not constant across the release")
        constants[c] = base[c].iloc[0]
    keep = base[base.segment_id.isin(top | ref)].sort_values("rank")[SEGMENT_FIELDS].copy()
    keep["demo_stratum"] = keep.segment_id.map(lambda s: f"top_{args.top}" if s in top else "reference_case")
    keep["reference_cases"] = keep.segment_id.map(lambda s: case_of.get(s, []))
    ids = set(keep.segment_id)

    gj = json.loads((V2 / F["geojson"]).read_text(encoding="utf-8"))
    # geometry unchanged; properties reduced to the join key (the rest is in segments.json)
    feats = [{"type": "Feature", "geometry": f["geometry"], "properties": {"segment_id": f["properties"]["segment_id"]}}
             for f in gj["features"] if f["properties"]["segment_id"] in ids]
    expl = pd.read_csv(V2 / F["explanations"])
    expl = expl[expl.segment_id.isin(ids)].sort_values(["rank", "contrib_rank"])
    emap = json.loads((V2 / F["explanations_map"]).read_text(encoding="utf-8"))
    explanations = {}
    for sid, g in expl.groupby("segment_id", sort=False):
        e = {"top": records(g[EXPLANATION_FIELDS])}
        if sid in emap["segments"]:
            m = emap["segments"][sid]
            e.update({"base": m["base"], "groups": m["groups"]})
        explanations[sid] = e
    stab = pd.read_csv(V2 / F["stability"])
    stab = {r.pop("segment_id"): r for r in records(stab[stab.segment_id.isin(ids)][["segment_id"] + STABILITY_FIELDS])}
    se = pd.read_csv(V2 / F["single_event"])
    se = {r.pop("segment_id"): r for r in records(se[se.segment_id.isin(ids)][["segment_id"] + SINGLE_EVENT_FIELDS])}

    years = pd.read_csv(REPORTS / "data_quality_by_year.csv")
    headline = json.loads((REPORTS / "headline.json").read_text(encoding="utf-8"))
    context = {
        "what": "national context and model facts for the overview and statistics screens; research "
                "report values, not part of the backend contract",
        "stats19_by_year": {
            "source": "ml/reports/data_quality_by_year.csv", "source_sha256": file_hash(REPORTS / "data_quality_by_year.csv"),
            "coverage": "Great Britain, all reported injury collisions (DfT STATS19)",
            "rows": records(years[["collision_year", "collisions", "ksi_cas", "adj_ksi_cas", "fatal_cas"]])},
        "holdout": {
            "source": "ml/reports/headline.json", "source_sha256": file_hash(REPORTS / "headline.json"),
            "what": "frozen model tested once on 2024-25 outcomes (cutoff 2023); share of the population's "
                    "2024-25 adjusted KSI captured by its top 10% of segments",
            "population": "all 1,827,550 scored segments",
            "top10_capture_model_pct": headline["holdout_all_lgbm_c10"],
            "top10_capture_crash_counts_pct": headline["holdout_all_hist_collisions_c10"],
            "top10_capture_empirical_bayes_pct": headline["holdout_all_eb_c10"],
            "model_minus_counts_points_ci95": headline["holdout_all_sel_minus_counts_c10"],
            "national_ksi_coverage_pct": headline["coverage_all_share_national"]},
    }

    tier_list = tiers(n_nat)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "segments.json": json.dumps(records(keep), separators=(",", ":")),
        "geometry.geojson": json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")),
        "explanations.json": json.dumps(explanations, separators=(",", ":")),
        "stability.json": json.dumps(stab, separators=(",", ":")),
        "single_event.json": json.dumps(se, separators=(",", ":")),
        "context.json": json.dumps(context, indent=1),
    }
    for name, text in payload.items():
        write_text(text, out / name)
    full = pd.read_parquet(ML_DIR / "outputs" / "road_segments_v2_full.parquet", columns=["blackspot_score"]) \
        if (ML_DIR / "outputs" / "road_segments_v2_full.parquet").exists() else None
    manifest = {
        "bundle": "veyra-gb-demo", "bundle_version": BUNDLE_VERSION,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "generator": "ml/demo/make_frontend_demo_data.py", "generator_args": {"top": args.top},
        "provenance": git_head(),
        "release": {"score_version": rel["release"], "contract_version": rel["contract_version"],
                    "frozen_spec_sha256": rel["model"]["frozen_spec_sha256"],
                    "forecast_years": rel["score"]["forecast_years"], "history_years": rel["score"]["history_years"],
                    "outputs_generated_utc": rel["outputs_generated_utc"]["value"],
                    "release_manifest_sha256": file_hash(V2 / "release_manifest_v2.json")},
        "source_files": {f"data/v2/{F[k]}": file_hash(V2 / F[k]) for k in
                         ("ranked", "geojson", "explanations", "explanations_map", "stability", "single_event", "meta")},
        "coverage": {
            "geography": "Great Britain (England, Scotland and Wales)",
            "not_covered": "Northern Ireland, the Isle of Man and the Channel Islands: outside DfT STATS19 (GB) "
                           "and OS Open Roads (GB); the model makes no claim there",
            "national_segments_scored": n_nat,
            "release_rows": int(len(base)),
            "national_expected_ksi_total": round(float(full.blackspot_score.sum()), 1) if full is not None else 57991.0,
            "national_expected_ksi_total_source": "sum of blackspot_score over all scored segments "
                                                  "(ml/outputs/road_segments_v2_full.parquet; INTEGRATION_CONTRACT.md 3.1)",
            "national_ksi_on_scored_network_pct": 97.7},
        "selection": {
            "rule": f"national top {args.top:,} by rank (complete) plus the integration-fixture reference cases "
                    "outside it; nothing else",
            "n_segments": int(len(keep)), "n_top": int(len(top)), "n_reference_cases": int(len(ref)),
            "reference_cases": {s: case_of[s] for s in sorted(ref, key=lambda s: int(keep.set_index('segment_id').loc[s, 'rank']))},
            "with_line_geometry": len(feats), "midpoint_only": int(len(keep) - len(feats)),
            "not_representative": "a top-ranked subset plus test cases, not a sample of the national network; "
                                  "sums and shares over it describe the subset only"},
        "release_constants": constants,
        "fields": {"segments.json": SEGMENT_FIELDS + ["demo_stratum", "reference_cases"],
                   "explanations.json": {"top": EXPLANATION_FIELDS, "base_and_groups": "top 5,000 only (" + F["explanations_map"] + ")",
                                         "source": F["explanations"]},
                   "stability.json": STABILITY_FIELDS, "single_event.json": SINGLE_EVENT_FIELDS,
                   "geometry.geojson": "release GeoJSON geometry unchanged; properties: segment_id only"},
        "score": {"field": "blackspot_score",
                  "units": "expected killed-or-seriously-injured casualties (DfT severity-adjusted) on the segment, "
                           "2026 and 2027 combined",
                  "forecast_period": meta["forecast_years"], "history_period": meta["history_years"],
                  "kind": "expected count (burden), not a probability and not a per-vehicle rate",
                  "order_by": "rank"},
        "rate": {"field": "ksi_per_100m_vkm_eb", "units": "adjusted KSI per 100 million vehicle-km, 2023-25",
                 "display_rule": f"only when exposure_available and length_m >= {contract.MIN_RATE_LENGTH_M:.0f}",
                 "min_length_m": contract.MIN_RATE_LENGTH_M},
        "tiers": tier_list,
        "tier_rules": {
            "population": f"all {n_nat:,} nationally scored segments, ranks 1 to {n_nat:,}",
            "partition": "contiguous and mutually exclusive: each rank belongs to exactly one group",
            "top1pct_cutoff_rank": top1pct_cutoff(n_nat),
            "top1pct_rounding": f"floor(1% x {n_nat:,}) = floor({n_nat / 100:,.1f}) = {top1pct_cutoff(n_nat):,} (rounded down)",
            "ranks_unchanged": "groups only band the release `rank`; no score or rank is recomputed",
        },
        "files": {name: {"sha256": file_hash(out / name), "bytes": (out / name).stat().st_size} for name in payload},
    }
    write_text(json.dumps(manifest, indent=1), out / "manifest.json")
    total = sum((out / n).stat().st_size for n in list(payload) + ["manifest.json"])
    print(f"demo bundle: {len(keep):,} segments ({len(top):,} top + {len(ref)} reference), "
          f"{len(feats):,} with lines, {total / 1e6:.2f} MB -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
