"""Record or verify SHA-256 hashes of the v1 and v2 production artefacts.

    .venv/Scripts/python ml/audit/artifact_manifest.py record   # before new work
    .venv/Scripts/python ml/audit/artifact_manifest.py verify   # after; exits 1 if anything changed
    .venv/Scripts/python ml/audit/artifact_manifest.py verify phase3

Phase 2 (historical windows, explainability, stability) must not alter any of
these files. The manifest lives at ml/reports/phase2_artifact_manifest.json.
The `phase3` set adds the Phase-2 research outputs (extension files, the saved
production model, result tables, checkpoints), recorded before Phase 3 began, in
ml/reports/phase3_artifact_manifest.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import REPO, REPORTS  # noqa: E402
from blackspot.io_utils import file_hash, write_json  # noqa: E402

MANIFEST = REPORTS / "phase2_artifact_manifest.json"
PATTERNS = [
    "data/road_segments_*",                 # v1 backend files
    "data/v2/road_segments_*",              # v2 backend files
    "ml/models/*", "ml/shap/*.csv", "ml/shap/per_level/*.csv", "ml/demo/blackspot_map.html",
    "ml/demo/blackspot_map_v2.html",
    "ml/outputs/frozen_spec.json", "ml/outputs/forecast_model_info.json",
    "ml/outputs/road_segments_v2_full.parquet", "ml/outputs/severity_v2/*",
    "ml/reports/model_comparison.csv", "ml/reports/model_comparison_bootstrap.csv",
    "ml/reports/rolling_origin_results.csv", "ml/reports/rolling_origin_bootstrap.csv",
    "ml/reports/ablation_results.csv", "ml/reports/final_audit.json", "ml/reports/headline.json",
    "blackspot_handoff.zip",
]
PHASE2_RESEARCH = [
    "data/v2/extensions/segment_explanations_v2.csv", "data/v2/extensions/segment_explanations_top5000_v2.json",
    "data/v2/extensions/segment_stability_v2.csv",
    "ml/outputs/explainability/*.txt", "ml/outputs/explainability/*.json", "ml/outputs/explainability/*.csv",
    "ml/outputs/explainability/local/*.json",
    "ml/reports/historical_window_*.csv", "ml/reports/historical_window_*.json",
    "ml/reports/ranking_stability_*.csv", "ml/reports/ranking_stability_*.json",
    "ml/interim/windows/*", "ml/interim/stability_preds.npz",
]
SETS = {"phase2": (PATTERNS, MANIFEST),
        "phase3": (PATTERNS + PHASE2_RESEARCH, REPORTS / "phase3_artifact_manifest.json")}


def current(patterns=PATTERNS) -> dict:
    out = {}
    for pat in patterns:
        for p in sorted(REPO.glob(pat)):
            if p.is_file():
                out[p.relative_to(REPO).as_posix()] = {"bytes": p.stat().st_size, "sha256": file_hash(p)}
    return out


def main(argv) -> int:
    mode = argv[1] if len(argv) > 1 else "verify"
    patterns, manifest = SETS[argv[2] if len(argv) > 2 else "phase2"]
    now = current(patterns)
    if mode == "record":
        write_json({"files": now}, manifest)
        print(f"recorded {len(now)} files -> {manifest}")
        return 0
    base = json.loads(manifest.read_text())["files"]
    changed = [k for k in base if k not in now or now[k]["sha256"] != base[k]["sha256"]]
    print(f"{len(base) - len(changed)}/{len(base)} artefacts unchanged")
    for k in changed:
        print("CHANGED:", k)
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
