/*
  Basemap (map tiles) configuration. Separate from the ML data source (dataSource.js): changing
  tiles never changes which predictions are shown.

    VITE_BASEMAP_URL          XYZ raster template, e.g. https://tiles.example.com/{z}/{x}/{y}.png
                              ({s} subdomain and {r} retina suffix are supported). Unset: the
                              OpenStreetMap standard tile layer (demo default). "none": no basemap,
                              a neutral background and a notice.
    VITE_BASEMAP_ATTRIBUTION  attribution HTML required by the provider (shown on every map).
                              Required whenever VITE_BASEMAP_URL is set.
    VITE_BASEMAP_SUBDOMAINS   letters for {s} (default "abc")
    VITE_BASEMAP_MAX_ZOOM     the provider's maximum zoom (default 19)
    VITE_BASEMAP_FILTER       "auto" (default): darken only the OSM default; "on": always darken
                              (for a light provider); "off": never (for a dark provider)
    VITE_BASEMAP_LABEL        short provider name for the tile-failure notice (default: host name)
    VITE_BASEMAP_CORS         "true" if the provider sends CORS headers. Tiles are then loaded with
                              crossOrigin so a provider's "Access blocked" image can be recognised
                              (src/lib/tileGuard.js). Always on for the OSM default.

  Why OpenStreetMap by default: CARTO Dark Matter (the design system's first choice) now answers
  unauthenticated requests with an "API key required" placeholder tile. The OSM tiles are
  darkened and desaturated with a CSS filter so the basemap stays a quiet graphite ground under
  the risk ramp (DESIGN.md). OpenStreetMap's servers are for light use with attribution
  (https://operations.osmfoundation.org/policies/tiles/): a production deployment must use an
  approved provider (with its own key and terms) or self-hosted tiles. No key is embedded here.

  OSM answers blocked requests with an "Access blocked" image served as HTTP 200, so Leaflet draws
  it as a tile. Seen 2026-10-17 for pages opened from a file, which send no Referer. The map
  recognises that image (tileGuard.js) and drops the basemap instead of showing it. Tiles carry
  the browser's default Referrer-Policy explicitly, as the OSM policy asks.
*/

const env = (typeof import.meta !== 'undefined' && import.meta.env) || {};

export const OSM_DEFAULT = {
  url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
};

export const REFERRER_POLICY = 'strict-origin-when-cross-origin';

export function readBasemapConfig(source = env) {
  if ((source.VITE_BASEMAP_URL || '').trim().toLowerCase() === 'none') {
    return {
      url: '',
      attribution: '',
      attributionText: '',
      subdomains: 'abc',
      maxZoom: 19,
      darken: false,
      label: 'No basemap',
      isDefault: false,
      missingAttribution: false,
      disabled: true,
      cors: false,
      referrerPolicy: REFERRER_POLICY,
    };
  }
  const custom = Boolean(source.VITE_BASEMAP_URL);
  const url = source.VITE_BASEMAP_URL || OSM_DEFAULT.url;
  const filter = (source.VITE_BASEMAP_FILTER || 'auto').toLowerCase();
  let host = '';
  try {
    host = new URL(url.replace(/\{[a-z]+\}/g, '0')).host;
  } catch {
    host = 'the tile provider';
  }
  const attribution = source.VITE_BASEMAP_ATTRIBUTION || (custom ? '' : OSM_DEFAULT.attribution);
  return {
    url,
    attribution,
    attributionText: attribution.replace(/<[^>]+>/g, '').replace(/&copy;/g, '©').trim(),
    subdomains: source.VITE_BASEMAP_SUBDOMAINS || 'abc',
    maxZoom: Number(source.VITE_BASEMAP_MAX_ZOOM) || 19,
    darken: filter === 'on' || (filter === 'auto' && !custom),
    label: source.VITE_BASEMAP_LABEL || host,
    isDefault: !custom,
    // A custom provider without attribution would breach most tile terms; flag it in the UI.
    missingAttribution: custom && !source.VITE_BASEMAP_ATTRIBUTION,
    disabled: false,
    cors: !custom || String(source.VITE_BASEMAP_CORS).toLowerCase() === 'true',
    referrerPolicy: REFERRER_POLICY,
  };
}

export const BASEMAP = readBasemapConfig();

/** A single tile URL (for the inline map crops on the overview page). */
export function tileUrl(z, x, y, cfg = BASEMAP) {
  if (cfg.disabled) return '';
  return cfg.url.replace('{s}', cfg.subdomains[0]).replace('{z}', z).replace('{x}', x).replace('{y}', y).replace('{r}', '');
}
