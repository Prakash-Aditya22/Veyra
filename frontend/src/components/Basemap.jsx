import { TileLayer } from 'react-leaflet';

/*
  The one dark basemap every map in the app draws on.

  Esri World Dark Gray Canvas, served without an API key. It replaced CARTO
  dark_all, which began answering every tile with an "API KEY REQUIRED" image.
  The canvas comes as two layers, roads and water plus a separate place-name
  layer; both stay in the tile pane, under the markers and route lines.

  Canvas tiles stop at zoom 16; past that Leaflet scales the z16 tiles up
  (maxNativeZoom) instead of requesting tiles that do not exist.

  Esri tile URLs order the path z/y/x, not z/x/y.
*/

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas';
const BASE_URL = `${ESRI}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`;
const LABELS_URL = `${ESRI}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`;

const ATTRIBUTION =
  'Tiles &copy; <a href="https://www.esri.com">Esri</a> &mdash; Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

const NATIVE_MAX = 16;

/** Base tile for a single slippy-map coordinate, for static crops outside Leaflet. */
export function basemapTileUrl(z, x, y) {
  return `${ESRI}/World_Dark_Gray_Base/MapServer/tile/${z}/${y}/${x}`;
}

export default function Basemap() {
  return (
    <>
      <TileLayer url={BASE_URL} attribution={ATTRIBUTION} maxNativeZoom={NATIVE_MAX} maxZoom={19} />
      <TileLayer url={LABELS_URL} maxNativeZoom={NATIVE_MAX} maxZoom={19} />
    </>
  );
}
