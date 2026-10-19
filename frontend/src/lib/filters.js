import { ROAD_CLASS_LABELS, SUFFICIENCY_LABELS, rateView } from '../data/normalize.js';
import { tierLabel } from './priority.js';

/*
  Filters over fields that exist in the v2 release. There is no region or local-authority
  filter: the release has no reliable administrative field (`spatial_block` is a 50 km
  validation grid, not an area). Filters that need an optional extension are offered only when
  the data source provides it.
*/

export const EMPTY_FILTERS = {
  query: '',
  tiers: [],
  roadClasses: [],
  sufficiency: [],
  flags: [],
  rate: [],
  explanation: [],
  stability: [],
};

export const FLAG_OPTIONS = [
  { key: 'single_event', label: 'Single-event concentration (one collision dominates the history)' },
  { key: 'one_collision', label: 'Leaves the top 1,000 without its largest collision' },
];

export const RATE_OPTIONS = [
  { key: 'shown', label: 'Per-vehicle rate available' },
  { key: 'not_available', label: 'Per-vehicle rate not available' },
];

export const EXPLANATION_OPTIONS = [
  { key: 'available', label: 'Model explanation available' },
  { key: 'not_available', label: 'Explanation not available' },
];

export const STABILITY_OPTIONS = [
  { key: 'robust top-1000', label: 'Robust top 1,000 (in 90% or more of refits)' },
  { key: 'borderline top-1000', label: 'Borderline top 1,000 (50 to 90%)' },
  { key: 'robust top-5%', label: 'Robust top 5%' },
  { key: 'variable', label: 'Variable' },
];

/** Options with counts, only for values present in the loaded data. */
export function filterOptions(segments, tiers) {
  const count = (pred) => segments.filter(pred).length;
  return {
    tiers: tiers
      .map((t) => ({ key: t.key, label: tierLabel(t), hint: t.description, n: count((s) => s.tier?.key === t.key) }))
      .filter((o) => o.n),
    roadClasses: Object.entries(ROAD_CLASS_LABELS)
      .map(([key, label]) => ({ key, label, n: count((s) => s.roadClass === key) }))
      .filter((o) => o.n),
    sufficiency: Object.entries(SUFFICIENCY_LABELS)
      .map(([key, label]) => ({ key, label, n: count((s) => s.history.sufficiency === key) }))
      .filter((o) => o.n),
    flags: FLAG_OPTIONS.map((o) => ({ ...o, n: count((s) => matchesFlag(s, o.key)) })),
    rate: RATE_OPTIONS.map((o) => ({ ...o, n: count((s) => rateKey(s) === o.key) })),
    explanation: segments.some((s) => s.ext?.hasExplanation === null)
      ? []
      : EXPLANATION_OPTIONS.map((o) => ({ ...o, n: count((s) => explanationKey(s) === o.key) })),
    stability: STABILITY_OPTIONS.map((o) => ({ ...o, n: count((s) => s.ext?.stabilityClass === o.key) })).filter((o) => o.n),
  };
}

function matchesFlag(s, key) {
  if (key === 'single_event') return s.singleEvent.flag;
  if (key === 'one_collision') return s.rank <= 1000 && s.ext?.oneCollisionRank != null && s.ext.oneCollisionRank > 1000;
  return false;
}

const rateKey = (s) => (rateView(s).available ? 'shown' : 'not_available');
const explanationKey = (s) => (s.ext?.hasExplanation ? 'available' : 'not_available');

/** Case-insensitive match on location, road number, name, class letter or segment ID. */
export function matchesQuery(s, query) {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [s.location, s.roadId, s.roadName, s.roadNumber, s.id]
    .filter(Boolean)
    .some((v) => String(v).toLowerCase().includes(q));
}

export function applyFilters(segments, f) {
  return segments.filter((s) => {
    if (!matchesQuery(s, f.query)) return false;
    if (f.tiers.length && !f.tiers.includes(s.tier?.key)) return false;
    if (f.roadClasses.length && !f.roadClasses.includes(s.roadClass)) return false;
    if (f.sufficiency.length && !f.sufficiency.includes(s.history.sufficiency)) return false;
    if (f.flags.length && !f.flags.every((k) => matchesFlag(s, k))) return false;
    if (f.rate.length && !f.rate.includes(rateKey(s))) return false;
    if (f.explanation.length && !f.explanation.includes(explanationKey(s))) return false;
    if (f.stability.length && !f.stability.includes(s.ext?.stabilityClass)) return false;
    return true;
  });
}

export function countActive(f) {
  return (f.query.trim() ? 1 : 0) + Object.entries(f).filter(([k, v]) => k !== 'query' && v.length).reduce((n, [, v]) => n + v.length, 0);
}

export function isDefaultFilters(f) {
  return countActive(f) === 0;
}

/** Table sorting. Ranking order always comes from `rank`, never from the rounded score. */
export const SORTS = {
  rank: { label: 'National rank', value: (s) => s.rank, dir: 'asc' },
  collisions: { label: 'Collisions 2023–25', value: (s) => s.history.collisions, dir: 'desc' },
  ksiHistory: { label: 'Serious/fatal casualties 2023–25', value: (s) => s.history.ksiCasualtiesAdjusted, dir: 'desc' },
  name: { label: 'Road name', value: (s) => s.location, dir: 'asc' },
};

export function sortSegments(list, key = 'rank', direction) {
  const spec = SORTS[key] ?? SORTS.rank;
  const dir = (direction ?? spec.dir) === 'asc' ? 1 : -1;
  return [...list].sort((a, b) => {
    const av = spec.value(a);
    const bv = spec.value(b);
    const c = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
    return c !== 0 ? c * dir : a.rank - b.rank; // ties fall back to rank
  });
}
