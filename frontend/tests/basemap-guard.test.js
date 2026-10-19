/*
  Basemap failure handling. OpenStreetMap answers blocked requests with an "Access blocked" image
  served as HTTP 200, so it must be recognised from its pixels; "none" turns the basemap off.
*/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { readBasemapConfig, tileUrl, REFERRER_POLICY } from '../src/config/basemap.js';
import { BLOCK_BAND, isOsmBlockBand } from '../src/lib/tileGuard.js';
import { ROOT } from './helpers.js';

const { width: W, height: H } = BLOCK_BAND;

function band(pixel) {
  const out = new Uint8ClampedArray(W * H * 4);
  for (let y = 0; y < H; y += 1) {
    for (let x = 0; x < W; x += 1) out.set(pixel(x, y), (y * W + x) * 4);
  }
  return out;
}

test('the hazard stripe of an OSM "Access blocked" tile is recognised', () => {
  // diagonal yellow/black bands, as on the block tile (pure yellow, near-black)
  const stripe = band((x, y) => (Math.floor((x + y) / 12) % 2 ? [255, 255, 0, 255] : [1, 1, 1, 255]));
  assert.equal(isOsmBlockBand(stripe), true);
});

test('ordinary map content is not mistaken for a block tile', () => {
  const land = band(() => [242, 239, 233, 255]); // OSM land
  const water = band(() => [170, 211, 223, 255]);
  const road = band((x) => (x < 4 ? [252, 214, 164, 255] : [242, 239, 233, 255])); // primary road edge
  const text = band((x, y) => (y % 10 < 3 ? [20, 20, 20, 255] : [242, 239, 233, 255])); // black label rows, 30%
  const darkened = band(() => [24, 24, 26, 255]); // a dark provider: black but no yellow
  for (const b of [land, water, road, text, darkened]) assert.equal(isOsmBlockBand(b), false);
  assert.equal(isOsmBlockBand(new Uint8ClampedArray(0)), false);
});

test('basemap "none": no tiles, no basemap attribution, neutral fallback', () => {
  const off = readBasemapConfig({ VITE_BASEMAP_URL: 'none' });
  assert.equal(off.disabled, true);
  assert.equal(off.url, '');
  assert.equal(off.attribution, '');
  assert.equal(tileUrl(6, 31, 20, off), '');
});

test('OSM default is loaded with CORS so its block image can be read; custom providers opt in', () => {
  const d = readBasemapConfig({});
  assert.equal(d.cors, true);
  assert.equal(d.disabled, false);
  assert.equal(d.referrerPolicy, REFERRER_POLICY);
  const c = readBasemapConfig({ VITE_BASEMAP_URL: 'https://t.example.org/{z}/{x}/{y}.png', VITE_BASEMAP_ATTRIBUTION: '&copy; Example' });
  assert.equal(c.cors, false);
  assert.equal(readBasemapConfig({ VITE_BASEMAP_URL: 'https://t.example.org/{z}/{x}/{y}.png', VITE_BASEMAP_CORS: 'true' }).cors, true);
});

test('the map drops a blocked or failing basemap and keeps the data credits', () => {
  const src = readFileSync(join(ROOT, 'src/components/MapCanvas.jsx'), 'utf8');
  assert.match(src, /isOsmBlockTile\(e\.tile\)/);
  assert.match(src, /\{!basemapOff && \(/); // tile layer unmounted when off
  assert.match(src, /<DataAttribution \/>/); // OS Open Roads and STATS19 credits independent of tiles
  assert.match(src, /Basemap unavailable/);
});
