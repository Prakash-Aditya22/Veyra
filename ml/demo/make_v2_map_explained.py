"""Build the explained v2 map: the v2 map plus a segment information panel.

    .venv/Scripts/python ml/demo/make_v2_map_explained.py            -> ml/demo/blackspot_map_v2_explained_r2.html
    .venv/Scripts/python ml/demo/make_v2_map_explained.py --legacy   -> ml/demo/blackspot_map_v2_explained.html
        (after pipeline.py forecast, ml/experiments/explain_blackspot.py, ml/experiments/ranking_stability.py)

The r2 page has the configurable, failure-aware basemap of ml/demo/basemap.py (default
OpenFreeMap, no key; neutral background and a message if it fails). The original page, with
hard-coded OpenStreetMap tiles, is kept unchanged; --legacy rebuilds it. The data are the same.

Separate from the plain v2 map (blackspot_map_v2*.html, make_v2_map.py). Data come
only from data/v2/ (the backend contract) and data/v2/extensions/ (new, optional files); the
panel follows the UI rules of data/v2/INTEGRATION_CONTRACT.md section 8.

Phase 3 changes:
- the exact rank is shown with its refit range and tier, never alone;
- the baseline is labelled as the model baseline, not the "average segment";
- a missing explanation says "not available";
- single-event wording uses the one-at-a-time sensitivity file and separates "sensitive to" from "depends on";
- rate and excess carry their 2023-25 period.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML))
sys.path.insert(0, str(ML / "demo"))
import basemap  # noqa: E402
from blackspot.config import BACKEND_DATA  # noqa: E402
from blackspot.io_utils import write_text  # noqa: E402

PANEL_COLS = ["rank", "location", "road_class", "length_m", "blackspot_score", "n_crashes",
              "n_ksi_casualties_adjusted", "n_fatal", "data_sufficiency", "single_event_flag",
              "single_event_share", "max_single_collision_ksi", "eb_excess_ksi_history", "exposure_available",
              "aadf", "ksi_per_100m_vkm_eb", "forecast_period", "history_period"]
STAB_COLS = ["rank_median", "rank_p05", "rank_p95", "freq_top100", "freq_top1000", "freq_top5pct",
             "stability_class", "window_rank_min", "window_rank_max"]
SE_COLS = {"forecast_without_largest_collision": "fwo", "rank_without_largest_collision_one_at_a_time": "rank_wo"}

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blackspot Map v2 explained</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 *{box-sizing:border-box} html,body{margin:0;height:100%;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#1d232b}
 #map{position:absolute;inset:0}
 .card{position:absolute;z-index:1000;background:#fff;border-radius:6px;box-shadow:0 2px 14px rgba(0,0,0,.22);padding:12px 14px}
 #ctl{top:12px;left:12px;width:290px;max-width:calc(100vw - 24px)}
 #ctl h1{font-size:16px;margin:0 0 4px} #ctl p{margin:0 0 8px;font-size:11.5px;color:#5d6775;line-height:1.4}
 label{display:block;font-size:12px;margin:6px 0} select{width:100%;padding:6px;border:1px solid #c8d0da;border-radius:4px}
 #panel{top:12px;right:12px;width:380px;max-width:calc(100vw - 24px);max-height:calc(100vh - 24px);overflow:auto;display:none}
 #panel h2{font-size:15px;margin:0 0 2px} .sub{font-size:11.5px;color:#6b7686;margin-bottom:8px}
 .sec{border-top:1px solid #e3e7ed;padding-top:8px;margin-top:8px}
 .sec h3{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#6b7686;margin:0 0 6px}
 .big{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}
 .kv{display:grid;grid-template-columns:1fr auto;gap:3px 10px;font-size:12.5px} .kv b{font-variant-numeric:tabular-nums;text-align:right}
 .bar{display:grid;grid-template-columns:1fr 64px;gap:2px 8px;align-items:center;font-size:12px;margin:3px 0}
 .barline{height:7px;border-radius:3px;margin-top:2px}
 .warn{background:#fff4e5;border:1px solid #f0c27b;border-radius:4px;padding:6px 8px;font-size:12px;margin-top:6px}
 .info{background:#eef3fb;border:1px solid #b9cbe8;border-radius:4px;padding:6px 8px;font-size:12px;margin-top:6px}
 .badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;color:#fff}
 .muted{color:#6b7686;font-size:11px;line-height:1.4;margin-top:6px}
 #close{float:right;border:0;background:none;font-size:18px;cursor:pointer;color:#6b7686}
 #leg{bottom:22px;left:12px;font-size:12px} .row{display:flex;align-items:center;gap:8px;margin:3px 0} .sw{width:26px;height:6px;border-radius:2px}
</style></head><body>
<div id="map"></div>
<div class="card" id="ctl">
  <h1>Road blackspots (v2), explained</h1>
  <p>Top __N__ of __NTOT__ scored segments. Click a road for its forecast, history, why the model ranks it,
     how stable that rank is, and warnings.</p>
  <p>Scores cover 97.7% of Great Britain's serious and fatal casualties (private and service roads are not
     scored). Ranks are tiers, not exact positions.</p>
  <label>Colour by
    <select id="mode">
      <option value="blackspot_score">Expected serious + fatal casualties __FP__ (burden)</option>
      <option value="stab">Rank stability (share of refits keeping it in the top 1,000)</option>
      <option value="eb_excess_ksi_history">Excess over similar roads (Empirical Bayes)</option>
    </select></label>
  <label><input type="checkbox" id="suff" checked> Only segments with &ge; 6 crashes in __HP__</label>
</div>
<div class="card" id="panel"><button id="close" aria-label="close">&times;</button><div id="pbody"></div></div>
<div class="card" id="leg"><div id="legrows"></div></div>
<script>
const DATA = __DATA__;
const COLORS = ["#f2c14e","#e8892b","#cf4a26","#8e1d1d","#2a0b0b"];
const map = L.map('map',{preferCanvas:true}).setView([53.5,-2.3],6);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,
 attribution:'&copy; OpenStreetMap contributors | Roads: OS Open Roads, Crown copyright | Data: DfT STATS19, OGL'}).addTo(map);
const f2=(x,d)=>(x==null||!isFinite(x))?'—':Number(x).toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:d});
const int=x=>(x==null||!isFinite(x))?'—':Math.round(x).toLocaleString();
function val(p,mode){return mode==='stab'?p.freq_top1000:p[mode];}
function q(v){const s=v.filter(x=>x!=null&&isFinite(x)).sort((a,b)=>a-b);return [.5,.75,.9,.97].map(t=>s[Math.floor(t*(s.length-1))]);}
let layer=null;
function draw(){
 const mode=document.getElementById('mode').value, suff=document.getElementById('suff').checked;
 const feats=DATA.features.filter(f=>(!suff||f.properties.data_sufficiency==='sufficient')&&val(f.properties,mode)!=null);
 const br=mode==='stab'?[0.5,0.75,0.9,0.99]:q(feats.map(f=>val(f.properties,mode)));
 const col=v=>COLORS[br.filter(b=>v>b).length];
 if(layer) map.removeLayer(layer);
 layer=L.geoJSON({type:'FeatureCollection',features:feats},{style:f=>({color:col(val(f.properties,mode)),weight:5,opacity:.9}),
   onEachFeature:(f,l)=>l.on('click',()=>show(f.properties))}).addTo(map);
 const lab=mode==='stab'?['≤ 50% of refits','50–75%','75–90%','90–99%','≥ 99%']:
   ['up to '+f2(br[0],2),f2(br[0],2)+'–'+f2(br[1],2),f2(br[1],2)+'–'+f2(br[2],2),f2(br[2],2)+'–'+f2(br[3],2),'above '+f2(br[3],2)];
 document.getElementById('legrows').innerHTML='<b>'+document.querySelector('#mode option:checked').text+'</b>'+
   COLORS.map((c,i)=>`<div class="row"><span class="sw" style="background:${c}"></span>${lab[i]}</div>`).join('')+
   `<div class="muted">${feats.length} segments shown.</div>`;
}
const BADGE={"robust top-1000":"#1e7a46","borderline top-1000":"#b7791f","robust top-5%":"#2b6cb0","variable":"#718096"};
function show(p){
 const ex=p.expl||{}, top=ex.top||[];
 const maxf=Math.max(...top.map(t=>Math.abs(Math.log(t.factor))),0.01);
 const bars=top.map(t=>{const up=t.factor>=1, w=Math.round(100*Math.abs(Math.log(t.factor))/maxf);
   return `<div class="bar"><div>${t.label} <span class="muted">(${t.display!=null?t.display:f2(t.value,2)})</span>
   <div class="barline" style="width:${w}%;background:${up?'#cf4a26':'#2b6cb0'}"></div></div><b>×${f2(t.factor,2)}</b></div>`;}).join('');
 const rateOK=p.exposure_available && p.ksi_per_100m_vkm_eb!=null && p.length_m>=250;
 const rate= rateOK ? `<div class="kv"><span>Serious/fatal per 100 million vehicle-km (EB, ${p.history_period})</span><b>${f2(p.ksi_per_100m_vkm_eb,1)}</b>
    <span>Average daily traffic (DfT count)</span><b>${int(p.aadf)}</b></div>
    <div class="muted">Per-vehicle risk is a different question from burden: a busy road can have a high burden and an ordinary rate.</div>`
   : `<div class="muted">${p.exposure_available? 'Per-vehicle rate not shown: the segment is shorter than 250 m, so its traffic denominator is too small for a reliable rate.'
      :'Per-vehicle rate not available: no DfT traffic count is matched to this road (counts exist for motorways and A roads only). No substitute is shown.'}</div>`;
 const warns=[];
 if(p.single_event_flag){
   const rw=p.rank_wo;
   const dep = rw==null ? '' : (p.fwo>=p.blackspot_score
     ? ` Removing that collision does <b>not</b> lower the model's forecast (${f2(p.fwo,2)} instead of ${f2(p.blackspot_score,2)}; rank #${int(rw)}): the segment's high priority does not <i>require</i> the event, but its forecast is <i>sensitive</i> to it. The model treats such a spike as partly noise.`
     : ` Without that collision the forecast would be ${f2(p.fwo,2)} (rank #${int(rw)}).`);
   warns.push(`<div class="warn"><b>Single-event concentration.</b> One collision supplied ${f2(100*p.single_event_share,0)}% of this segment's serious/fatal history (${f2(p.max_single_collision_ksi,1)} of ${f2(p.n_ksi_casualties_adjusted,1)} adjusted serious/fatal casualties), so its history, excess and per-vehicle figures are dominated by one incident, not by the road's design.${dep}</div>`);}
 else if(p.rank_wo!=null && p.rank_wo>1000 && p.rank<=1000) warns.push(`<div class="warn">Sensitive to one collision: without its largest recent collision this segment would be #${int(p.rank_wo)} (forecast ${f2(p.fwo,2)}).</div>`);
 if(p.data_sufficiency!=='sufficient') warns.push(`<div class="warn"><b>Low history.</b> Fewer than 6 crashes in ${p.history_period}; the forecast leans on road type and neighbouring roads.</div>`);
 const stab = p.rank_p05!=null ? `<div class="kv"><span>Rank range across __NBOOT__ spatial-bootstrap refits (5th–95th pct)</span><b>#${int(p.rank_p05)} – #${int(p.rank_p95)}</b>
   <span>Refits keeping it in the national top 1,000</span><b>${f2(100*p.freq_top1000,0)}%</b>
   <span>Refits keeping it in the top 100</span><b>${f2(100*p.freq_top100,0)}%</b>
   <span>Rank range across historical-window choices</span><b>#${int(p.window_rank_min)} – #${int(p.window_rank_max)}</b></div>
   <div class="muted">Spread from refitting the model __NBOOT__ times; not a confidence interval for future casualties. Neighbouring ranks are not meaningfully different: compare tiers or ranges, not positions.</div>` : '<div class="muted">Stability not available for this segment.</div>';
 const rankline = p.rank_p05!=null
   ? `#${int(p.rank)} <span class="muted">(range #${int(p.rank_p05)}–#${int(p.rank_p95)} across refits)</span>`
   : `#${int(p.rank)} <span class="muted">(stability not available)</span>`;
 document.getElementById('pbody').innerHTML=`
  <h2>${p.location}</h2><div class="sub">${p.road_class} road · ${int(p.length_m)} m · <span class="badge" style="background:${BADGE[p.stability_class]||'#718096'}">${p.stability_class||'n/a'}</span></div>
  <div class="sec"><h3>Forecast ${p.forecast_period}</h3><div class="big">${f2(p.blackspot_score,2)}</div>
   <div class="kv"><span>expected serious or fatal casualties (DfT-adjusted), two-year total</span><b></b>
   <span>National rank of __NTOT__</span><b>${rankline}</b></div></div>
  <div class="sec"><h3>Rank stability</h3>${stab}</div>
  <div class="sec"><h3>Recorded history ${p.history_period}</h3><div class="kv"><span>Collisions</span><b>${int(p.n_crashes)}</b>
   <span>Serious/fatal casualties (adjusted)</span><b>${f2(p.n_ksi_casualties_adjusted,1)}</b><span>Fatal collisions</span><b>${int(p.n_fatal)}</b>
   <span>Excess over similar roads (EB, ${p.history_period})</span><b>${f2(p.eb_excess_ksi_history,2)}</b></div></div>
  <div class="sec"><h3>Why the model ranks it here</h3>
   ${top.length ? `<div class="kv"><span>Model baseline (typical segment)</span><b>${f2(ex.base,4)}</b></div>${bars}
   <div class="muted">Factors multiply the model baseline (a geometric-mean segment, not the average forecast) to give the forecast. They are TreeSHAP attributions of the production model that produced the score: what the model associates with a high casualty count, not causes and not what would cut casualties if changed. Top 5 of 45 shown.</div>`
   : `<div class="muted">Explanation not available for this segment (explanations cover 281,353 of 1.83 million segments).</div>`}</div>
  <div class="sec"><h3>Per-vehicle risk (separate measure)</h3>${rate}</div>
  ${warns.join('')}`;
 document.getElementById('panel').style.display='block';
}
document.getElementById('close').onclick=()=>document.getElementById('panel').style.display='none';
document.getElementById('mode').onchange=draw; document.getElementById('suff').onchange=draw; draw();
</script></body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the explained v2 map.")
    basemap.add_arguments(ap)
    ap.add_argument("--legacy", action="store_true",
                    help="rebuild the original page (hard-coded OpenStreetMap tiles), blackspot_map_v2_explained.html")
    ap.add_argument("--out", type=Path, help="output path (default: the r2 page, or the original with --legacy)")
    a = ap.parse_args(argv)
    d = BACKEND_DATA / "v2"
    ext = d / "extensions"
    gj = json.loads((d / "road_segments_top5000_v2.geojson").read_text())
    meta = json.loads((d / "road_segments_meta_v2.json").read_text())
    v2 = pd.read_csv(d / "road_segments_ranked_v2.csv", low_memory=False).set_index("segment_id")
    stab = pd.read_csv(ext / "segment_stability_v2.csv").set_index("segment_id") if (ext / "segment_stability_v2.csv").exists() else None
    sef = ext / "segment_single_event_sensitivity_v2.csv"
    se = pd.read_csv(sef).set_index("segment_id") if sef.exists() else None
    expl = json.loads((ext / "segment_explanations_top5000_v2.json").read_text())["segments"] \
        if (ext / "segment_explanations_top5000_v2.json").exists() else {}
    for f in gj["features"]:
        sid = f["properties"]["segment_id"]
        r = v2.loc[sid]
        props = {"segment_id": sid}
        for c in PANEL_COLS:
            v = r[c]
            props[c] = None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)
        if stab is not None and sid in stab.index:
            for c in STAB_COLS:
                v = stab.loc[sid, c]
                props[c] = None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)
        if se is not None and sid in se.index:
            for c, short in SE_COLS.items():
                props[short] = se.loc[sid, c].item()
        props["expl"] = expl.get(sid)
        f["properties"] = props
    fp = meta["forecast_years"]
    summ = ML / "reports" / "ranking_stability_summary.json"
    nboot = json.loads(summ.read_text())["replicates"]["bootstrap"] if summ.exists() else "the"
    template = TEMPLATE if a.legacy else basemap.apply(TEMPLATE, basemap.config_from_args(a, meta))
    html = (template.replace("__DATA__", json.dumps(gj, separators=(",", ":")))
            .replace("__N__", f"{len(gj['features']):,}").replace("__NTOT__", f"{meta['n_segments_scored_nationally']:,}")
            .replace("__FP__", f"{fp[0]}-{fp[-1]}")
            .replace("__HP__", f"{meta['history_years'][0]}-{meta['history_years'][-1]}")
            .replace("__NBOOT__", str(nboot)))
    assert "__" not in html.replace("__proto__", ""), "unfilled template placeholder"
    out = a.out or ML / "demo" / ("blackspot_map_v2_explained.html" if a.legacy else "blackspot_map_v2_explained_r2.html")
    write_text(html, out)
    print("wrote", out)


if __name__ == "__main__":
    main()
