"""Build the standalone v2 map from the v2 outputs (self-contained, open by double-click).

    .venv/Scripts/python ml/demo/make_v2_map.py            -> ml/demo/blackspot_map_v2_r2.html
    .venv/Scripts/python ml/demo/make_v2_map.py --legacy   -> ml/demo/blackspot_map_v2.html (original)

The r2 page has a configurable, failure-aware basemap (ml/demo/basemap.py; default OpenFreeMap,
no key). If the basemap fails, a neutral background and a message replace it. The original page
hard-codes OpenStreetMap tiles, which OSM blocks when the page is opened from a file. It is
protected (ml/audit/artifact_manifest.py) and kept unchanged; --legacy rebuilds it exactly. The
embedded data are identical in both. The v1 demo (blackspot_map.html) is left as it was.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML))
sys.path.insert(0, str(ML / "demo"))
import basemap  # noqa: E402
from blackspot.config import BACKEND_DATA  # noqa: E402
from blackspot.io_utils import write_text  # noqa: E402

import pandas as pd  # noqa: E402

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blackspot Map v2</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 *{box-sizing:border-box} html,body{margin:0;height:100%;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#f4f5f7}
 #map{position:absolute;inset:0}
 .panel{position:absolute;z-index:1000;background:#fff;border-radius:6px;box-shadow:0 2px 14px rgba(0,0,0,.22);padding:12px 14px;color:#1d232b}
 #ctl{top:12px;left:12px;width:300px;max-width:calc(100vw - 24px)}
 #ctl h1{font-size:17px;margin:0 0 4px} #ctl p{margin:0 0 10px;font-size:12px;color:#5d6775;line-height:1.4}
 label{display:block;font-size:12px;margin:6px 0}
 select{width:100%;padding:7px;border:1px solid #c8d0da;border-radius:4px;font-size:13px}
 #leg{bottom:22px;left:12px;font-size:12px;max-width:calc(100vw - 24px)}
 .row{display:flex;align-items:center;gap:8px;margin:3px 0} .sw{width:26px;height:6px;border-radius:2px}
 .muted{color:#6b7686;font-size:11px;line-height:1.45;max-width:260px;margin-top:6px}
 .pop table{border-collapse:collapse;font-size:12.5px} .pop td{padding:2px 0}
 .pop td:last-child{text-align:right;padding-left:14px;font-variant-numeric:tabular-nums}
 .pop h3{font-size:14px;margin:0 0 6px}
</style></head><body>
<div id="map"></div>
<div class="panel" id="ctl">
  <h1>Road blackspots, Great Britain (v2)</h1>
  <p>Top __N__ of __NTOT__ scored road segments. Forecast for __FP__ from __HP__ history.
     Segments are cut from OS Open Roads centrelines, not from crash points.</p>
  <label>Colour by
    <select id="mode">
      <option value="blackspot_score">Expected serious + fatal casualties, __FP__</option>
      <option value="eb_excess_ksi_history">Excess over similar roads (Empirical Bayes)</option>
      <option value="ksi_per_100m_vkm_eb">Per 100 million vehicle-km (M/A roads with traffic counts)</option>
    </select></label>
  <label><input type="checkbox" id="suff" checked> Only segments with &ge; 6 crashes in __HP__</label>
</div>
<div class="panel" id="leg"><div id="legrows"></div>
  <div class="muted">A burden, not a risk rate: busy roads rank high because many people use them.
  Excess and rate answer different questions. Model: __MODEL__ (spec __HASH__).</div></div>
<script>
const DATA = __DATA__;
const COLORS = ["#f2c14e","#e8892b","#cf4a26","#8e1d1d","#2a0b0b"];
const map = L.map('map',{preferCanvas:true}).setView([53.5,-2.3],6);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,
  attribution:'&copy; OpenStreetMap contributors | Roads: OS Open Roads, Crown copyright | Data: DfT STATS19, OGL'}).addTo(map);
let layer=null;
function quantiles(v){const s=v.filter(x=>x!=null&&isFinite(x)).sort((a,b)=>a-b);
  return [.5,.75,.9,.97].map(q=>s[Math.floor(q*(s.length-1))]);}
function fmt(x,d){return (x==null||!isFinite(x))?'—':Number(x).toFixed(d);}
function draw(){
  const mode=document.getElementById('mode').value, suff=document.getElementById('suff').checked;
  const feats=DATA.features.filter(f=>(!suff||f.properties.data_sufficiency==='sufficient')&&f.properties[mode]!=null);
  const br=quantiles(feats.map(f=>f.properties[mode]));
  const col=v=>COLORS[br.filter(b=>v>b).length];
  if(layer) map.removeLayer(layer);
  layer=L.geoJSON({type:'FeatureCollection',features:feats},{
    style:f=>({color:col(f.properties[mode]),weight:5,opacity:.9}),
    onEachFeature:(f,l)=>{const p=f.properties;l.bindPopup(`<div class="pop"><h3>#${p.rank} ${p.location}</h3><table>
      <tr><td>Expected KSI __FP__</td><td>${fmt(p.blackspot_score,2)}</td></tr>
      <tr><td>Excess over similar roads</td><td>${fmt(p.eb_excess_ksi_history,2)}</td></tr>
      <tr><td>KSI per 100M veh-km</td><td>${fmt(p.ksi_per_100m_vkm_eb,1)}</td></tr>
      <tr><td>Crashes __HP__</td><td>${p.n_crashes}</td></tr>
      <tr><td>KSI casualties (adjusted)</td><td>${fmt(p.n_ksi_casualties_adjusted,1)}</td></tr>
      <tr><td>Length</td><td>${fmt(p.length_m,0)} m</td></tr></table>
      ${p.single_event_flag?'<div style="margin-top:6px;color:#8e1d1d;font-size:11.5px">History dominated by one mass-casualty collision: not a road-design signal.</div>':''}</div>`);}}).addTo(map);
  const lab=['up to '+fmt(br[0],2),fmt(br[0],2)+'–'+fmt(br[1],2),fmt(br[1],2)+'–'+fmt(br[2],2),
             fmt(br[2],2)+'–'+fmt(br[3],2),'above '+fmt(br[3],2)];
  document.getElementById('legrows').innerHTML='<b>'+document.querySelector('#mode option:checked').text+'</b>'+
    COLORS.map((c,i)=>`<div class="row"><span class="sw" style="background:${c}"></span>${lab[i]}</div>`).join('')+
    `<div class="muted">${feats.length} segments shown; bands are quantiles of those shown.</div>`;
}
document.getElementById('mode').onchange=draw; document.getElementById('suff').onchange=draw; draw();
</script></body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the standalone v2 map.")
    basemap.add_arguments(ap)
    ap.add_argument("--legacy", action="store_true",
                    help="rebuild the original page (hard-coded OpenStreetMap tiles), blackspot_map_v2.html")
    ap.add_argument("--out", type=Path, help="output path (default: the r2 page, or the original with --legacy)")
    a = ap.parse_args(argv)
    d = BACKEND_DATA / "v2"
    gj = json.loads((d / "road_segments_top5000_v2.geojson").read_text())
    meta = json.loads((d / "road_segments_meta_v2.json").read_text())
    full = pd.read_csv(d / "road_segments_ranked_v2.csv", low_memory=False).set_index("segment_id")
    keep = ["ksi_per_100m_vkm_eb", "n_ksi_casualties_adjusted", "length_m", "eb_excess_ksi_history"]
    for f in gj["features"]:
        r = full.loc[f["properties"]["segment_id"]]
        for k in keep:
            v = r[k]
            f["properties"][k] = None if pd.isna(v) else round(float(v), 4)
    template = TEMPLATE if a.legacy else basemap.apply(TEMPLATE, basemap.config_from_args(a, meta))
    html = (template.replace("__DATA__", json.dumps(gj, separators=(",", ":")))
            .replace("__N__", f"{len(gj['features']):,}")
            .replace("__NTOT__", f"{meta['n_segments_scored_nationally']:,}")
            .replace("__FP__", "-".join(map(str, meta["forecast_years"][::len(meta['forecast_years']) - 1])))
            .replace("__HP__", f"{meta['history_years'][0]}-{meta['history_years'][-1]}")
            .replace("__MODEL__", meta["model"]).replace("__HASH__", meta["frozen_spec_sha256"][:12]))
    out = a.out or ML / "demo" / ("blackspot_map_v2.html" if a.legacy else "blackspot_map_v2_r2.html")
    write_text(html, out)
    print("wrote", out)


if __name__ == "__main__":
    main()
