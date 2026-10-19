/*
  Local basemap settings for the standalone maps in this folder (blackspot_map_v2_r2.html,
  blackspot_map_v2_explained_r2.html).

  Copy this file to basemap.config.js in the same folder and edit it there. basemap.config.js is
  gitignored, so your key stays on your machine. You do not need to regenerate the maps or edit
  any code: reload the page.

  Without basemap.config.js the pages use OpenFreeMap, which needs no key. A ?basemap=<name> in
  the page address overrides everything here, e.g. ...blackspot_map_v2_r2.html?basemap=none

  Providers:
    'openfreemap-positron'  default. No key. https://openfreemap.org/tos/
    'carto-positron'        needs your own CARTO key (free for non-commercial use up to 5 million
                            requests a month): https://carto.com/basemaps/apikey/
                            Terms: https://carto.com/legal/basemap-terms/
    'osm'                   OpenStreetMap standard tiles. Light use only, and only when the page
                            is served over http(s) (never from a double-clicked file).
                            https://operations.osmfoundation.org/policies/tiles/
    'custom'                any raster XYZ provider you are licensed to use (fill in `custom`)
    'none'                  neutral background, no basemap
*/
window.VEYRA_BASEMAP_CONFIG = {
  provider: 'openfreemap-positron',

  // Your own CARTO key, used when provider is 'carto-positron'. Never commit it.
  cartoKey: '',

  // Used when provider is 'custom'. The attribution required by the provider's terms is mandatory.
  custom: {
    label: 'My tile provider',
    url: '',                    // e.g. 'https://tiles.example.com/{z}/{x}/{y}.png?key=YOUR_KEY'
    attribution: '',            // e.g. '&copy; Example provider &copy; OpenStreetMap contributors'
    maxZoom: 18,
    subdomains: 'abc',
    checked: true,              // false only for servers without CORS (blocked replies then cannot be detected)
  },
};
