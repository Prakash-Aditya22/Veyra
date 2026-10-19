import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
export const BUNDLE = join(ROOT, 'public', 'data', 'demo-v2');

export const readJson = (name, dir = BUNDLE) => JSON.parse(readFileSync(join(dir, name), 'utf8'));

// Great Britain incl. islands (WGS84), as in the ML integration contract.
export const GB = { lon: [-8.7, 2.0], lat: [49.8, 61.0] };
export const inGB = (lat, lon) => lat >= GB.lat[0] && lat <= GB.lat[1] && lon >= GB.lon[0] && lon <= GB.lon[1];
// The previous fixture's region (Odisha, India): nothing may fall inside it.
export const inIndia = (lat, lon) => lat >= 6 && lat <= 37 && lon >= 68 && lon <= 98;

/**
 * fetch() replacement that serves the bundle from disk. `missing` lists files that should
 * behave as absent; `htmlFallback` mimics a static host answering a missing file with
 * index.html (status 200, text/html), as the Vite dev server does.
 */
export function diskFetch({ dir = BUNDLE, missing = [], htmlFallback = false } = {}) {
  return async (url) => {
    const name = url.split('/').pop();
    const path = join(dir, name);
    if (missing.includes(name) || !existsSync(path)) {
      if (htmlFallback) {
        return { ok: true, status: 200, headers: { get: () => 'text/html' }, json: async () => { throw new SyntaxError('html'); } };
      }
      return { ok: false, status: 404, headers: { get: () => 'text/plain' }, json: async () => null };
    }
    const body = readFileSync(path, 'utf8');
    return { ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => JSON.parse(body) };
  };
}
