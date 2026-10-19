/*
  Loads everything the screens share, once, from whichever source is configured.
  Pure async code (no React), so tests can run it against the real bundle without a browser.
*/

import { DATA_CONFIG } from '../config/dataSource.js';
import { createApiSource } from './apiSource.js';
import { createLocalSource, DataSourceError } from './localSource.js';
import { byRank, normalizeRelease, normalizeSegment, validateSegment } from './normalize.js';
import { tierProblems } from '../lib/priority.js';

export function createDataSource(config = DATA_CONFIG, fetchImpl = globalThis.fetch) {
  if (config.mode === 'local') return createLocalSource({ localDataUrl: config.localDataUrl, fetchImpl });
  if (config.mode === 'api') return createApiSource({ apiBaseUrl: config.apiBaseUrl, fetchImpl });
  throw new DataSourceError(`Unknown VITE_DATA_MODE "${config.mode}". Use "local" or "api".`);
}

/** GeoJSON [lon, lat] positions -> Leaflet [lat, lng], keyed by segment_id. */
export function geometryIndex(fc) {
  const out = new Map();
  for (const f of fc?.features ?? []) {
    if (f.geometry?.type !== 'LineString') continue;
    out.set(f.properties.segment_id, f.geometry.coordinates.map(([lon, lat]) => [lat, lon]));
  }
  return out;
}

export async function loadCatalog(source) {
  const [manifest, rawSegments, geometry, context, summary] = await Promise.all([
    source.getRelease(),
    source.getSegments(),
    source.getGeometry(),
    source.getContext(),
    source.extensionSummary(),
  ]);
  const release = normalizeRelease(manifest);
  // Rank groups must partition ranks 1..N exactly; otherwise legend and filters would mislead.
  const tierIssues = tierProblems(release.tiers, release.nationalSegments);
  if (tierIssues.length) throw new DataSourceError(`The release's rank groups are inconsistent: ${tierIssues.join('; ')}.`);
  const invalid = [];
  const segments = [];
  for (const raw of rawSegments) {
    const problems = validateSegment(raw);
    const seg = problems.length ? null : normalizeSegment(raw, release);
    if (seg && !seg.tier) problems.push(`rank ${raw.rank} is outside every rank group`);
    if (problems.length) invalid.push({ id: raw.segment_id ?? '(no id)', problems });
    else segments.push(seg);
  }
  segments.sort(byRank);
  const lines = geometryIndex(geometry);
  for (const s of segments) {
    s.line = lines.get(s.id) ?? null;
    // null = this source cannot say (e.g. API without a bulk endpoint); false = known absent
    s.ext = summary
      ? {
          hasExplanation: summary.provided.explanations ? summary.leadingFactor.has(s.id) : false,
          leadingFactor: summary.leadingFactor.get(s.id) ?? null,
          stabilityClass: summary.stabilityClass.get(s.id) ?? null,
          rankRange: summary.rankRange.get(s.id) ?? null,
          oneCollisionRank: summary.oneCollisionRank.get(s.id) ?? null,
        }
      : { hasExplanation: null, leadingFactor: null, stabilityClass: null, rankRange: null, oneCollisionRank: null };
  }
  return {
    source: source.describe(),
    release,
    segments,
    byId: new Map(segments.map((s) => [s.id, s])),
    summaryAvailable: summary !== null,
    extensionsProvided: summary?.provided ?? null,
    context,
    invalid,
  };
}
