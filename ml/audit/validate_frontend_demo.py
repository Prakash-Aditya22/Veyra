"""Check the frontend demo bundle against the v2 release it claims to come from.

    .venv/Scripts/python ml/audit/validate_frontend_demo.py <frontend>/public/data/demo-v2

Every check compares the bundle with data/v2/ (the contract's source of truth):
  - bundle file hashes match manifest.json; source hashes match the current release;
  - the segment set is exactly the documented selection (top N + fixture reference cases);
  - every segment field equals the release CSV value; ranks, scores and IDs included;
  - release-wide constants (forecast and history period, version) equal the release;
  - geometry equals the release GeoJSON, WGS84 [lon, lat], inside Great Britain;
  - explanations, stability and single-event records equal the extension rows and join on segment_id;
  - no rate where exposure is unavailable; no explanation that the release does not hold;
  - counts and coverage statements in manifest.json match the release.
Exits 1 on any problem.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot import contract  # noqa: E402
from blackspot.config import BACKEND_DATA, ML_DIR  # noqa: E402
from blackspot.io_utils import file_hash  # noqa: E402

V2 = BACKEND_DATA / "v2"
F = contract.FILES


def same(a, b) -> bool:
    if a is None or (isinstance(a, float) and math.isnan(a)):
        return b is None or (isinstance(b, float) and math.isnan(b))
    if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
        return math.isclose(float(a), float(b), rel_tol=0, abs_tol=0)
    return a == b


def tier_problems(tiers: list[dict], n_national: int, rules: dict, seg: list[dict]) -> list[str]:
    """Rank groups must partition ranks 1..N exactly, with a floor-rounded top-1% cutoff and labels
    that state the exact boundaries; every bundle segment must fall in exactly one group."""
    errs = []
    if tiers[0]["min_rank"] != 1 or tiers[-1]["max_rank"] != n_national:
        errs.append("rank groups do not cover ranks 1..N")
    for a, b in zip(tiers, tiers[1:]):
        if b["min_rank"] != a["max_rank"] + 1:
            errs.append(f"gap or overlap between rank groups {a['key']} and {b['key']}")
    if any(t["min_rank"] > t["max_rank"] for t in tiers):
        errs.append("a rank group is empty or reversed")
    cutoff = n_national // 100
    if next((t["max_rank"] for t in tiers if t["key"] == "top1pct"), None) != cutoff or rules.get("top1pct_cutoff_rank") != cutoff:
        errs.append(f"top-1% cutoff is not floor(N/100) = {cutoff}")
    for t in tiers:
        want = f"Ranks {t['min_rank']:,}–{t['max_rank']:,}"
        if t.get("label") != want:
            errs.append(f"rank group {t['key']} label {t.get('label')!r} should be {want!r}")
    for s in seg:
        n = sum(t["min_rank"] <= s["rank"] <= t["max_rank"] for t in tiers)
        if n != 1:
            errs.append(f"{s['segment_id']}: rank {s['rank']} falls in {n} rank groups")
    return errs


def validate(bundle: Path) -> list[str]:
    errs: list[str] = []
    m = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    for name, info in m["files"].items():
        if file_hash(bundle / name) != info["sha256"]:
            errs.append(f"{name}: hash differs from manifest.json")
    for path, h in m["source_files"].items():
        if file_hash(BACKEND_DATA.parent / path) != h:
            errs.append(f"{path}: the release changed since the bundle was built (stale bundle)")
    if m["release"]["release_manifest_sha256"] != file_hash(V2 / "release_manifest_v2.json"):
        errs.append("release_manifest_v2.json changed since the bundle was built")

    base = pd.read_csv(V2 / F["ranked"], low_memory=False).set_index("segment_id")
    seg = json.loads((bundle / "segments.json").read_text(encoding="utf-8"))
    ids = [s["segment_id"] for s in seg]
    top_n = m["generator_args"]["top"]
    fx = json.loads((ML_DIR / "tests" / "fixtures" / "integration" / "fixture_manifest.json").read_text(encoding="utf-8"))
    fixture_ids = {s["segment_id"] for c in fx["cases"] for s in c["segments"]}
    want = set(base.index[base["rank"] <= top_n]) | fixture_ids
    if set(ids) != want or len(ids) != len(set(ids)):
        errs.append("segment set differs from the documented selection (top N + fixture cases)")
    if [s["rank"] for s in seg] != sorted(s["rank"] for s in seg):
        errs.append("segments.json is not in rank order")
    unknown = [i for i in ids if i not in base.index]
    if unknown:
        return errs + [f"{len(unknown)} segment_id not in the release"]
    for s in seg:
        r = base.loc[s["segment_id"]]
        for k, v in s.items():
            if k in ("segment_id", "demo_stratum", "reference_cases"):
                continue
            rv = r[k]
            rv = None if (not isinstance(rv, str) and pd.isna(rv)) else (rv.item() if hasattr(rv, "item") else rv)
            if not same(v, rv):
                errs.append(f"{s['segment_id']}.{k}: bundle {v!r} != release {rv!r}")
        if not s["exposure_available"] and s["ksi_per_100m_vkm_eb"] is not None:
            errs.append(f"{s['segment_id']}: rate present without exposure")
        stratum = "reference_case" if s["rank"] > top_n else f"top_{top_n}"
        if s["demo_stratum"] != stratum:
            errs.append(f"{s['segment_id']}: demo_stratum {s['demo_stratum']} should be {stratum}")
    for k, v in m["release_constants"].items():
        if base[k].nunique() != 1 or base[k].iloc[0] != v:
            errs.append(f"release constant {k} differs from the release")
    meta = json.loads((V2 / F["meta"]).read_text(encoding="utf-8"))
    cov = m["coverage"]
    if cov["national_segments_scored"] != meta["n_segments_scored_nationally"] or cov["release_rows"] != len(base):
        errs.append("coverage counts differ from the release")
    if m["selection"]["n_segments"] != len(seg):
        errs.append("selection.n_segments differs from segments.json")
    if m["score"]["forecast_period"] != meta["forecast_years"] or m["score"]["history_period"] != meta["history_years"]:
        errs.append("score periods differ from the release meta")
    errs += tier_problems(m["tiers"], meta["n_segments_scored_nationally"], m.get("tier_rules", {}), seg)

    gj = json.loads((bundle / "geometry.geojson").read_text(encoding="utf-8"))
    real = {f["properties"]["segment_id"]: f["geometry"]
            for f in json.loads((V2 / F["geojson"]).read_text(encoding="utf-8"))["features"]}
    gids = [f["properties"]["segment_id"] for f in gj["features"]]
    if set(gids) != {i for i in ids if i in real}:
        errs.append("geometry.geojson does not hold exactly the bundle segments that have release geometry")
    for f in gj["features"]:
        if f["geometry"] != real.get(f["properties"]["segment_id"]):
            errs.append(f"{f['properties']['segment_id']}: geometry differs from the release")
    lo_lon, hi_lon = contract.GB_BOUNDS["lon"]
    lo_lat, hi_lat = contract.GB_BOUNDS["lat"]
    for f in gj["features"]:
        c = f["geometry"]["coordinates"]
        if f["geometry"]["type"] != "LineString" or len({tuple(x) for x in c}) < 2:
            errs.append(f"{f['properties']['segment_id']}: not a LineString with >= 2 distinct positions")
        if not all(lo_lon <= x <= hi_lon and lo_lat <= y <= hi_lat for x, y in c):
            errs.append(f"{f['properties']['segment_id']}: positions outside Great Britain or not [lon, lat]")
    for s in seg:
        if not (lo_lat <= s["lat"] <= hi_lat and lo_lon <= s["lon"] <= hi_lon):
            errs.append(f"{s['segment_id']}: midpoint outside Great Britain")

    ex = json.loads((bundle / "explanations.json").read_text(encoding="utf-8"))
    rex = pd.read_csv(V2 / F["explanations"])
    rex = rex[rex.segment_id.isin(ids)]
    if set(ex) != set(rex.segment_id):
        errs.append("explanations.json segments differ from the release explanation rows")
    emap = json.loads((V2 / F["explanations_map"]).read_text(encoding="utf-8"))["segments"]
    for sid, e in ex.items():
        rows = rex[rex.segment_id == sid].sort_values("contrib_rank").to_dict(orient="records")
        if len(e["top"]) != len(rows):
            errs.append(f"{sid}: explanation length differs")
            continue
        for a, b in zip(e["top"], rows):
            for k, v in a.items():
                if not same(v, None if (not isinstance(b[k], str) and pd.isna(b[k])) else b[k]):
                    errs.append(f"{sid}.explanation.{k}: {v!r} != {b[k]!r}")
        if ("base" in e) != (sid in emap) or (sid in emap and (e["base"], e["groups"]) != (emap[sid]["base"], emap[sid]["groups"])):
            errs.append(f"{sid}: base/groups differ from the release map JSON")
    for name, key in (("stability.json", "stability"), ("single_event.json", "single_event")):
        b = json.loads((bundle / name).read_text(encoding="utf-8"))
        r = pd.read_csv(V2 / F[key]).set_index("segment_id")
        if set(b) != set(r.index) & set(ids):
            errs.append(f"{name}: segment set differs from the release rows for the bundle")
        for sid, rec in b.items():
            for k, v in rec.items():
                rv = r.loc[sid, k]
                rv = None if (not isinstance(rv, str) and pd.isna(rv)) else (rv.item() if hasattr(rv, "item") else rv)
                if not same(v, rv):
                    errs.append(f"{name}:{sid}.{k}: {v!r} != {rv!r}")
    return errs


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    errs = validate(Path(argv[1]))
    for e in errs[:50]:
        print("FAIL ", e)
    print(f"{argv[1]}: {'bundle matches the v2 release' if not errs else f'{len(errs)} problem(s)'}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
