/*
  blackspot_score -> the published 0-100 tier scale in risk.js.

  The score is expected killed-or-seriously-injured casualties on a 500m
  stretch over two years, and runs 0 to 9.67. The UI's tiers are 0-100.

  CUTOFFS ARE CALIBRATED TO THE POPULATION USERS ACTUALLY SEE, not to all
  45,014 segments. The UI filters to n_crashes >= 6, because 86% of segments
  rest on fewer than six crashes and their scores are noise. That filter
  removes overwhelmingly low-scoring rows, so what is displayed is far riskier
  than the whole:

                     all 45,014     shown (n_crashes>=6, 6,213)
      median               0.25                       0.94
      p90                  0.81                       2.24

  The earlier cutoffs (0.45/0.85/1.45), derived from the full population, put
  23.3% of DISPLAYED segments in "Critical" and 60% in Severe-or-worse: a red
  screen that distinguishes nothing. These cutoffs are the 50th, 80th and 95th
  percentiles of the displayed population, giving roughly 50/30/15/5%.

  THE LEGEND MUST SAY SO. A segment labelled "Watch" at 0.90 is still above
  the national median of 0.25. The tiers rank segments that have enough
  evidence to be ranked; they are not absolute national bands. Saying that
  plainly is the condition on which this calibration is honest.

  This is the only place these constants live.
*/

const BANDS = [
  { from: 0, to: 0.94, out: [0, 24] },      // Watch
  { from: 0.94, to: 1.57, out: [25, 49] },  // Elevated
  { from: 1.57, to: 3.09, out: [50, 74] },  // Severe
  { from: 3.09, to: 9.67, out: [75, 100] }, // Critical
];

/** Returns 0-100, or null when there is no score, so tierOf gives No data. */
export function scoreToDisplay(blackspotScore) {
  if (blackspotScore === null || blackspotScore === undefined
      || Number.isNaN(blackspotScore)) {
    return null;
  }
  if (blackspotScore <= 0) return 0;

  for (const b of BANDS) {
    if (blackspotScore < b.to) {
      const t = (blackspotScore - b.from) / (b.to - b.from);
      const [lo, hi] = b.out;
      return Math.round(lo + t * (hi - lo));
    }
  }
  return 100;
}

/*
  The number is casualties on a corridor over two years, across all traffic --
  not the reader's risk on one trip. The unit and window are part of the
  string so a caller cannot render it bare.
*/
export function formatExpectedKsi(value) {
  if (!value) return 'no recorded blackspots';
  return `${value.toFixed(1)} KSI over 2 years`;
}
