/*
  The local demo bundle: Great Britain geography, contract conventions, joins and labelling.
  Values themselves are checked against the ML release on the ML branch by
  ml/audit/validate_frontend_demo.py; these tests need only the bundle.
*/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { BUNDLE, inGB, inIndia, readJson } from './helpers.js';

const manifest = readJson('manifest.json');
const segments = readJson('segments.json');
const geometry = readJson('geometry.geojson');
const ids = new Set(segments.map((s) => s.segment_id));
const SEGMENT_ID = /^[A-Za-z0-9() ]+-[0-9A-F]{12}-[0-9]{2,}$/;

test('bundle declares Great Britain coverage and excludes Northern Ireland', () => {
  assert.equal(manifest.coverage.geography, 'Great Britain (England, Scotland and Wales)');
  assert.match(manifest.coverage.not_covered, /Northern Ireland/);
  assert.equal(manifest.bundle, 'veyra-gb-demo');
});

test('every segment midpoint is in Great Britain and none is in the old Indian fixture region', () => {
  assert.ok(segments.length > 0);
  for (const s of segments) {
    assert.ok(inGB(s.lat, s.lon), `${s.segment_id} outside GB`);
    assert.ok(!inIndia(s.lat, s.lon), `${s.segment_id} inside the old fixture region`);
  }
});

test('GeoJSON is RFC 7946: LineString of [lon, lat] in GB, joined by segment_id, no crs member', () => {
  assert.equal(geometry.type, 'FeatureCollection');
  assert.equal(geometry.crs, undefined);
  const byId = new Map(segments.map((s) => [s.segment_id, s]));
  for (const f of geometry.features) {
    const s = byId.get(f.properties.segment_id);
    assert.ok(s, `geometry for unknown segment ${f.properties.segment_id}`);
    assert.equal(f.geometry.type, 'LineString');
    const c = f.geometry.coordinates;
    assert.ok(new Set(c.map((p) => p.join(','))).size >= 2);
    for (const [lon, lat] of c) assert.ok(inGB(lat, lon), 'position not [lon, lat] in GB');
    // the CSV midpoint lies within the line's bounding box (6 significant digits)
    const lons = c.map((p) => p[0]);
    const lats = c.map((p) => p[1]);
    assert.ok(s.lon >= Math.min(...lons) - 1e-3 && s.lon <= Math.max(...lons) + 1e-3);
    assert.ok(s.lat >= Math.min(...lats) - 1e-3 && s.lat <= Math.max(...lats) + 1e-3);
  }
  assert.equal(geometry.features.length, manifest.selection.with_line_geometry);
});

test('segment IDs follow the contract and are unique; ranks are unique and in order', () => {
  assert.equal(ids.size, segments.length);
  for (const s of segments) assert.match(s.segment_id, SEGMENT_ID);
  const ranks = segments.map((s) => s.rank);
  assert.deepEqual(ranks, [...ranks].sort((a, b) => a - b));
  assert.equal(new Set(ranks).size, ranks.length);
  for (let i = 1; i < segments.length; i += 1) {
    assert.ok(segments[i].blackspot_score <= segments[i - 1].blackspot_score, 'score increases with rank');
  }
});

test('the tied pair keeps the contract tie-break (segment_id ascending)', () => {
  const tie = Object.entries(manifest.selection.reference_cases).filter(([, c]) => c.includes('tie_pair')).map(([id]) => id);
  assert.equal(tie.length, 2);
  const [a, b] = tie.map((id) => segments.find((s) => s.segment_id === id)).sort((x, y) => x.rank - y.rank);
  assert.equal(a.blackspot_score, b.blackspot_score);
  assert.equal(b.rank, a.rank + 1);
  assert.ok(a.segment_id < b.segment_id);
});

test('extension files join on real segment IDs; single-event sensitivity only for the top 1,000', () => {
  for (const name of ['explanations.json', 'stability.json', 'single_event.json']) {
    for (const id of Object.keys(readJson(name))) assert.ok(ids.has(id), `${name}: unknown segment ${id}`);
  }
  const se = readJson('single_event.json');
  for (const id of Object.keys(se)) assert.ok(segments.find((s) => s.segment_id === id).rank <= 1000);
  for (const e of Object.values(readJson('explanations.json'))) {
    assert.deepEqual(e.top.map((f) => f.contrib_rank), [1, 2, 3, 4, 5]);
    for (const f of e.top) assert.ok(Math.abs(Math.exp(f.shap_log) - f.factor) < 1e-3 * f.factor + 1e-6);
  }
});

test('no exposure means no rate: never zero, never filled', () => {
  for (const s of segments) {
    if (!s.exposure_available) {
      assert.equal(s.ksi_per_100m_vkm_eb, null, s.segment_id);
      assert.equal(s.aadf, null, s.segment_id);
    } else {
      assert.ok(s.ksi_per_100m_vkm_eb > 0 && s.aadf > 0, s.segment_id);
      assert.ok(['M', 'A'].includes(s.road_class));
    }
  }
  assert.ok(segments.some((s) => !s.exposure_available), 'fixture lacks a no-exposure case');
});

test('score units and forecast horizon are stated: expected KSI casualties, 2026 and 2027 combined', () => {
  assert.deepEqual(manifest.score.forecast_period, [2026, 2027]);
  assert.deepEqual(manifest.score.history_period, [2023, 2024, 2025]);
  assert.match(manifest.score.units, /killed-or-seriously-injured casualties/);
  assert.match(manifest.score.units, /2026 and 2027 combined/);
  assert.match(manifest.score.kind, /not a probability and not a per-vehicle rate/);
  assert.equal(manifest.release_constants.forecast_period, '2026-2027');
  assert.equal(manifest.score.order_by, 'rank');
});

test('the bundle is labelled as a subset, never as the national map', () => {
  const sel = manifest.selection;
  assert.equal(sel.n_segments, segments.length);
  assert.ok(sel.n_segments < manifest.coverage.national_segments_scored);
  assert.match(sel.not_representative, /not a sample of the national network/);
  assert.equal(sel.n_top + sel.n_reference_cases, sel.n_segments);
  const strata = new Set(segments.map((s) => s.demo_stratum));
  assert.deepEqual([...strata].sort(), ['reference_case', `top_${manifest.generator_args.top}`].sort());
});

test('the bundle covers the required demonstration cases', () => {
  const se = readJson('single_event.json');
  const ex = readJson('explanations.json');
  const has = (pred) => segments.some(pred);
  assert.ok(has((s) => s.rank <= 100), 'high-ranked segment');
  assert.ok(has((s) => s.rank > 18275), 'segment below the top 1%');
  assert.ok(has((s) => s.data_sufficiency === 'none'), 'segment with no recent collisions');
  assert.ok(has((s) => s.single_event_flag && se[s.segment_id]), 'single-event segment with sensitivity');
  assert.ok(has((s) => !s.exposure_available), 'segment without an exposure rate');
  assert.ok(has((s) => s.exposure_available && s.length_m < 250), 'short segment with exposure');
  assert.ok(has((s) => !se[s.segment_id]), 'segment outside the single-event extension');
  assert.ok(segments.every((s) => ex[s.segment_id]), 'every release row has an explanation (none is missing in v2)');
  assert.ok(BUNDLE.endsWith('demo-v2'));
});
