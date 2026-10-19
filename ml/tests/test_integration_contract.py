"""ML -> backend integration contract (data/v2/INTEGRATION_CONTRACT.md).

The fixture tests always run: they need only the 13-segment fixture in fixtures/integration/.
Tests against the real release skip when its files are absent (e.g. a fresh clone).
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from blackspot import contract
from blackspot.config import BACKEND_DATA, ML_DIR, OUTPUTS

FIX = Path(__file__).parent / "fixtures" / "integration"
REAL = BACKEND_DATA / "v2"
DOC = REAL / "INTEGRATION_CONTRACT.md"
F = contract.FILES
needs_real = pytest.mark.skipif(not (REAL / F["ranked"]).exists(), reason="real v2 release not present")


def base(root=FIX):
    return contract.read_ranked(root / F["ranked"])


def case(name):
    m = json.loads((FIX / "fixture_manifest.json").read_text(encoding="utf-8"))
    return [s["segment_id"] for c in m["cases"] if c["case"] == name for s in c["segments"]]


# 1. required fields and types ------------------------------------------------------------
def test_fixture_conforms_to_the_contract():
    res = contract.validate_release(FIX)
    assert set(res) == set(F.values())                      # every file present in the fixture
    assert all(not e for e in res.values()), res


def test_required_fields_present_with_expected_types():
    v = base()
    assert list(v.columns) == [f.name for f in contract.RANKED]
    assert list(v.columns[:len(contract.LEGACY)]) == contract.LEGACY
    for f in contract.RANKED:
        s = v[f.name]
        if f.type == "int":
            assert pd.api.types.is_integer_dtype(s) or (f.nullable and s.dropna().mod(1).eq(0).all()), f.name
        elif f.type == "float":
            assert pd.api.types.is_numeric_dtype(s), f.name
        elif f.type == "bool":
            assert pd.api.types.is_bool_dtype(s), f.name
        else:
            assert s.dropna().map(type).eq(str).all(), f.name
        if not f.nullable:
            assert s.notna().all(), f.name


# 2. IDs match across extension files ------------------------------------------------------
def test_extension_ids_join_the_base_file_with_the_same_rank():
    v = base().set_index("segment_id")
    ids = set(v.index)
    expl = pd.read_csv(FIX / F["explanations"])
    stab = pd.read_csv(FIX / F["stability"])
    se = pd.read_csv(FIX / F["single_event"])
    gj = json.loads((FIX / F["geojson"]).read_text(encoding="utf-8"))
    emap = json.loads((FIX / F["explanations_map"]).read_text(encoding="utf-8"))["segments"]
    assert set(expl.segment_id) == ids and set(stab.segment_id) == ids          # cover every base row
    assert set(se.segment_id) == set(v.index[v["rank"] <= 1000])                 # top 1,000 only
    assert set(f["properties"]["segment_id"] for f in gj["features"]) == set(v.index[v["rank"] <= 5000])
    assert set(emap) == set(v.index[v["rank"] <= 5000])
    for df in (expl.drop_duplicates("segment_id"), stab, se):
        assert (df.set_index("segment_id")["rank"] == v.loc[df.segment_id, "rank"]).all()


# 3. optional fields may be absent ---------------------------------------------------------
def test_base_files_alone_are_a_complete_release(tmp_path):
    for k in contract.REQUIRED_FILES:
        shutil.copyfile(FIX / F[k], tmp_path / F[k])
    res = contract.validate_release(tmp_path)
    assert set(res) == {F[k] for k in contract.REQUIRED_FILES}
    assert all(not e for e in res.values()), res


def test_segment_outside_map_explanations_reads_as_unavailable():
    sid = case("explained_without_map_json")[0]
    emap = json.loads((FIX / F["explanations_map"]).read_text(encoding="utf-8"))["segments"]
    assert sid not in emap                                         # absent, not an empty or zero record
    expl = pd.read_csv(FIX / F["explanations"])
    assert len(expl[expl.segment_id == sid]) == 5                  # the CSV still has it


def test_validator_rejects_broken_releases(tmp_path):
    shutil.copytree(FIX, tmp_path / "r")
    r = tmp_path / "r"
    v = base(r)
    v.loc[v.exposure_available == False, "ksi_per_100m_vkm_eb"] = 0.0          # noqa: E712  fabricated rate
    v.to_csv(r / F["ranked"], index=False)
    assert any("ksi_per_100m_vkm_eb" in e for e in contract.validate_release(r)[F["ranked"]])

    v = base(FIX).drop(columns=["blackspot_score"])
    v.to_csv(r / F["ranked"], index=False)
    assert any("missing columns" in e for e in contract.validate_release(r)[F["ranked"]])

    shutil.copyfile(FIX / F["ranked"], r / F["ranked"])
    gj = json.loads((FIX / F["geojson"]).read_text(encoding="utf-8"))
    gj["features"][0]["geometry"]["coordinates"] = [c[::-1] for c in gj["features"][0]["geometry"]["coordinates"]]
    (r / F["geojson"]).write_text(json.dumps(gj), encoding="utf-8")            # [lat, lon] by mistake
    assert contract.validate_release(r)[F["geojson"]]

    s = pd.read_csv(FIX / F["stability"])
    s.loc[0, "segment_id"] = "A1-000000000000-00"
    s.to_csv(r / F["stability"], index=False)
    assert contract.validate_release(r)[F["stability"]]


# 4. missing exposure never becomes a risk estimate ----------------------------------------
def test_missing_exposure_is_never_a_rate():
    v = base()
    no = v[~v.exposure_available]
    assert len(no) >= 2
    assert no[contract.EXPOSURE_COLS].isna().all().all()
    for _, r in v.iterrows():
        rate, why = contract.per_vehicle_rate_for_display(r.to_dict())
        if not r.exposure_available:
            assert rate is None and "not available" in why
        elif r.length_m < contract.MIN_RATE_LENGTH_M:
            assert rate is None and "shorter" in why
        else:
            assert rate == pytest.approx(r.ksi_per_100m_vkm_eb)


def test_short_segment_rate_exists_but_is_not_displayed():
    r = base().set_index("segment_id").loc[case("exposure_short_segment")[0]]
    assert r.exposure_available and pd.notna(r.ksi_per_100m_vkm_eb) and r.length_m < 250
    assert contract.per_vehicle_rate_for_display(r.to_dict())[0] is None


# 5. score units and forecast periods are documented ---------------------------------------
def test_score_units_and_periods_are_stated_in_the_files():
    v = base()
    meta = json.loads((FIX / F["meta"]).read_text(encoding="utf-8"))
    assert meta["forecast_years"] == [2026, 2027] and meta["history_years"] == [2023, 2024, 2025]
    assert (v.forecast_period == "2026-2027").all() and (v.history_period == "2023-2025").all()
    assert v.score_definition.str.contains("KSI casualties").all() and v.score_definition.str.contains("2026-2027").all()
    units = {f.name: f.units for f in contract.RANKED}
    assert "2-year total" in units["blackspot_score"] and "2026-27" in units["blackspot_score"]
    assert "history" in units["ksi_per_100m_vkm_eb"]               # a 2023-25 rate, not a forecast


@pytest.mark.skipif(not DOC.exists(), reason="contract document not present")
def test_contract_document_covers_every_field_and_the_score_meaning():
    text = DOC.read_text(encoding="utf-8")
    for fields in (contract.RANKED, contract.GEOJSON, contract.EXPLANATIONS, contract.STABILITY, contract.SINGLE_EVENT):
        for f in fields:
            assert f"`{f.name}`" in text, f.name
    for phrase in ("2026 and 2027 combined", "not per-vehicle risk", "EPSG:4326", "EPSG:27700", "ORDER BY rank"):
        assert phrase.lower() in text.lower(), phrase


# 6. ranking and tie-breaking are deterministic --------------------------------------------
def test_rank_is_the_order_and_ties_break_by_segment_id():
    v = contract.production_order(base())
    assert v["rank"].is_unique and v["rank"].is_monotonic_increasing
    assert v.blackspot_score.is_monotonic_decreasing
    a, b = case("tie_pair")
    t = v.set_index("segment_id").loc[[a, b]]
    assert t.blackspot_score.iloc[0] == t.blackspot_score.iloc[1]          # tied
    assert t["rank"].iloc[1] == t["rank"].iloc[0] + 1 and a < b            # adjacent, lower id first


@pytest.mark.skipif(not (OUTPUTS / "road_segments_v2_full.parquet").exists(), reason="national table not present")
def test_national_ranks_follow_full_precision_score_then_segment_id():
    p = pd.read_parquet(OUTPUTS / "road_segments_v2_full.parquet", columns=["segment_id", "rank", "blackspot_score"])
    o = p.sort_values(["blackspot_score", "segment_id"], ascending=[False, True], kind="mergesort")
    assert (o["rank"].values == np.arange(1, len(p) + 1)).all()
    a, b = case("tie_pair")
    s = p.set_index("segment_id").loc[[a, b], "blackspot_score"]
    assert s.iloc[0] == s.iloc[1]                                          # tied at full precision too


@needs_real
def test_rounded_csv_scores_cannot_reproduce_the_rank():
    """Why the contract says ORDER BY rank: the CSV keeps 6 significant digits."""
    v = base(REAL)
    assert v.blackspot_score.duplicated(keep=False).sum() > 0
    assert contract.production_order(v)["rank"].is_monotonic_increasing


# 7. GeoJSON geometry and coordinate conventions -------------------------------------------
def test_geojson_is_wgs84_lon_lat_and_matches_the_midpoints():
    gj = json.loads((FIX / F["geojson"]).read_text(encoding="utf-8"))
    assert not contract.validate_geojson(gj, base())
    assert "crs" not in gj
    v = base().set_index("segment_id")
    for f in gj["features"]:
        c = np.asarray(f["geometry"]["coordinates"])
        r = v.loc[f["properties"]["segment_id"]]
        # the CSV midpoint (6 significant digits) lies within the line's [lon, lat] bounding box
        assert c[:, 0].min() - 1e-3 <= r.lon <= c[:, 0].max() + 1e-3
        assert c[:, 1].min() - 1e-3 <= r.lat <= c[:, 1].max() + 1e-3


# 8. the fixture needs no national pipeline ------------------------------------------------
def test_fixture_validates_without_the_national_pipeline():
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from blackspot.contract import validate_release; "
            "r = validate_release(sys.argv[2]); bad = [m for m in ('lightgbm', 'pyproj', 'blackspot.features', "
            "'blackspot.models', 'blackspot.network') if m in sys.modules]; "
            "print(sum(map(len, r.values())), bad)")
    out = subprocess.run([sys.executable, "-I", "-c", code, str(ML_DIR), str(FIX)], capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "0 []"
    assert sum(p.stat().st_size for p in FIX.rglob("*") if p.is_file()) < 200_000


# the fixture is a verbatim subset of the release; machine-readable files are in sync ------
@needs_real
def test_fixture_rows_are_verbatim_copies_of_the_release():
    for k in ("ranked", "explanations", "stability", "single_event"):
        real = set((REAL / F[k]).read_bytes().splitlines()[1:])
        fix = (FIX / F[k]).read_bytes().splitlines()
        assert fix[0] == (REAL / F[k]).read_bytes().splitlines()[0]
        assert set(fix[1:]) <= real, k
    real_gj = {f["properties"]["segment_id"]: f for f in json.loads((REAL / F["geojson"]).read_text(encoding="utf-8"))["features"]}
    for f in json.loads((FIX / F["geojson"]).read_text(encoding="utf-8"))["features"]:
        assert f == real_gj[f["properties"]["segment_id"]]


@needs_real
def test_real_release_conforms_to_the_contract():
    res = contract.validate_release(REAL)
    assert all(not e for e in res.values()), res


@pytest.mark.skipif(not (REAL / "integration_schema_v2.json").exists(), reason="schema not generated")
def test_machine_readable_schema_matches_the_contract_module():
    assert json.loads((REAL / "integration_schema_v2.json").read_text(encoding="utf-8")) == \
        json.loads(json.dumps(contract.spec()))


@pytest.mark.skipif(not (REAL / "release_manifest_v2.json").exists(), reason="release manifest not generated")
def test_release_manifest_hashes_match_the_files():
    from blackspot.io_utils import file_hash
    m = json.loads((REAL / "release_manifest_v2.json").read_text(encoding="utf-8"))
    assert m["release"] == contract.SCORE_VERSION and m["score"]["forecast_years"] == [2026, 2027]
    roles = {f["path"]: f["role"] for f in m["files"]}
    assert roles["data/v2/road_segments_ranked_v2.csv"] == "required"
    for f in m["files"]:
        if f.get("present"):
            assert file_hash(BACKEND_DATA.parent / f["path"]) == f["sha256"], f["path"]
    assert re.match(r"\d{4}-\d\d-\d\dT", m["outputs_generated_utc"]["value"])


# the explained map (reference UI) agrees with the release and shows nothing fabricated ------
MAPS = ["blackspot_map_v2_explained.html", "blackspot_map_v2_explained_r2.html"]   # original, configurable basemap


@pytest.mark.parametrize("name", MAPS)
def test_explained_map_agrees_with_the_release_and_fabricates_nothing(name):
    MAP = ML_DIR / "demo" / name
    if not (MAP.exists() and (REAL / F["ranked"]).exists()):
        pytest.skip("map or release not present")
    html = MAP.read_text(encoding="utf-8")
    data = json.loads(re.search(r"const DATA = (\{.*?\});\nconst COLORS", html, re.S).group(1))
    v = base(REAL).set_index("segment_id")
    stab = pd.read_csv(REAL / F["stability"]).set_index("segment_id")
    for f in data["features"]:
        p = f["properties"]
        r = v.loc[p["segment_id"]]
        assert p["rank"] == r["rank"] and p["blackspot_score"] == pytest.approx(r.blackspot_score)
        if not p["exposure_available"]:
            assert p["ksi_per_100m_vkm_eb"] is None and p["aadf"] is None          # unavailable, not zero
        assert p["rank_p05"] == pytest.approx(stab.loc[p["segment_id"], "rank_p05"])
        assert p["expl"] is None or p["expl"]["rank"] == r["rank"]
    for must in ("Explanation not available", "Per-vehicle rate not available", "Model baseline",
                 "not a confidence interval", "range #"):
        assert must in html, must
    for banned in ("Average segment", "does <b>not</b> depend on that collision"):
        assert banned not in html, banned
