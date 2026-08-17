/*
  Risk tiering. Boundaries are fixed and published in the legend - they are
  never rescaled per viewport or per filter (DESIGN.md section 2).

  Colour alone never encodes tier. Every consumer of `tierOf` must render the
  tier's `word` alongside its `color`.
*/

export const TIERS = [
  { key: 'watch', word: 'Watch', min: 0, max: 24, color: 'var(--risk-1)', hex: '#C9A227' },
  { key: 'elevated', word: 'Elevated', min: 25, max: 49, color: 'var(--risk-2)', hex: '#C2711F' },
  { key: 'severe', word: 'Severe', min: 50, max: 74, color: 'var(--risk-3)', hex: '#A33A2B' },
  { key: 'critical', word: 'Critical', min: 75, max: 100, color: 'var(--risk-4)', hex: '#7A1F1A' },
];

export const NO_DATA_TIER = {
  key: 'nodata',
  word: 'No data',
  color: 'var(--risk-none)',
  hex: '#3A3E46',
};

/**
 * Absence of data is not absence of risk, so a null score gets its own tier.
 *
 * The published boundaries are stated as whole numbers, but scores carry one
 * decimal. The upper bound is therefore exclusive of the next tier's minimum
 * rather than a literal `<= max`, otherwise a score of 74.8 would fall through
 * the gap between Severe and Critical and be mislabelled as No data.
 */
export function tierOf(score) {
  if (score === null || score === undefined || Number.isNaN(score)) {
    return NO_DATA_TIER;
  }
  return (
    TIERS.find((t) => score >= t.min && score < t.max + 1) ??
    (score >= 100 ? TIERS[TIERS.length - 1] : NO_DATA_TIER)
  );
}

/** Marker radius scales with incident count, clamped to 6px-22px. */
export function markerRadius(incidents, maxIncidents) {
  if (!maxIncidents) return 6;
  const t = Math.sqrt(incidents) / Math.sqrt(maxIncidents);
  return 6 + t * 16;
}

/** A cluster inherits the colour of its highest-severity member, never an average. */
export function worstTier(clusters) {
  const scored = clusters.filter((c) => c.score !== null);
  if (!scored.length) return NO_DATA_TIER;
  return tierOf(Math.max(...scored.map((c) => c.score)));
}
