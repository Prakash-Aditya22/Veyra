"""Build the small integration fixture in ml/tests/fixtures/integration/ from the real v2 release.

    .venv/Scripts/python ml/audit/make_integration_fixtures.py

Picks real segments by fixed rules (fixture_manifest.json records each rule and the source file
hashes) and copies their records verbatim: CSV lines as text, so rounding and empty cells are
exactly those of the release; JSON and GeoJSON objects unchanged. No value is invented or
recomputed. The folder mirrors data/v2/, so the same validator and tests run on both.
The full-precision national table is used only to find a tied pair of forecasts.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import BACKEND_DATA, ML_DIR, OUTPUTS  # noqa: E402
from blackspot.contract import FILES  # noqa: E402
from blackspot.io_utils import atomic_path, file_hash, write_json, write_text  # noqa: E402

SRC = BACKEND_DATA / "v2"
DST = ML_DIR / "tests" / "fixtures" / "integration"


def pick_cases(v: pd.DataFrame, stab: pd.DataFrame, se: pd.DataFrame) -> list[tuple[str, str, list[str]]]:
    first = lambda d: [d.sort_values("rank").segment_id.iloc[0]]  # noqa: E731
    s = v.merge(stab[["segment_id", "stability_class"]], on="segment_id")
    cases = [
        ("high_rank_normal", "rank 1", first(v)),
        ("high_rank_with_exposure", "best rank with exposure_available, length_m >= 250, sufficient history, no single-event flag",
         first(v[v.exposure_available & (v.length_m >= 250) & (v.data_sufficiency == "sufficient") & ~v.single_event_flag])),
        ("exposure_short_segment", "best rank with exposure_available and length_m < 250 (rate exists but must not be displayed)",
         first(v[v.exposure_available & (v.length_m < 250)])),
        ("single_event", "best rank with single_event_flag", first(v[v.single_event_flag])),
        ("no_history", "best rank with data_sufficiency == none (no collision 2023-25)", first(v[v.data_sufficiency == "none"])),
        ("sparse_history", "best rank with data_sufficiency == sparse", first(v[v.data_sufficiency == "sparse"])),
        ("borderline_stability", "best rank with stability_class == borderline top-1000",
         first(s[s.stability_class == "borderline top-1000"])),
        ("forecast_rises_without_largest_collision", "largest forecast_without_largest_collision / forecast among non-flagged top-1,000",
         [se[~se.single_event_flag].assign(r=se.forecast_without_largest_collision / se.forecast)
          .sort_values(["r", "rank"], ascending=[False, True]).segment_id.iloc[0]]),
        ("explained_without_map_json", "best rank above 5,000 (CSV explanation, no map JSON, no line geometry)",
         first(v[v["rank"] > 5000])),
        ("rank_50000", "rank == 50,000 (edge of the top-N export)", v.loc[v["rank"] == 50_000, "segment_id"].tolist()),
        ("lowest_ranked", "worst rank in the file (exported because n_crashes >= 6)", [v.sort_values("rank").segment_id.iloc[-1]]),
    ]
    # a pair with identical full-precision forecasts and adjacent ranks (tie broken by segment_id)
    full = pd.read_parquet(OUTPUTS / "road_segments_v2_full.parquet", columns=["segment_id", "rank", "blackspot_score"])
    full = full[full.segment_id.isin(v.segment_id)].sort_values("rank")
    same = full.blackspot_score.values[1:] == full.blackspot_score.values[:-1]
    adj = full["rank"].values[1:] == full["rank"].values[:-1] + 1
    i = int(next(k for k in range(len(same)) if same[k] and adj[k]))
    cases.append(("tie_pair", "best-ranked adjacent pair with identical full-precision blackspot_score",
                  full.segment_id.iloc[[i, i + 1]].tolist()))
    return cases


def copy_csv_lines(src: Path, dst: Path, ids: set, key: str = "segment_id") -> int:
    """Copy the header and the matching rows byte for byte (line endings included)."""
    lines = src.read_bytes().splitlines(keepends=True)
    header = next(csv.reader([lines[0].decode("utf-8")]))
    k = header.index(key)
    keep = [ln for ln in lines[1:] if next(csv.reader([ln.decode("utf-8")]))[k] in ids]
    with atomic_path(dst) as tmp:
        tmp.write_bytes(lines[0] + b"".join(keep))
    return len(keep)


def main() -> int:
    v = pd.read_csv(SRC / FILES["ranked"], low_memory=False)
    stab = pd.read_csv(SRC / FILES["stability"])
    se = pd.read_csv(SRC / FILES["single_event"])
    cases = pick_cases(v, stab, se)
    ids = {sid for _, _, l in cases for sid in l}
    rank = v.set_index("segment_id")["rank"]

    if DST.exists():
        for p in [DST / FILES[k] for k in FILES]:
            if p.exists():
                p.unlink()
    DST.mkdir(parents=True, exist_ok=True)
    counts = {FILES["ranked"]: copy_csv_lines(SRC / FILES["ranked"], DST / FILES["ranked"], ids)}
    shutil.copyfile(SRC / FILES["meta"], DST / FILES["meta"])
    top500 = [r for r in json.loads((SRC / FILES["top500"]).read_text(encoding="utf-8")) if r["segment_id"] in ids]
    write_text(json.dumps(top500, indent=1), DST / FILES["top500"])
    gj = json.loads((SRC / FILES["geojson"]).read_text(encoding="utf-8"))
    gj["features"] = [f for f in gj["features"] if f["properties"]["segment_id"] in ids]
    write_text(json.dumps(gj), DST / FILES["geojson"])
    for k in ("explanations", "stability", "single_event"):
        counts[FILES[k]] = copy_csv_lines(SRC / FILES[k], DST / FILES[k], ids)
    ex = json.loads((SRC / FILES["explanations_map"]).read_text(encoding="utf-8"))
    ex["segments"] = {k: e for k, e in ex["segments"].items() if k in ids}
    write_text(json.dumps(ex, indent=1), DST / FILES["explanations_map"])
    counts.update({FILES["top500"]: len(top500), FILES["geojson"]: len(gj["features"]),
                   FILES["explanations_map"]: len(ex["segments"])})

    write_json({
        "what": "real records copied verbatim from the v2 release; a subset for contract tests",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "generator": "ml/audit/make_integration_fixtures.py",
        "source_sha256": {FILES[k]: file_hash(SRC / FILES[k]) for k in FILES if (SRC / FILES[k]).exists()},
        "meta_note": "road_segments_meta_v2.json is copied unchanged; its n_rows_in_this_file describes the full release",
        "n_segments": len(ids), "rows_per_file": counts,
        "cases": [{"case": c, "rule": r, "segments": [{"segment_id": s, "rank": int(rank[s])} for s in l]}
                  for c, r, l in cases]}, DST / "fixture_manifest.json")
    print(f"fixture: {len(ids)} segments -> {DST}")
    for c, r, l in cases:
        print(f"  {c:42s} {[(s, int(rank[s])) for s in l]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
