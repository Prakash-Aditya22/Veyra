/*
  The data layer (adapter + normalisation) against the real bundle, with no browser and no
  backend: rank order, joins, missing-data handling and the API-mode boundary.
*/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readDataConfig } from '../src/config/dataSource.js';
import { createDataSource, loadCatalog } from '../src/data/catalog.js';
import { NotAgreedError } from '../src/data/apiSource.js';
import { DataSourceError } from '../src/data/localSource.js';
import {
  byRank,
  explanationView,
  normalizeRelease,
  normalizeSegment,
  rateView,
  singleEventView,
  stabilityView,
  tierOf,
  validateSegment,
} from '../src/data/normalize.js';
import { applyFilters, EMPTY_FILTERS, sortSegments } from '../src/lib/filters.js';
import { summarize } from '../src/lib/stats.js';
import { diskFetch, readJson } from './helpers.js';

const local = (opts) => createDataSource({ mode: 'local', localDataUrl: '/data/demo-v2' }, diskFetch(opts));
const segRaw = readJson('segments.json');
const release = normalizeRelease(readJson('manifest.json'));
const seg = (id) => normalizeSegment(segRaw.find((s) => s.segment_id === id), release);

test('config defaults to the local bundle; API mode needs an explicit base URL', () => {
  assert.deepEqual(readDataConfig({}), { mode: 'local', apiBaseUrl: '', localDataUrl: '/data/demo-v2' });
  assert.equal(readDataConfig({ VITE_DATA_MODE: 'api', VITE_API_BASE_URL: 'http://x/api/' }).apiBaseUrl, 'http://x/api');
  assert.throws(() => createDataSource({ mode: 'api', apiBaseUrl: '' }), DataSourceError);
  assert.throws(() => createDataSource({ mode: 'other' }), DataSourceError);
});

test('API mode never invents data: unagreed endpoints fail loudly', async () => {
  const api = createDataSource({ mode: 'api', apiBaseUrl: 'http://backend.invalid' }, async () => {
    throw new Error('network must not be called for release metadata');
  });
  await assert.rejects(api.getRelease(), NotAgreedError);
  assert.equal(await api.getSingleEvent('x'), null);
  assert.equal(await api.extensionSummary(), null);
});

test('the local demo loads without a backend, in rank order, with geometry joined by segment_id', async () => {
  const cat = await loadCatalog(local());
  assert.equal(cat.invalid.length, 0);
  assert.equal(cat.segments.length, segRaw.length);
  assert.deepEqual(cat.segments.map((s) => s.rank), [...cat.segments].sort(byRank).map((s) => s.rank));
  const withLine = cat.segments.filter((s) => s.line);
  assert.equal(withLine.length, readJson('geometry.geojson').features.length);
  for (const s of withLine) {
    const [lat, lon] = s.line[0]; // Leaflet order after conversion
    assert.ok(lat > 49 && lat < 61 && lon > -9 && lon < 2);
  }
  assert.ok(cat.segments.every((s) => s.ext.hasExplanation === true));
});

test('a missing optional extension degrades to "not available", never to fabricated values', async () => {
  for (const htmlFallback of [false, true]) {
    const cat = await loadCatalog(local({ missing: ['explanations.json', 'stability.json', 'single_event.json'], htmlFallback }));
    assert.equal(cat.segments.length, segRaw.length);
    assert.ok(cat.segments.every((s) => s.ext.hasExplanation === false && s.ext.stabilityClass === null));
    const src = local({ missing: ['explanations.json'], htmlFallback });
    const e = explanationView(await src.getExplanation(cat.segments[0].id));
    assert.equal(e.available, false);
    assert.equal(e.headline, 'Explanation not available.');
    assert.equal(e.factors, undefined);
  }
});

test('a missing required file is an error, not an empty map', async () => {
  await assert.rejects(loadCatalog(local({ missing: ['segments.json'] })), DataSourceError);
  await assert.rejects(loadCatalog(local({ missing: ['manifest.json'], htmlFallback: true })), DataSourceError);
});

