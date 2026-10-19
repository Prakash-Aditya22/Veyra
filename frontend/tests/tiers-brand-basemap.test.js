/*
  Phase 5: exact, mutually exclusive rank groups; Veyra branding; basemap configuration kept
  separate from the ML data source.
*/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { readBasemapConfig, OSM_DEFAULT, tileUrl } from '../src/config/basemap.js';
import { readDataConfig } from '../src/config/dataSource.js';
import { loadCatalog, createDataSource } from '../src/data/catalog.js';
import { DataSourceError } from '../src/data/localSource.js';
import { normalizeRelease, tierOf } from '../src/data/normalize.js';
import { styledTiers, tierLabel, tierProblems } from '../src/lib/priority.js';
import { PRODUCT, PRODUCT_SUBTITLE } from '../src/lib/usePageTitle.js';
import { ROOT, diskFetch, readJson } from './helpers.js';

const manifest = readJson('manifest.json');
const release = normalizeRelease(manifest);
const N = release.nationalSegments;

test('rank groups partition ranks 1..N with no gap or overlap; the top-1% cutoff is floor(N/100)', () => {
  assert.equal(N, 1827550);
  assert.deepEqual(tierProblems(release.tiers, N), []);
  assert.deepEqual(
    release.tiers.map((t) => [t.min_rank, t.max_rank]),
    [[1, 100], [101, 1000], [1001, 18275], [18276, 1827550]],
  );
  assert.equal(Math.floor(N / 100), 18275);
  assert.equal(manifest.tier_rules.top1pct_cutoff_rank, 18275);
  assert.match(manifest.tier_rules.top1pct_rounding, /rounded down/);
  // every boundary rank belongs to exactly one group
  for (const r of [1, 100, 101, 1000, 1001, 18275, 18276, N]) {
    assert.equal(release.tiers.filter((t) => r >= t.min_rank && r <= t.max_rank).length, 1, `rank ${r}`);
  }
  assert.equal(tierOf(0, release.tiers), null);
  assert.equal(tierOf(N + 1, release.tiers), null);
});

test('displayed labels state exact ranks and match the release labels', () => {
  const styled = styledTiers(release.tiers);
  assert.deepEqual(styled.map((t) => t.label), ['Ranks 1–100', 'Ranks 101–1,000', 'Ranks 1,001–18,275', 'Ranks 18,276–1,827,550']);
  assert.deepEqual(styled.map((t) => t.short), ['1–100', '101–1,000', '1,001–18,275', '18,276+']);
  for (const t of manifest.tiers) assert.equal(t.label, tierLabel(t));
});

test('every loaded segment falls in exactly one group; ranks are untouched', async () => {
  const cat = await loadCatalog(createDataSource({ mode: 'local', localDataUrl: '/x' }, diskFetch()));
  const raw = readJson('segments.json');
  assert.deepEqual(cat.segments.map((s) => s.rank), raw.map((r) => r.rank));
  for (const s of cat.segments) {
    assert.equal(release.tiers.filter((t) => s.rank >= t.min_rank && s.rank <= t.max_rank).length, 1);
    assert.ok(s.tier && s.rank >= s.tier.min_rank && s.rank <= s.tier.max_rank);
  }
});

test('inconsistent rank groups are rejected at load time, not drawn', async () => {
  const bad = structuredClone(manifest);
  bad.tiers[1].min_rank = 100; // overlap with ranks 1-100
  assert.ok(tierProblems(normalizeRelease(bad).tiers, N).some((p) => p.includes('overlap')));
  const gap = structuredClone(manifest);
  gap.tiers[2].min_rank = 1002;
  assert.ok(tierProblems(normalizeRelease(gap).tiers, N).length > 0);
  const cut = structuredClone(manifest);
  cut.tiers[2].max_rank = 18276;
  cut.tiers[3].min_rank = 18277;
  assert.ok(tierProblems(normalizeRelease(cut).tiers, N).some((p) => p.includes('floor')));
  const fetchBad = async (url) => {
    const res = await diskFetch()(url);
    return url.endsWith('manifest.json') ? { ...res, json: async () => bad } : res;
  };
  await assert.rejects(loadCatalog(createDataSource({ mode: 'local', localDataUrl: '/x' }, fetchBad)), DataSourceError);
});

test('Veyra branding: wordmark, subtitle and page title; the old name is gone', () => {
  assert.equal(PRODUCT, 'Veyra');
  assert.equal(PRODUCT_SUBTITLE, 'Great Britain Road Safety Intelligence');
  const html = readFileSync(join(ROOT, 'index.html'), 'utf8');
  assert.match(html, /<title>Veyra · Great Britain Road Safety Intelligence<\/title>/);
  assert.match(html, /Northern Ireland is not covered/);
  assert.match(readFileSync(join(ROOT, 'src/components/Nav.jsx'), 'utf8'), /\{PRODUCT\}/);
  for (const f of ['README.md', 'DESIGN.md', 'BACKEND_INTEGRATION.md', 'package.json']) {
    const t = readFileSync(join(ROOT, f), 'utf8');
    assert.match(t, /Veyra|veyra/, f);
    assert.doesNotMatch(t, /Blackspot Atlas|blackspot-web/, f);
  }
  const scan = (dir) =>
    readdirSync(dir).flatMap((n) => {
      const p = join(dir, n);
      return statSync(p).isDirectory() ? scan(p) : [p];
    });
  const offenders = scan(join(ROOT, 'src')).filter((p) => /Blackspot Atlas|United Kingdom|UK-wide/.test(readFileSync(p, 'utf8')));
  assert.deepEqual(offenders.map((p) => relative(ROOT, p)), []);
});

test('basemap: OSM default darkened with attribution; a custom provider needs its own attribution', () => {
  const d = readBasemapConfig({});
  assert.equal(d.url, OSM_DEFAULT.url);
  assert.equal(d.darken, true);
  assert.match(d.attributionText, /© OpenStreetMap contributors/);
  assert.equal(d.missingAttribution, false);
  const c = readBasemapConfig({ VITE_BASEMAP_URL: 'https://tiles.example.org/dark/{z}/{x}/{y}.png' });
  assert.equal(c.darken, false);
  assert.equal(c.missingAttribution, true);
  assert.equal(c.label, 'tiles.example.org');
  const lit = readBasemapConfig({ VITE_BASEMAP_URL: 'https://t.example.org/{z}/{x}/{y}.png', VITE_BASEMAP_FILTER: 'on', VITE_BASEMAP_ATTRIBUTION: '&copy; Example' });
  assert.equal(lit.darken, true);
  assert.equal(lit.missingAttribution, false);
  assert.equal(tileUrl(6, 31, 20, d), 'https://tile.openstreetmap.org/6/31/20.png');
});

test('basemap and ML data source are configured independently, and tile URLs live only in the basemap config', () => {
  const data = readDataConfig({ VITE_BASEMAP_URL: 'https://tiles.example.org/{z}/{x}/{y}.png' });
  assert.deepEqual(data, readDataConfig({}));
  const scan = (dir) =>
    readdirSync(dir).flatMap((n) => {
      const p = join(dir, n);
      return statSync(p).isDirectory() ? scan(p) : [p];
    });
  const withTiles = scan(join(ROOT, 'src'))
    .filter((p) => /\{z\}\/\{x\}\/\{y\}|tile\.openstreetmap|basemaps\.cartocdn/.test(readFileSync(p, 'utf8')))
    .map((p) => relative(ROOT, p).replace(/\\/g, '/'));
  assert.deepEqual(withTiles, ['src/config/basemap.js']);
});
