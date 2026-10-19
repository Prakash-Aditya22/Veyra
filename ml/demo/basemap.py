"""Configurable, failure-aware basemap for the standalone v2 demo maps (the *_r2.html pages).

Why this exists: the original pages hard-code OpenStreetMap's volunteer tile servers
(tile.openstreetmap.org). Observed on 2026-10-17 with the installed Chrome 155:
- Opened from a file (file://), the page sends no Referer. Every tile then came back as OSM's
  "403 Access blocked: App is not following the tile usage policy" image, all 6,987 bytes.
- Served over http, the same browser on the same machine sent a Referer and got real tiles.
- Headless Chrome (a different User-Agent) got real tiles even without a Referer.
- The block images arrive as HTTP 200 PNGs. Leaflet therefore draws them as valid tiles, and no
  status check can catch them. CARTO's keyless "API KEY REQUIRED" tiles behave the same way.

Providers (terms checked 2026-10-17; recheck before any production use):

- openfreemap-positron (default): https://openfreemap.org. Free, commercial use allowed, no key,
  no registration, no view limits. Vector tiles, drawn by MapLibre GL (needs WebGL). The style
  adds the required attribution itself (OpenFreeMap, OpenMapTiles, OpenStreetMap). Terms
  (https://openfreemap.org/tos/, updated 2026-10-14): integrators must be 18+, no automated
  bulk collection, requests pass through Cloudflare, no availability guarantee.
- carto-positron: raster. Needs your own API key since 25 Sep 2026 (keyless requests get "API KEY
  REQUIRED" tiles). Free for non-commercial use up to 5 M requests a month. Attribution:
  OpenStreetMap contributors and CARTO. https://carto.com/legal/basemap-terms/
- osm: OpenStreetMap standard tiles. Light use only, valid Referer required, so it is refused on
  file:// pages. Serve the page over http(s) to use it.
  https://operations.osmfoundation.org/policies/tiles/
- custom: any raster template you are licensed to use.
- none: neutral background only.

Choosing a provider, with no change to code or the generated HTML (highest priority first):
1. ?basemap=<name> in the page address;
2. ml/demo/basemap.config.js, a local file you create from basemap.config.example.js (it is
   gitignored). Your CARTO key or custom provider goes here, never in the HTML;
3. the build default, openfreemap-positron (the generators' --basemap or --tile-* options).

Whatever the provider, the page never trusts tiles blindly:
- configurations known to break the provider's policy (no key, no Referer) are not requested;
- raster tiles are fetched and rejected unless the response is 2xx with an image type and is not
  OSM's "Access blocked" tile (recognised by its yellow and black edge stripe);
- if the basemap fails, it is removed and a neutral background and a message replace it.

The road segments, forecasts, ranks, legend and data attribution do not depend on the basemap.
"""
from __future__ import annotations

import argparse
import json
import re

MAPLIBRE_VERSION = "5.24.0"
MAPLIBRE_LEAFLET_VERSION = "0.1.3"
TIMEOUT_SECONDS = 15

