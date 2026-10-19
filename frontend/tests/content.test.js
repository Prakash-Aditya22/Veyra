/*
  No trace of the Indian demonstration fixture or the fictitious 0-100 danger score remains in
  the source, the page shell, the docs or the built bundle (when one exists).
*/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { ROOT } from './helpers.js';

const BANNED = [
  /Bhubaneswar/i, /Cuttack/i, /\bPuri\b/, /Odisha/i, /\bIndia\b/i, /\bNH-\d/, /\bSH-\d/, /en-IN/,
  /monsoon/i, /DBSCAN/, /macroF1/, /recallFatal/, /danger score/i, /composite (danger )?score/i, /0 to 100/, /\bkm\/h\b/,
  /AccidentsBig/, /Rasulgarh/i, /BBS-C\d/, /\bcluster=/, /isDemo/,
];

function files(dir, exts) {
  const out = [];
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === 'tests') continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...files(p, exts));
    else if (exts.some((e) => name.endsWith(e))) out.push(p);
  }
  return out;
}

function scan(paths) {
  const hits = [];
  for (const p of paths) {
    const text = readFileSync(p, 'utf8');
    for (const re of BANNED) if (re.test(text)) hits.push(`${relative(ROOT, p)}: ${re}`);
  }
  return hits;
}

test('source, page shell and docs are free of the Indian fixture and the 0-100 score', () => {
  const paths = [
    ...files(join(ROOT, 'src'), ['.js', '.jsx', '.css']),
    join(ROOT, 'index.html'),
    join(ROOT, 'README.md'),
    join(ROOT, 'DESIGN.md'),
    join(ROOT, 'BACKEND_INTEGRATION.md'),
  ].filter(existsSync);
  assert.deepEqual(scan(paths), []);
});

test('the old fixture modules are gone', () => {
  for (const f of ['src/data/blackspots.js', 'src/data/series.js', 'src/lib/risk.js', 'src/components/RiskBadge.jsx']) {
    assert.equal(existsSync(join(ROOT, f)), false, f);
  }
});

test('the built bundle (if present) carries no fixture strings', { skip: !existsSync(join(ROOT, 'dist')) && 'run npm run build first' }, () => {
  assert.deepEqual(scan(files(join(ROOT, 'dist'), ['.js', '.html', '.css'])), []);
});

test('no hard-coded data paths or API URLs outside the configuration module', () => {
  const offenders = files(join(ROOT, 'src'), ['.js', '.jsx'])
    .filter((p) => !p.includes(join('src', 'config')))
    // string literals holding the bundle path or an API URL
    .filter((p) => /['"`][^'"`]*data\/demo-v2|['"`]https?:\/\/[^'"`]*\/api/.test(readFileSync(p, 'utf8')))
    .map((p) => relative(ROOT, p));
  assert.deepEqual(offenders, []);
});
