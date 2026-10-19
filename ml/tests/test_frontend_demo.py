"""Frontend demo bundle: generated only from the v2 release, and the validator catches tampering.

Builds the bundle into a temporary folder (needs data/v2; skipped on a fresh clone). If a
built frontend bundle exists (VEYRA_FRONTEND_DEMO_DIR, or the local worktree used in Phase 4),
it is validated too.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from blackspot.config import BACKEND_DATA, REPO

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "audit"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))

needs_release = pytest.mark.skipif(not (BACKEND_DATA / "v2" / "release_manifest_v2.json").exists(),
                                   reason="v2 release not present")
FRONTEND = Path(os.environ.get("VEYRA_FRONTEND_DEMO_DIR",
                               REPO / ".worktrees" / "frontend-uk" / "frontend" / "public" / "data" / "demo-v2"))


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    if not (BACKEND_DATA / "v2" / "release_manifest_v2.json").exists():
        pytest.skip("v2 release not present")
    from make_frontend_demo_data import main
    out = tmp_path_factory.mktemp("demo") / "demo-v2"
    assert main(["--out", str(out)]) == 0
    return out


@needs_release
def test_generated_bundle_matches_the_release(bundle):
    from validate_frontend_demo import validate
    assert validate(bundle) == []
    m = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert m["selection"]["n_top"] == 1000 and m["selection"]["n_reference_cases"] == 6
    assert m["coverage"]["geography"].startswith("Great Britain")
    t = m["tiers"]
    assert [x["label"] for x in t] == ["Ranks 1–100", "Ranks 101–1,000", "Ranks 1,001–18,275", "Ranks 18,276–1,827,550"]
    assert m["tier_rules"]["top1pct_cutoff_rank"] == 1_827_550 // 100 == 18_275
    assert sum(f["bytes"] for f in m["files"].values()) < 4_000_000          # compact


@needs_release
@pytest.mark.parametrize("tamper", ["score", "rate_without_exposure", "fake_segment", "geometry", "tier_overlap", "tier_label"])
def test_validator_detects_tampering(bundle, tmp_path, tamper):
    from validate_frontend_demo import validate
    b = tmp_path / "b"
    shutil.copytree(bundle, b)
    seg = json.loads((b / "segments.json").read_text(encoding="utf-8"))
    if tamper == "score":
        seg[0]["blackspot_score"] = 99.0
    elif tamper == "rate_without_exposure":
        s = next(s for s in seg if not s["exposure_available"])
        s["ksi_per_100m_vkm_eb"] = 0.0
    elif tamper == "fake_segment":
        seg.append({**seg[-1], "segment_id": "A1-000000000000-00", "rank": seg[-1]["rank"] + 1})
    (b / "segments.json").write_text(json.dumps(seg), encoding="utf-8")
    if tamper in ("tier_overlap", "tier_label"):
        m = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
        if tamper == "tier_overlap":
            m["tiers"][1]["min_rank"] = 100          # ranks 100 would sit in two groups
        else:
            m["tiers"][1]["label"] = "Top 1,000"     # ambiguous: reads as containing ranks 1-100
        (b / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    if tamper == "geometry":
        g = json.loads((b / "geometry.geojson").read_text(encoding="utf-8"))
        g["features"][0]["geometry"]["coordinates"] = [c[::-1] for c in g["features"][0]["geometry"]["coordinates"]]
        (b / "geometry.geojson").write_text(json.dumps(g), encoding="utf-8")
    assert validate(b), tamper


@pytest.mark.skipif(not (FRONTEND / "manifest.json").exists(), reason="no frontend demo bundle on this machine")
def test_frontend_bundle_matches_the_release():
    from validate_frontend_demo import validate
    assert validate(FRONTEND) == []