test('rates: shown only with exposure and length >= 250 m; otherwise a reason, never 0', () => {
  for (const raw of segRaw) {
    const s = normalizeSegment(raw, release);
    const r = rateView(s);
    if (!raw.exposure_available || raw.length_m < 250) {
      assert.equal(r.available, false);
      assert.equal(r.value, undefined);
      assert.ok(r.reason.length > 20);
    } else {
      assert.equal(r.value, raw.ksi_per_100m_vkm_eb);
    }
  }
  assert.match(rateView(seg('B5339-8AD45E53257A-00')).reason, /No DfT traffic count/);
  assert.match(rateView(seg('A4-FA629E609A3F-00')).reason, /shorter than 250 m/);
});

test('explanations come from the export and keep its order; absence is explicit', () => {
  const ex = readJson('explanations.json');
  const v = explanationView(ex['B5339-8AD45E53257A-00']);
  assert.equal(v.available, true);
  assert.equal(v.factors.length, 5);
  assert.equal(v.factors[0].label, 'Collisions on this segment, last 3 years');
  assert.equal(v.base, 0.0064);
  for (const missing of [null, undefined, { top: [] }]) assert.equal(explanationView(missing).available, false);
});

test('single-event sensitivity uses the one-at-a-time rank; Water Street rises without the event', () => {
  const ws = seg('A57-842C4722100B-00');
  const v = singleEventView(ws, readJson('single_event.json')['A57-842C4722100B-00']);
  assert.equal(v.flagged, true);
  assert.equal(v.sensitivity.direction, 'rises');
  assert.equal(v.sensitivity.rankWithout, 2);
  assert.equal(v.sensitivity.forecastWithout, 7.8219);
  const outside = singleEventView(seg('U-A6B609EAE534-00'), undefined);
  assert.equal(outside.sensitivity.available, false);
});

test('stability view passes values through; absence is explicit', () => {
  const st = stabilityView(readJson('stability.json')['A57-842C4722100B-00']);
  assert.deepEqual([st.p05, st.p95, st.freqTop1000], [1, 687, 1]);
  assert.equal(stabilityView(null).available, false);
});

test('rank tiers follow the published boundaries; ordering is by rank, never by rounded score', () => {
  assert.equal(tierOf(1, release.tiers).key, 'top100');
  assert.equal(tierOf(1000, release.tiers).key, 'top1000');
  assert.equal(tierOf(1001, release.tiers).key, 'top1pct');
  assert.equal(tierOf(18276, release.tiers).key, 'below1pct');
  const all = segRaw.map((r) => normalizeSegment(r, release));
  const shuffled = [...all].reverse();
  assert.deepEqual(sortSegments(shuffled, 'rank').map((s) => s.id), all.map((s) => s.id));
  const tie = all.filter((s) => s.id.startsWith('A6005-C33B1E4E8A91'));
  assert.equal(tie[0].score, tie[1].score);
  assert.deepEqual(sortSegments([tie[1], tie[0]], 'rank').map((s) => s.id), [tie[0].id, tie[1].id]);
});

test('validation rejects incomplete or inconsistent records', () => {
  const ok = segRaw[0];
  assert.deepEqual(validateSegment(ok), []);
  assert.ok(validateSegment({ ...ok, rank: undefined }).some((p) => p.includes('rank')));
  assert.ok(validateSegment({ ...ok, exposure_available: false, ksi_per_100m_vkm_eb: 0 }).includes('rate present without exposure'));
});

test('filters and summaries name their denominators and use real fields only', () => {
  const all = segRaw.map((r) => normalizeSegment(r, release));
  assert.equal(applyFilters(all, EMPTY_FILTERS).length, all.length);
  const a = applyFilters(all, { ...EMPTY_FILTERS, roadClasses: ['A'] });
  assert.ok(a.length > 0 && a.every((s) => s.roadClass === 'A'));
  const q = applyFilters(all, { ...EMPTY_FILTERS, query: 'water street' });
  assert.ok(q.some((s) => s.id === 'A57-842C4722100B-00'));
  const byId = applyFilters(all, { ...EMPTY_FILTERS, query: 'B5339-8AD45E53257A-00' });
  assert.deepEqual(byId.map((s) => s.id), ['B5339-8AD45E53257A-00']);
  const s = summarize(all);
  assert.equal(s.n, all.length);
  assert.ok(Math.abs(s.expectedKsi - all.reduce((t, x) => t + x.score, 0)) < 1e-9);
  assert.ok(s.rateShown < s.n);
});
