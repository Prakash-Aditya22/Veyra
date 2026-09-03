import { tierOf } from './risk.js';

/*
  Explorer's filters, applied to live segments from /api/segments.

  Every group here has a counterpart on the segment record the API returns.
  The fixture's period, road-type and contributing-condition groups are gone
  with the fixture: a 500 m segment aggregates crashes from 2019 to 2021 into
  counts and carries no date, no carriageway classification and no
  per-segment factor attribution. Those three groups could only ever have
  matched nothing, and a filter that silently matches nothing is worse than an
  absent one.

  The evidence floor is deliberately NOT a predicate here. It is `minCrashes`
  on the request, because the six-crash floor is the population the tier
  cutoffs in riskScale.js are calibrated against - lowering it changes which
  rows the server sends, not merely which of them are drawn.

  `sortBlackspots` is shared with Rankings, which still reads the fixture.
  Leave its `lastIncident` handling alone.
*/

export const TIER_FILTERS = [
  { key: 'critical', label: 'Critical, 75 to 100' },
  { key: 'severe', label: 'Severe, 50 to 74' },
  { key: 'elevated', label: 'Elevated, 25 to 49' },
  { key: 'watch', label: 'Watch, 0 to 24' },
  { key: 'nodata', label: 'No data' },
];

/*
  86% of segments rest on fewer than six crashes and their scores are noise.
  Six is the floor the UI shows by default; unchecking the box drops it to one
  and the extra segments arrive flagged as thinly evidenced.
*/
export const MIN_CRASHES_EVIDENCED = 6;
export const MIN_CRASHES_ALL = 1;

export const EMPTY_FILTERS = {
  tiers: [],
  includeThin: false,
  road: '',
};

export function isDefaultFilters(f) {
  return !f.tiers.length && !f.includeThin && !f.road.trim();
}

export function countActive(f) {
  return f.tiers.length + (f.includeThin ? 1 : 0) + (f.road.trim() ? 1 : 0);
}

/** True when one segment survives the client-side groups. */
export function matchesFilters(s, f) {
  if (f.tiers.length && !f.tiers.includes(tierOf(s.score).key)) return false;

  const road = f.road.trim().toLowerCase();
  if (road && !s.roadClass.toLowerCase().includes(road)
      && !s.name.toLowerCase().includes(road)) {
    return false;
  }

  return true;
}

export function applyFilters(segments, f) {
  return segments.filter((s) => matchesFilters(s, f));
}

/** Sorting for the rankings table and the docked results panel. */
export function sortBlackspots(list, key, direction) {
  const dir = direction === 'asc' ? 1 : -1;
  return [...list].sort((a, b) => {
    let av = a[key];
    let bv = b[key];

    // Null scores always sink to the bottom, whichever way the column is sorted.
    if (key === 'score') {
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
    }

    if (typeof av === 'string') return av.localeCompare(bv) * dir;
    return (av - bv) * dir;
  });
}
