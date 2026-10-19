"""Standalone demo maps: the r2 pages use the configurable basemap and keep the original data.

The original pages (blackspot_map_v2.html, blackspot_map_v2_explained.html) hard-code
OpenStreetMap tiles. OSM blocks those when the page is opened from a file, because no Referer
is sent. They are kept unchanged. The r2 pages swap only the basemap (ml/demo/basemap.py).
"""
import json
import re
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_DIR / "demo"))
import basemap  # noqa: E402

DEMO = ML_DIR / "demo"
PAIRS = [("blackspot_map_v2.html", "blackspot_map_v2_r2.html"),
         ("blackspot_map_v2_explained.html", "blackspot_map_v2_explained_r2.html")]
DATA_RE = re.compile(r"const DATA = (\{.*?\});\nconst COLORS", re.S)
CONFIG_RE = re.compile(r"const BASEMAP_CONFIG = (\{.*?\});\n</script>", re.S)

MINI = """<html><head>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
</style></head><body>
<div id="map"></div>
<script>
const DATA = {"type":"FeatureCollection","features":[]};
const COLORS = [];
const map = L.map('map',{preferCanvas:true}).setView([53.5,-2.3],6);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,
  attribution:'&copy; OpenStreetMap contributors | Roads: OS Open Roads, Crown copyright | Data: DfT STATS19, OGL'}).addTo(map);
</script></body></html>"""


def cfg(**kw):
    return basemap.config(os_release_year=2026, **kw)


def test_apply_replaces_the_hard_coded_osm_layer_with_the_configurable_basemap():
    html = basemap.apply(MINI, cfg())
    assert "L.tileLayer('https://tile.openstreetmap.org" not in html
    assert html.count("initBasemap(map, BASEMAP_CONFIG);") == 1
    assert 'id="basemap-note"' in html and "Basemap unavailable" in html
    assert f"maplibre-gl@{basemap.MAPLIBRE_VERSION}/dist/maplibre-gl.js" in html
    c = json.loads(CONFIG_RE.search(html).group(1))
    assert c["default"] == "openfreemap-positron"
    assert DATA_RE.search(html).group(1) == '{"type":"FeatureCollection","features":[]}'


def test_apply_refuses_a_template_it_does_not_recognise():
    with pytest.raises(ValueError):
        basemap.apply(MINI.replace("tile.openstreetmap.org", "example.org"), cfg())
    with pytest.raises(ValueError):
        basemap.apply(MINI.replace('<div id="map"></div>', ""), cfg())


def test_providers_encode_their_terms():
    c = cfg()["providers"]
    assert c["osm"]["requiresReferer"] is True                     # never requested from file://
    assert c["carto-positron"]["requiresKey"] is True and c["carto-positron"]["key"] == ""
    assert "key" not in c["openfreemap-positron"] and c["openfreemap-positron"]["kind"] == "vector"
    for p in c.values():
        if p["kind"] == "raster":
            assert "OpenStreetMap" in p["attribution"] and p.get("checked", True)


def test_no_key_option_and_an_example_local_config():
    c = cfg()
    assert c["providers"]["carto-positron"]["key"] == ""
    example = (DEMO / "basemap.config.example.js").read_text(encoding="utf-8")
    assert "window.VEYRA_BASEMAP_CONFIG" in example and "cartoKey: ''" in example
    ignored = (ML_DIR.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "ml/demo/basemap.config.js" in ignored and "ml/demo/basemap.config.example.js" not in ignored


def test_custom_provider_needs_a_template_and_attribution():
    ok = cfg(default="custom", custom={"url": "https://t.example/{z}/{x}/{y}.png", "attribution": "© Example"})
    assert ok["providers"]["custom"]["checked"] is True
    with pytest.raises(ValueError):
        cfg(default="custom", custom={"url": "https://t.example/{z}/{x}/{y}.png", "attribution": " "})
    with pytest.raises(ValueError):
        cfg(default="custom", custom={"url": "https://t.example/tiles.png", "attribution": "© Example"})
    with pytest.raises(ValueError):
        cfg(default="nope")


def test_data_attribution_credits_the_road_and_collision_sources():
    a = cfg()["dataAttribution"]
    for must in ("OS Open Roads", "Crown copyright and database right 2026", "STATS19", "Open Government Licence v3.0"):
        assert must in a
    assert basemap.os_year({"segmentation": "OS Open Roads centrelines (2026-04 release); ..."}) == 2026


@pytest.mark.parametrize("orig,r2", PAIRS)
def test_r2_map_keeps_the_original_data_and_drops_the_hard_coded_tiles(orig, r2):
    if not ((DEMO / orig).exists() and (DEMO / r2).exists()):
        pytest.skip("map not built")
    a, b = (DEMO / orig).read_text(encoding="utf-8"), (DEMO / r2).read_text(encoding="utf-8")
    assert DATA_RE.search(b).group(1) == DATA_RE.search(a).group(1)    # predictions, ids, ranks, explanations
    assert "L.tileLayer('https://tile.openstreetmap.org" in a and "L.tileLayer('https://tile.openstreetmap.org" not in b
    c = json.loads(CONFIG_RE.search(b).group(1))
    p = c["providers"][c["default"]]
    assert not p.get("requiresKey") or p.get("key"), "default basemap needs a key the page does not have"
    assert not p.get("requiresReferer"), "default basemap would be blocked on file:// pages"
    assert "OS Open Roads" in c["dataAttribution"] and "STATS19" in c["dataAttribution"]
    assert all(not v.get("key") for v in c["providers"].values()), "an API key is embedded in the page"
    assert '<script src="basemap.config.js"></script>' in b                # local settings, no regeneration
    assert "isOsmBlockTile(bmp)" in b                                      # OSM block images are rejected
    # everything outside the basemap code is the original page
    stripped = b
    for chunk in (basemap.HEAD, basemap.CSS, "\n" + basemap.NOTE):
        stripped = stripped.replace(chunk, "", 1)
    stripped = re.sub(r"<script>\n/\* Basemap:.*?</script>\n", "", stripped, count=1, flags=re.S)
    assert stripped == basemap.LEGACY_TILES.sub("initBasemap(map, BASEMAP_CONFIG);", a)