PROVIDERS = {
    "openfreemap-positron": {
        "kind": "vector",
        "label": "OpenFreeMap",
        "style": "https://tiles.openfreemap.org/styles/positron",
        "maxZoom": 18,
    },
    "carto-positron": {
        "kind": "raster",
        "label": "CARTO",
        "url": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png?key={key}",
        "subdomains": "abcd",
        "maxZoom": 18,
        "requiresKey": True,
        "key": "",                               # supplied at view time by basemap.config.js, never embedded
        "attribution": '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors '
                       '&copy; <a href="https://carto.com/attributions">CARTO</a>',
    },
    "osm": {
        "kind": "raster",
        "label": "OpenStreetMap",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "subdomains": "",
        "maxZoom": 18,
        "requiresReferer": True,
        "attribution": '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
    "none": {"kind": "none", "label": "No basemap", "maxZoom": 18},
}
DEFAULT = "openfreemap-positron"

# The original pages' one tile statement; apply() replaces exactly this.
LEGACY_TILES = re.compile(
    r"L\.tileLayer\('https://tile\.openstreetmap\.org/\{z\}/\{x\}/\{y\}\.png',\{maxZoom:18,\s*"
    r"attribution:'[^']*'\}\)\.addTo\(map\);")
LEAFLET_SCRIPT = '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>'
LOCAL_CONFIG = "basemap.config.js"
MAP_DIV = '<div id="map"></div>'
MAIN_SCRIPT = "<script>\nconst DATA = "

HEAD = f"""
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@{MAPLIBRE_VERSION}/dist/maplibre-gl.css"/>
<script src="https://unpkg.com/maplibre-gl@{MAPLIBRE_VERSION}/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/@maplibre/maplibre-gl-leaflet@{MAPLIBRE_LEAFLET_VERSION}/leaflet-maplibre-gl.js"></script>
<script src="{LOCAL_CONFIG}"></script><!-- optional local settings (basemap.config.example.js); a missing file is fine -->"""

CSS = """ #map.leaflet-container{background:#eceff3}
 .basemap-off .leaflet-tile-pane{display:none}
 .basemap-note{position:absolute;z-index:900;top:12px;right:12px;width:340px;max-width:calc(100vw - 24px);background:#fff;
   border-left:4px solid #8a94a3;border-radius:6px;box-shadow:0 2px 14px rgba(0,0,0,.18);padding:9px 12px;
   font-size:12px;line-height:1.45;color:#1d232b}
 .basemap-note[hidden]{display:none}
 .basemap-note b{display:block;margin-bottom:2px}
 .leaflet-control-attribution{max-width:calc(100vw - 380px);line-height:1.4}
 #panel{max-height:calc(100vh - 72px)}
 @media (max-width:760px){.leaflet-control-attribution{max-width:none} #leg{bottom:84px} #panel{max-height:calc(100vh - 112px)}}
"""

NOTE = """<div id="basemap-note" class="basemap-note" role="status" aria-live="polite" hidden>
  <b>Basemap unavailable</b><span class="why"></span>
  The road segments, forecasts, ranks and legend come from the v2 release, not from the basemap, and are shown in full.
</div>"""

JS = r"""
/* Basemap: configurable and never trusted blindly (ml/demo/basemap.py). */
const StrictTiles = L.TileLayer.extend({
  // Fetch each tile and accept it only if the response is 2xx with an image type, so a
  // provider's "access blocked" or error reply is never drawn as the map background.
  createTile(coords, done) {
    const img = document.createElement('img');
    img.alt = ''; img.setAttribute('role', 'presentation');
    const ctl = window.AbortController ? new AbortController() : null;
    img.basemapAbort = ctl;
    fetch(this.getTileUrl(coords), {mode: 'cors', credentials: 'omit',
        referrerPolicy: this.options.referrerPolicy, signal: ctl ? ctl.signal : undefined})
      .then((r) => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const type = r.headers.get('content-type') || '';
        if (!/^image\//i.test(type)) throw new Error('not an image: ' + (type || 'no content type'));
        return r.blob();
      })
      .then((b) => (window.createImageBitmap ? createImageBitmap(b).then((bmp) => {
        if (isOsmBlockTile(bmp)) throw new Error('the server sent its "Access blocked" image instead of a map tile');
        return b;
      }) : b))
      .then((b) => {
        const u = URL.createObjectURL(b);
        img.onload = () => { URL.revokeObjectURL(u); done(null, img); };
        img.onerror = () => { URL.revokeObjectURL(u); done(new Error('unreadable image'), img); };
        img.src = u;
      })
      .catch((e) => { if (e.name !== 'AbortError') done(e, img); });
    return img;
  },
  _abortLoading() {
    for (const k in this._tiles) {
      const t = this._tiles[k];
      if (t.coords.z !== this._tileZoom && !t.loaded && t.el.basemapAbort) t.el.basemapAbort.abort();
    }
    L.TileLayer.prototype._abortLoading.call(this);
  },
});

// OSM's "Access blocked" tiles carry a pure yellow and black hazard stripe down the left edge
// (columns 8-19, rows 8-239 of 256). They arrive as HTTP 200 PNGs, so only their pixels identify
// them. Map tiles never have this stripe.
const blockCanvas = document.createElement('canvas');
function isOsmBlockTile(img) {
  const w = img.width, h = img.height;
  if (w < 128 || h < 128) return false;
  const k = w / 256, x0 = Math.round(8 * k), y0 = Math.round(8 * k);
  const bw = Math.round(12 * k), bh = Math.round(232 * k);
  blockCanvas.width = bw; blockCanvas.height = bh;
  const ctx = blockCanvas.getContext('2d', {willReadFrequently: true});
  let d;
  try { ctx.clearRect(0, 0, bw, bh); ctx.drawImage(img, x0, y0, bw, bh, 0, 0, bw, bh); d = ctx.getImageData(0, 0, bw, bh).data; }
  catch (e) { return false; }                               // unreadable (no CORS): cannot tell
  let yellow = 0, black = 0;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i] > 230 && d[i + 1] > 230 && d[i + 2] < 40) yellow += 1;
    else if (d[i] < 30 && d[i + 1] < 30 && d[i + 2] < 30 && d[i + 3] > 200) black += 1;
  }
  const n = d.length / 4;
  return yellow / n > 0.3 && black / n > 0.3;
}

function localProviders(cfg, local) {
  // Merge ml/demo/basemap.config.js (window.VEYRA_BASEMAP_CONFIG) into the built-in providers.
  const providers = Object.assign({}, cfg.providers);
  if (!local) return providers;
  if (local.cartoKey) providers['carto-positron'] = Object.assign({}, providers['carto-positron'], {key: String(local.cartoKey).trim()});
  const c = local.custom;
  if (c && c.url) {
    providers.custom = {kind: 'raster', label: c.label || 'Custom basemap', url: String(c.url), attribution: String(c.attribution || '').trim(),
                        maxZoom: Number(c.maxZoom) || 18, subdomains: c.subdomains || 'abc', checked: c.checked !== false};
  }
  return providers;
}

function initBasemap(map, cfg) {
  const note = document.getElementById('basemap-note');
  const box = map.getContainer();
  const local = window.VEYRA_BASEMAP_CONFIG || null;
  const asked = new URLSearchParams(location.search).get('basemap');
  const providers = localProviders(cfg, local);
  const id = String(asked || (local && local.provider) || cfg.default || 'none').trim();
  const source = asked ? 'the page address (?basemap=)' : (local && local.provider) ? 'basemap.config.js' : 'the built-in default';
  const p = providers[id];
  const state = window.VEYRA_BASEMAP = {provider: id, source: source, localConfig: !!local, status: 'loading', reason: null};
  map.attributionControl.addAttribution(cfg.dataAttribution);
  map.setMaxZoom((p && p.maxZoom) || 18);
  let layer = null, timer = null;
  const ok = () => {
    if (state.status !== 'loading') return;
    clearTimeout(timer); state.status = 'ok'; box.classList.remove('basemap-off'); note.hidden = true;
  };
  const fail = (reason) => {
    if (state.status === 'unavailable') return;
    clearTimeout(timer); state.status = 'unavailable'; state.reason = reason;
    if (layer) { try { map.removeLayer(layer); } catch (e) { /* already gone */ } layer = null; }
    box.classList.add('basemap-off');
    note.querySelector('.why').textContent = reason;
    note.hidden = false;
    if (window.console) console.warn('Basemap unavailable: ' + reason);
  };
  box.classList.add('basemap-off');                       // neutral until the basemap proves itself
  if (!p) return fail('No basemap called "' + id + '" is configured (requested by ' + source + ').');
  if (p.kind === 'none') return fail('The basemap is turned off ("none", set by ' + source + ').');
  if (p.requiresKey && !p.key) return fail(p.label + ' basemaps need your own API key. Add it as cartoKey in ml/demo/basemap.config.js (see basemap.config.example.js).');
  if (p.kind === 'raster' && (!/\{z\}/.test(p.url) || !/\{x\}/.test(p.url) || !/\{y\}/.test(p.url) || !p.attribution))
    return fail('The ' + p.label + ' settings need a tile URL with {z}, {x} and {y} and the attribution its terms require.');
  if (p.requiresReferer && location.protocol === 'file:')
    return fail(p.label + "'s tile servers require an HTTP Referer, which browsers do not send for pages opened from a file. It was not contacted. Serve the page over http(s) or use another provider.");
  timer = setTimeout(() => fail(p.label + ' did not load within ' + cfg.timeoutSeconds + ' seconds.'), cfg.timeoutSeconds * 1000);
  if (p.kind === 'vector') {
    const c = document.createElement('canvas');
    if (!(c.getContext('webgl2') || c.getContext('webgl'))) return fail(p.label + ' needs WebGL, which is turned off or unavailable in this browser.');
    if (typeof maplibregl === 'undefined' || !L.maplibreGL) return fail('The ' + p.label + ' map library could not be loaded (offline or blocked).');
    let loaded = false, errors = 0;
    layer = L.maplibreGL({style: p.style, interactive: false}).addTo(map);
    const gl = layer.getMaplibreMap();
    gl.on('load', () => { loaded = true; ok(); });
    gl.on('error', (e) => {
      const err = (e && e.error) || {};
      const msg = err.status ? 'HTTP ' + err.status : (err.message || 'unknown error');
      errors += 1;
      if (!loaded && (!err.url || String(err.url).indexOf(p.style) === 0)) fail(p.label + ' could not load its map style (' + msg + ').');
      else if (errors >= 6) fail(p.label + ' is not returning map tiles (' + msg + ').');
    });
    return undefined;
  }
  const opts = {maxZoom: p.maxZoom || 18, subdomains: p.subdomains || 'abc', attribution: p.attribution || '',
                key: p.key ? encodeURIComponent(p.key) : '', referrerPolicy: 'strict-origin-when-cross-origin'};
  layer = p.checked === false ? L.tileLayer(p.url, opts) : new StrictTiles(p.url, opts);
  let good = 0, bad = 0, first = '';
  layer.on('tileload', () => { good += 1; if (good >= 2) ok(); });
  layer.on('tileerror', (e) => {
    bad += 1; first = first || (e.error && e.error.message) || 'tile failed';
    if ((good === 0 && bad >= 4) || (bad >= 8 && bad > good)) fail(p.label + ' is not returning usable map tiles (' + first + ').');
  });
  layer.addTo(map);
  return undefined;
}
"""


def data_attribution(os_year: int) -> str:
    """Credits for the data drawn on the map; shown whatever happens to the basemap."""
    return ('Road geometry: <a href="https://www.ordnancesurvey.co.uk/products/os-open-roads">OS Open Roads</a>, '
            f'contains OS data &copy; Crown copyright and database right {os_year} | '
            'Collisions and traffic counts: DfT STATS19 and AADF, '
            '<a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">'
            'Open Government Licence v3.0</a>')


def os_year(meta: dict) -> int:
    """Release year of the OS Open Roads data the segments were cut from (release metadata)."""
    m = re.search(r"OS Open Roads centrelines \((\d{4})-\d{2} release\)", meta.get("segmentation", ""))
    if not m:
        raise ValueError("road_segments_meta_v2.json does not name the OS Open Roads release")
    return int(m.group(1))


def add_arguments(ap: argparse.ArgumentParser) -> None:
    g = ap.add_argument_group("basemap (see ml/demo/basemap.py for each provider's terms)")
    g.add_argument("--basemap", default=DEFAULT, choices=[*PROVIDERS, "custom"],
                   help=f"default provider (default {DEFAULT}); a viewer can switch with ?basemap=<name>")
    g.add_argument("--tile-url", help="custom raster template with {z}/{x}/{y} (requires --tile-attribution)")
    g.add_argument("--tile-attribution", help="attribution HTML required by the custom provider's terms")
    g.add_argument("--tile-label", default="Custom basemap")
    g.add_argument("--tile-max-zoom", type=int, default=18)
    g.add_argument("--tile-subdomains", default="abc")
    g.add_argument("--tile-unchecked", action="store_true",
                   help="load custom tiles as plain images (for servers without CORS); blocked replies cannot be detected")


def config(default: str = DEFAULT, *, custom: dict | None = None,
           os_release_year: int, timeout: int = TIMEOUT_SECONDS) -> dict:
    """Build-time settings embedded in the page. Keys never go here: see basemap.config.example.js."""
    providers = json.loads(json.dumps(PROVIDERS))
    if custom is not None:
        url, attribution = custom.get("url") or "", (custom.get("attribution") or "").strip()
        if not all(t in url for t in ("{z}", "{x}", "{y}")):
            raise ValueError("--tile-url must contain {z}, {x} and {y}")
        if not attribution:
            raise ValueError("--tile-attribution is required: every tile provider's terms require attribution")
        providers["custom"] = {"kind": "raster", "label": custom.get("label") or "Custom basemap", "url": url,
                               "attribution": attribution, "maxZoom": int(custom.get("maxZoom", 18)),
                               "subdomains": custom.get("subdomains", "abc"),
                               "checked": not custom.get("unchecked", False)}
    if default not in providers:
        raise ValueError(f"unknown basemap {default!r}; choose from {sorted(providers)}")
    return {"default": default, "providers": providers, "timeoutSeconds": timeout,
            "dataAttribution": data_attribution(os_release_year)}


def config_from_args(a: argparse.Namespace, meta: dict) -> dict:
    custom = None
    if a.basemap == "custom" or a.tile_url:
        custom = {"url": a.tile_url, "attribution": a.tile_attribution, "label": a.tile_label,
                  "maxZoom": a.tile_max_zoom, "subdomains": a.tile_subdomains, "unchecked": a.tile_unchecked}
    return config(a.basemap, custom=custom, os_release_year=os_year(meta))


def apply(template: str, cfg: dict) -> str:
    """Swap the original pages' hard-coded OSM tile statement for the configurable basemap."""
    for marker in (LEAFLET_SCRIPT, MAP_DIV, MAIN_SCRIPT, "</style>"):
        if template.count(marker) != 1:
            raise ValueError(f"template does not contain exactly one {marker!r}")
    if len(LEGACY_TILES.findall(template)) != 1:
        raise ValueError("template does not contain exactly one hard-coded OpenStreetMap tile statement")
    blob = json.dumps(cfg, separators=(",", ":")).replace("<", "\\u003c")
    out = LEGACY_TILES.sub(lambda _: "initBasemap(map, BASEMAP_CONFIG);", template)
    out = out.replace(LEAFLET_SCRIPT, LEAFLET_SCRIPT + HEAD)
    out = out.replace("</style>", CSS + "</style>")
    out = out.replace(MAP_DIV, MAP_DIV + "\n" + NOTE)
    return out.replace(MAIN_SCRIPT, f"<script>{JS}const BASEMAP_CONFIG = {blob};\n</script>\n" + MAIN_SCRIPT)
