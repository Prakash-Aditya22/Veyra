import { ROAD_CLASS_LABELS, rateView } from '../data/normalize.js';

/*
  Summaries of a list of segments. Every figure names its population:
    national   - all scored GB segments (counts and the forecast total come from the release)
    subset     - the segments loaded in this demo (a top-ranked subset, not a sample)
    selection  - what the current filters leave
  Sums of expected casualties are sums of the ML forecast for 2026-27 over the listed
  segments; they are never presented as observed casualties or as national totals.
*/

export function summarize(list) {
  const n = list.length;
  const expectedKsi = list.reduce((a, s) => a + s.score, 0);
  const byClass = Object.entries(ROAD_CLASS_LABELS)
    .map(([key, label]) => {
      const l = list.filter((s) => s.roadClass === key);
      return { key, label, n: l.length, expectedKsi: l.reduce((a, s) => a + s.score, 0) };
    })
    .filter((r) => r.n);
  const withStability = list.filter((s) => s.ext?.stabilityClass);
  const stability = ['robust top-1000', 'borderline top-1000', 'robust top-5%', 'variable']
    .map((key) => ({ key, n: withStability.filter((s) => s.ext.stabilityClass === key).length }))
    .filter((r) => r.n);
  return {
    n,
    expectedKsi,
    collisions: list.reduce((a, s) => a + s.history.collisions, 0),
    ksiAdjustedHistory: list.reduce((a, s) => a + s.history.ksiCasualtiesAdjusted, 0),
    sufficient: list.filter((s) => s.history.sufficiency === 'sufficient').length,
    rateShown: list.filter((s) => rateView(s).available).length,
    singleEvent: list.filter((s) => s.singleEvent.flag).length,
    explained: list.some((s) => s.ext?.hasExplanation === null) ? null : list.filter((s) => s.ext?.hasExplanation).length,
    byClass,
    stability,
    stabilityDenominator: withStability.length,
  };
}

export function byTier(list, tiers) {
  return tiers.map((t) => {
    const l = list.filter((s) => s.tier?.key === t.key);
    return { ...t, n: l.length, expectedKsi: l.reduce((a, s) => a + s.score, 0) };
  });
}

/** How often each feature is the largest model attribution (associations, not causes). */
export function leadingFactors(list, limit = 8) {
  const counts = new Map();
  let denominator = 0;
  for (const s of list) {
    const f = s.ext?.leadingFactor;
    if (!f) continue;
    denominator += 1;
    counts.set(f, (counts.get(f) ?? 0) + 1);
  }
  const rows = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, limit);
  return { denominator, rows: rows.map(([label, n]) => ({ label, n })) };
}
