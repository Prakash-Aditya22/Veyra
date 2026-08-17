import { tierOf } from './risk.js';

/*
  Aggregations derived from whatever set of clusters is currently in view, so
  the statistics screen responds to the same filters as the explorer. Nothing
  here reads global state - pass the filtered list in.
*/

export function totals(list) {
  return list.reduce(
    (acc, b) => ({
      incidents: acc.incidents + b.incidents,
      fatal: acc.fatal + b.fatal,
      serious: acc.serious + b.serious,
      slight: acc.slight + b.slight,
    }),
    { incidents: 0, fatal: 0, serious: 0, slight: 0 },
  );
}

/** 24-bin incident-time histogram summed across the clusters in view. */
export function byHour(list) {
  const bins = Array.from({ length: 24 }, (_, hour) => ({ hour, count: 0 }));
  list.forEach((b) => {
    b.hourly.forEach(({ hour, count }) => {
      bins[hour].count += count;
    });
  });
  return bins;
}

/** Incident totals grouped by carriageway classification, descending. */
export function byRoadClass(list) {
  const map = new Map();
  list.forEach((b) => {
    const entry = map.get(b.roadClass) ?? {
      roadClass: b.roadClass,
      incidents: 0,
      fatal: 0,
      clusters: 0,
    };
    entry.incidents += b.incidents;
    entry.fatal += b.fatal;
    entry.clusters += 1;
    map.set(b.roadClass, entry);
  });
  return [...map.values()].sort((a, b) => b.incidents - a.incidents);
}

/** Cluster counts per risk tier, in published tier order. */
export function byTier(list) {
  const order = ['critical', 'severe', 'elevated', 'watch', 'nodata'];
  const map = new Map(order.map((k) => [k, 0]));
  list.forEach((b) => {
    const key = tierOf(b.score).key;
    map.set(key, (map.get(key) ?? 0) + 1);
  });
  return order.map((key) => ({ key, clusters: map.get(key) }));
}

/**
 * Contributing factors ranked across the clusters in view. Each factor's
 * weight is scaled by that cluster's incident count so a 247-incident stretch
 * carries more influence than a 13-incident one.
 */
export function topFactors(list, limit = 8) {
  const map = new Map();
  list.forEach((b) => {
    b.factors.forEach(({ label, weight }) => {
      map.set(label, (map.get(label) ?? 0) + weight * b.incidents);
    });
  });
  const ranked = [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit);
  const max = ranked[0]?.[1] ?? 1;
  return ranked.map(([label, value]) => ({
    label,
    share: Math.round((value / max) * 100),
  }));
}

/** Peak hour across the clusters in view, used in the dashboard KPI strip. */
export function peakHour(list) {
  const bins = byHour(list);
  return bins.reduce((best, b) => (b.count > best.count ? b : best), bins[0]);
}
