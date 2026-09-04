import { scoreToDisplay } from './riskScale.js';
import { MIN_CRASHES_EVIDENCED } from './filters.js';

/*
  Everything that crosses the API -> Leaflet boundary.

  The API speaks GeoJSON order - {lon, lat} - and Leaflet speaks [lat, lng].
  Both translations live here, together, rather than one inside each screen:
  they are the same hazard twice, the names differ by a single character, and a
  swap in either puts every marker and every polyline in the wrong place while
  still rendering a plausible-looking map.

  Keeping them out of the screen components is also what makes them testable.
  Importing Explorer.jsx or Route.jsx from a test pulls in Leaflet, which reads
  `window` as it loads and throws under Vitest's node environment; these
  functions depend on nothing but two other lib modules.
*/

/**
 * One API segment in the shape the map, the results panel and the detail
 * panel read.
 *
 * Two things are worth naming. The API reports `lon`; Leaflet takes
 * [lat, lng], so the flip happens here and only here. And `score` is the 0-100
 * display band, while `blackspotScore` stays alongside it as the model's own
 * output - expected KSI casualties over two years - because the detail panel
 * shows the raw figure rather than only its band.
 */
export function toView(s) {
  return {
    id: s.segmentId,
    name: s.location,
    lat: s.lat,
    lng: s.lon,
    score: scoreToDisplay(s.blackspotScore),
    blackspotScore: s.blackspotScore,
    // Recorded counts, 2019 to 2021. Not forecasts, unlike the score above.
    incidents: s.nCrashes,
    ksi: s.nKsi,
    fatal: s.nFatal,
    serious: s.nKsi - s.nFatal,
    slight: s.nCrashes - s.nKsi,
    roadClass: s.roadId,
    speedLimit: s.speedMax,
    pctNight: s.pctNight,
    pctJunction: s.pctJunction,
    kmFrom: s.kmFrom,
    kmTo: s.kmTo,
    rank: s.rank,
    thinlyEvidenced: s.nCrashes < MIN_CRASHES_EVIDENCED,
  };
}

/**
 * A route's geometry, as Leaflet positions. The request is kept in GeoJSON
 * order; only what is about to be drawn is flipped.
 */
export function toLatLngs(geometry) {
  return geometry.map((c) => [c.lat, c.lon]);
}
