/*
  Rank groups: contiguous, mutually exclusive bands of the national rank of the ML forecast.

    Ranks 1–100 · 101–1,000 · 1,001–<top-1% cutoff> · <cutoff + 1>–<last rank>

  The boundaries come from the data release (manifest `tiers`, with `tier_rules`). The top-1%
  cutoff is 1% of all nationally scored segments, rounded down: floor(1,827,550 / 100) = 18,275.
  Display text is built from the boundaries here, so a label can never disagree with the ranks
  it covers, and no group reads as containing another. Groups band the release `rank`; nothing
  is recomputed. A group states where a segment sits in the national ranking of expected
  serious-or-fatal casualty burden; it is not a hazard index, a probability or a per-vehicle risk.

  Colours are the design system's risk ramp (DESIGN.md section 2), darkest for the highest
  ranks. Colour never appears without the group's text label.
*/

const RAMP = {
  top100: { color: 'var(--risk-4)', hex: '#7A1F1A', radius: 7 },
  top1000: { color: 'var(--risk-3)', hex: '#A33A2B', radius: 5.5 },
  top1pct: { color: 'var(--risk-2)', hex: '#C2711F', radius: 4.5 },
  below1pct: { color: 'var(--risk-1)', hex: '#C9A227', radius: 4.5 },
};

const FALLBACK = { color: 'var(--risk-none)', hex: '#3A3E46', radius: 4 };
const nf = (n) => n.toLocaleString('en-GB');

/** "Ranks 1–100": exact, inclusive boundaries. */
export function tierLabel(t) {
  return `Ranks ${nf(t.min_rank)}–${nf(t.max_rank)}`;
}

/** Compact form for badges and chart axes: "1–100", or "18,276+" for the open-ended last group. */
export function tierShort(t, last = false) {
  return last ? `${nf(t.min_rank)}+` : `${nf(t.min_rank)}–${nf(t.max_rank)}`;
}

/**
 * Problems with a set of rank groups; empty when they partition ranks 1..nNational exactly
 * (start at 1, end at the last rank, no gap, no overlap) and the top-1% cutoff is floor(N/100).
 */
export function tierProblems(tiers, nNational) {
  const p = [];
  if (!Array.isArray(tiers) || tiers.length === 0) return ['no rank groups in the release'];
  if (tiers[0].min_rank !== 1) p.push('rank groups do not start at rank 1');
  if (tiers[tiers.length - 1].max_rank !== nNational) p.push(`rank groups do not end at rank ${nf(nNational)}`);
  tiers.forEach((t, i) => {
    if (!(Number.isInteger(t.min_rank) && Number.isInteger(t.max_rank) && t.min_rank <= t.max_rank)) {
      p.push(`rank group ${t.key} has invalid boundaries`);
    }
    if (i > 0 && t.min_rank !== tiers[i - 1].max_rank + 1) p.push(`gap or overlap before rank group ${t.key}`);
  });
  const onePct = tiers.find((t) => t.key === 'top1pct');
  if (onePct && onePct.max_rank !== Math.floor(nNational / 100)) {
    p.push(`top-1% cutoff ${onePct.max_rank} is not floor(${nNational} / 100)`);
  }
  return p;
}

/** Release groups with display text and ramp colour, in rank order. */
export function styledTiers(tiers) {
  return tiers.map((t, i) => ({
    ...t,
    ...(RAMP[t.key] ?? FALLBACK),
    label: tierLabel(t),
    short: tierShort(t, i === tiers.length - 1),
  }));
}

/** One segment's group with display text and colour (`last` is set by normalizeRelease). */
export function tierStyle(tier) {
  if (!tier) return { key: 'unknown', label: 'Rank group not available', short: 'n/a', ...FALLBACK };
  return { ...tier, ...(RAMP[tier.key] ?? FALLBACK), label: tierLabel(tier), short: tierShort(tier, tier.last) };
}
