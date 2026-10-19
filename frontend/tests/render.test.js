/*
  What the panel actually says for real records, rendered with the project's own components.
  The test entry is bundled once with the project's Vite (SSR build), then rendered with
  react-dom/server. No browser, no backend.
*/
import { before, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { ROOT, readJson } from './helpers.js';

let render;
let renderLists;
const manifest = readJson('manifest.json');
const segments = readJson('segments.json');
const ex = readJson('explanations.json');
const st = readJson('stability.json');
const se = readJson('single_event.json');
const view = (id, overrides = {}) =>
  render({
    manifest,
    raw: segments.find((s) => s.segment_id === id),
    explanation: ex[id],
    stability: st[id],
    singleEvent: se[id],
    ...overrides,
  });
const text = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

before(async () => {
  // inside node_modules so the SSR bundle resolves react etc. from the project
  const out = join(ROOT, 'node_modules', '.cache', 'render-test');
  mkdirSync(out, { recursive: true });
  await build({
    root: ROOT,
    configFile: false,
    logLevel: 'silent',
    plugins: [react()],
    build: { ssr: join(ROOT, 'tests', 'render-entry.jsx'), outDir: out, emptyOutDir: true, rollupOptions: { output: { entryFileNames: 'entry.mjs' } } },
  });
  ({ render, renderLists } = await import(pathToFileURL(join(out, 'entry.mjs')).href));
  process.on('exit', () => rmSync(out, { recursive: true, force: true }));
});

test('missing explanation renders "Explanation not available", with no factors', () => {
  const v = view('A551-E68F9612B4DB-00', { explanation: undefined });
  assert.match(text(v.explanation), /Explanation not available\./);
  assert.doesNotMatch(v.explanation, /×/);
  assert.doesNotMatch(v.explanation, /factors__row/);
});

test('an available explanation shows the exported labels and factors, framed as attributions', () => {
  const t = text(view('B5339-8AD45E53257A-00').explanation);
  assert.match(t, /Collisions on this segment, last 3 years \(32\)/);
  assert.match(t, /×13\.36/);
  assert.match(t, /not causes/);
});

test('no exposure: the rate block says Not available and shows no number', () => {
  const t = text(view('B5339-8AD45E53257A-00').rate);
  assert.match(t, /^Not available\. No DfT traffic count is matched/);
  assert.doesNotMatch(t, /\d/);
});

test('short segment with exposure: the rate exists in the data but is not displayed', () => {
  const raw = segments.find((s) => s.segment_id === 'A4-FA629E609A3F-00');
  assert.ok(raw.ksi_per_100m_vkm_eb > 0 && raw.length_m < 250);
  const t = text(view('A4-FA629E609A3F-00').rate);
  assert.match(t, /shorter than 250 m/);
  assert.doesNotMatch(t, new RegExp(String(Math.round(raw.ksi_per_100m_vkm_eb))));
});

test('valid exposure: the rate is shown with its period and kept apart from the burden', () => {
  const raw = segments.find((s) => s.segment_id === 'A100-22D1CA35BA35-00');
  const t = text(view('A100-22D1CA35BA35-00').rate);
  assert.match(t, /per 100 million vehicle-km, 2023–25/);
  assert.match(t, new RegExp(raw.ksi_per_100m_vkm_eb.toFixed(1)));
});

test('rank is shown with its refit range, never alone', () => {
  const t = text(view('A57-842C4722100B-00').stability);
  assert.match(t, /#10 of 1,827,550/);
  assert.match(t, /#1 – #687/);
  assert.match(t, /not a confidence interval/);
  const missing = text(view('A57-842C4722100B-00', { stability: undefined }).stability);
  assert.match(missing, /Not available\./);
});

test('single-event wording separates sensitivity from dependence', () => {
  const t = view('A57-842C4722100B-00').singleEventText;
  assert.match(t, /does not lower the model's forecast \(7\.82 instead of 6\.43; rank #2/);
  assert.match(t, /does not require the event, but its forecast is sensitive to it/);
});

test('the badge shows the exact national rank group and the rank, never a 0-100 score', () => {
  const t = text(view('A57-842C4722100B-00').badge);
  assert.equal(t, 'National rank group: Ranks 1–100 , national rank #10');
  assert.equal(text(view('U-A6B609EAE534-00').badgeSmall), 'National rank group: Ranks 18,276+');
  assert.equal(text(view('A6005-C33B1E4E8A91-01').badge), 'National rank group: Ranks 18,276–1,827,550 , national rank #19,459');
  assert.equal(text(view('A551-E68F9612B4DB-00').badge), 'National rank group: Ranks 1,001–18,275 , national rank #5,001');
});

test('filter rail: labelled search, exact rank-group options with counts that read as segments', () => {
  const { rail } = renderLists({ manifest, segments });
  assert.match(rail, /<label[^>]*for="rail-search"[^>]*>Search by road, place or segment ID<\/label>/);
  assert.match(rail, /id="rail-search"[^>]*aria-describedby="rail-search-help rail-count"/);
  const t = text(rail);
  for (const label of ['Ranks 1–100 the national top 100 100 segments', 'Ranks 101–1,000 the rest of the national top 1,000 900 segments']) {
    assert.ok(t.includes(label), label);
  }
  assert.doesNotMatch(t, /Top 1,000|Below top 1%|Top 1%/);
  // disabled Reset explains itself
  assert.match(rail, /disabled=""[^>]*aria-describedby="rail-reset-help"/);
  assert.match(t, /No filters are active, so there is nothing to reset\./);
});

test('results: a real list of focusable buttons, each with a descriptive accessible name', () => {
  const { results } = renderLists({ manifest, segments });
  assert.match(results, /<ul class="results__list" id="segment-list" tabindex="-1" aria-labelledby="segment-list-title" aria-describedby="segment-list-help">/);
  const items = results.match(/<li>/g) ?? [];
  assert.equal(items.length, Math.min(150, segments.length));
  assert.match(results, /aria-label="Rank 10: A57 \(Water Street\) 0\.0-0\.5 km of stretch 178\. 6\.43 expected serious or fatal casualties, 2026–27\. Ranks 1–100\. 7 collisions in 2023–25\. Warning: single-event warning\."/);
  assert.match(text(results), /arrow keys to move between segments/);
});
