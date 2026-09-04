import { describe, it, expect } from 'vitest';
import { toView, toLatLngs } from './geo.js';

/*
  The single seam where the API's GeoJSON order becomes Leaflet's.

  The API speaks {lon, lat}; Leaflet takes [lat, lng]. Every coordinate that
  crosses that boundary passes through one of these two functions, so a swap
  here puts every marker and every polyline in the wrong place - and the two
  names differ by one character, which is exactly the kind of mistake a
  reviewer's eye slides over. These are the assertions that would catch it.

  The fixtures use British coordinates where latitude and longitude cannot be
  confused for one another: latitude ~51 is far outside the -0.x longitude
  range, so a flipped pair fails loudly rather than merely reading oddly.
*/

const SEGMENT = {
  segmentId: 'A23_run3_km0.5',
  roadId: 'A23',
  run: 3,
  location: 'A23 km 0.5-1.0 (seg 3)',
  kmFrom: 0.5,
  kmTo: 1.0,
  lat: 51.4607,
  lon: -0.116,
  blackspotScore: 9.67,
  rank: 1,
  nCrashes: 60,
  nKsi: 10,
  nFatal: 2,
  ksiRate: 0.167,
  crashesPerYear: 20.0,
  speedMax: 30.0,
  pctNight: 0.233,
  pctJunction: 0.7,
};

describe('toView', () => {
  it('renames lon to lng without swapping the values', () => {
    const v = toView(SEGMENT);
    expect(v.lat).toBe(51.4607);
    expect(v.lng).toBe(-0.116);
    // The API's own name must not survive alongside the renamed one: two
    // spellings of the same field is how one of them goes stale.
    expect(v.lon).toBeUndefined();
  });

  it('carries the identity and the raw model output through', () => {
    const v = toView(SEGMENT);
    expect(v.id).toBe('A23_run3_km0.5');
    expect(v.name).toBe('A23 km 0.5-1.0 (seg 3)');
    // The 0-100 band and the model's own figure both survive; the detail
    // panel shows the raw expected-KSI value, not only its tier.
    expect(v.blackspotScore).toBe(9.67);
    expect(v.score).toBe(100);
  });

  it('maps the recorded counts, which are counts and not estimates', () => {
    const v = toView(SEGMENT);
    expect(v.incidents).toBe(60);
    expect(v.ksi).toBe(10);
    expect(v.fatal).toBe(2);
    expect(v.serious).toBe(8); // nKsi - nFatal
    expect(v.slight).toBe(50); // nCrashes - nKsi
  });

  it('flags a segment under the six-crash evidence floor', () => {
    expect(toView({ ...SEGMENT, nCrashes: 5 }).thinlyEvidenced).toBe(true);
    expect(toView({ ...SEGMENT, nCrashes: 6 }).thinlyEvidenced).toBe(false);
  });

  it('gives a null score the No-data band rather than a low one', () => {
    expect(toView({ ...SEGMENT, blackspotScore: null }).score).toBeNull();
  });
});

describe('toLatLngs', () => {
  it('flips each {lon, lat} into [lat, lng] in order', () => {
    const geometry = [
      { lon: -0.0982, lat: 51.3762 },
      { lon: -0.1426, lat: 51.539 },
    ];
    expect(toLatLngs(geometry)).toEqual([
      [51.3762, -0.0982],
      [51.539, -0.1426],
    ]);
  });

  it('preserves vertex order, which is what makes the line a journey', () => {
    const geometry = [
      { lon: -0.1, lat: 51.1 },
      { lon: -0.2, lat: 51.2 },
      { lon: -0.3, lat: 51.3 },
    ];
    expect(toLatLngs(geometry).map((p) => p[0])).toEqual([51.1, 51.2, 51.3]);
  });

  it('handles an empty geometry without inventing a point', () => {
    expect(toLatLngs([])).toEqual([]);
  });
});
