import { BLACKSPOTS } from '../data/blackspots.js';
import { tierOf } from './risk.js';

/*
  Filter definitions and the single pure function that applies them.

  Periods are anchored to the last date present in the dataset, not to today.
  Anchoring to `new Date()` would silently empty the map as the fixture ages,
  and would misrepresent a precomputed dataset as a live one.
*/

const DATASET_END = BLACKSPOTS.reduce(
  (latest, b) => (b.lastIncident > latest ? b.lastIncident : latest),
  '2019-01-01',
);

function monthsBefore(iso, months) {
  const d = new Date(`${iso}T00:00:00`);
  d.setMonth(d.getMonth() - months);
  return d.toISOString().slice(0, 10);
}

export const PERIODS = [
  { key: 'full', label: 'Full coverage, 2019 to 2024', since: '2019-01-01' },
  { key: '36m', label: 'Final 36 months', since: monthsBefore(DATASET_END, 36) },
  { key: '12m', label: 'Final 12 months', since: monthsBefore(DATASET_END, 12) },
];

export const TIER_FILTERS = [
  { key: 'critical', label: 'Critical, 75 to 100' },
  { key: 'severe', label: 'Severe, 50 to 74' },
  { key: 'elevated', label: 'Elevated, 25 to 49' },
  { key: 'watch', label: 'Watch, 0 to 24' },
  { key: 'nodata', label: 'No data' },
];

export const ROAD_TYPES = [
  'Dual carriageway',
  'Single carriageway',
];

export const ROAD_CLASSES = [
  'NH-16',
  'NH-316',
  'NH-55',
  'SH-13',
  'SH-60',
  'SH-9A',
  'Urban arterial',
  'Urban collector',
  'Rural district road',
  'Coastal highway',
];

/*
  The dataset records lighting and surface state as contributing factors rather
  than as a separate weather column, so the condition filter matches on factor
  text. Each entry names the factors that count as a hit.
*/
export const CONDITIONS = [
  { key: 'wet', label: 'Wet surface', match: ['Wet surface, monsoon months'] },
  {
    key: 'dark',
    label: 'Reduced visibility',
    match: ['Reduced visibility after dusk', 'Unlit stretch adjacent to forest edge'],
  },
  {
    key: 'hgv',
    label: 'Heavy goods traffic',
    match: ['Heavy goods vehicle share', 'Freight yard access conflict'],
  },
  {
    key: 'pedestrian',
    label: 'Pedestrian exposure',
    match: [
      'Pedestrian crossing without signal',
      'Student pedestrian volume at peak hours',
      'Pilgrim and tourist pedestrian volume',
      'Passenger boarding from carriageway',
    ],
  },
];

export const EMPTY_FILTERS = {
  period: 'full',
  tiers: [],
  roadTypes: [],
  roadClasses: [],
  conditions: [],
};

export function isDefaultFilters(f) {
  return (
    f.period === 'full' &&
    !f.tiers.length &&
    !f.roadTypes.length &&
    !f.roadClasses.length &&
    !f.conditions.length
  );
}

export function countActive(f) {
  return (
    (f.period === 'full' ? 0 : 1) +
    f.tiers.length +
    f.roadTypes.length +
    f.roadClasses.length +
    f.conditions.length
  );
}

export function applyFilters(blackspots, f) {
  const period = PERIODS.find((p) => p.key === f.period) ?? PERIODS[0];

  return blackspots.filter((b) => {
    if (b.lastIncident < period.since) return false;
    if (f.tiers.length && !f.tiers.includes(tierOf(b.score).key)) return false;
    if (f.roadTypes.length && !f.roadTypes.includes(b.roadType)) return false;
    if (f.roadClasses.length && !f.roadClasses.includes(b.roadClass)) return false;

    if (f.conditions.length) {
      const factorLabels = b.factors.map((x) => x.label);
      const hit = f.conditions.some((key) => {
        const cond = CONDITIONS.find((c) => c.key === key);
        return cond?.match.some((m) => factorLabels.includes(m));
      });
      if (!hit) return false;
    }

    return true;
  });
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
