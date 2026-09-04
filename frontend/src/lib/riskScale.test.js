import { describe, it, expect } from 'vitest';
import { scoreToDisplay, formatExpectedKsi } from './riskScale.js';
import { tierOf } from './risk.js';

describe('scoreToDisplay', () => {
  it('maps the band cutoffs onto the published tiers', () => {
    expect(tierOf(scoreToDisplay(0.5)).key).toBe('watch');
    expect(tierOf(scoreToDisplay(1.2)).key).toBe('elevated');
    expect(tierOf(scoreToDisplay(2.0)).key).toBe('severe');
    expect(tierOf(scoreToDisplay(5.0)).key).toBe('critical');
    expect(tierOf(scoreToDisplay(9.67)).key).toBe('critical');
  });

  it('keeps Critical to roughly the worst 5% of displayed segments', () => {
    // Measured on the 6,213 segments with n_crashes >= 6: median 0.94,
    // p80 1.57, p95 3.09. Just below a cutoff must not reach the next tier.
    expect(tierOf(scoreToDisplay(0.93)).key).toBe('watch');
    expect(tierOf(scoreToDisplay(3.09)).key).toBe('critical');
    expect(tierOf(scoreToDisplay(3.08)).key).toBe('severe');
  });

  it('puts each interior cutoff in the band it opens, not the one it closes', () => {
    // 0.94 and 1.57 are the 50th and 80th percentiles of the displayed
    // population, and they are the calibration the whole tier scheme rests
    // on. A mutation isolated to either comparison - >= for >, or a digit
    // moved - shows up here and nowhere else: the assertions above only
    // bracket these two values, they never land on them.
    expect(tierOf(scoreToDisplay(0.94)).key).toBe('elevated');
    expect(tierOf(scoreToDisplay(1.57)).key).toBe('severe');
    expect(tierOf(scoreToDisplay(1.56)).key).toBe('elevated');
  });

  it('is monotonic', () => {
    const scores = [0, 0.5, 0.94, 1.57, 3.09, 5, 9.67];
    const display = scores.map(scoreToDisplay);
    for (let i = 1; i < display.length; i += 1) {
      expect(display[i]).toBeGreaterThanOrEqual(display[i - 1]);
    }
  });

  it('clamps to 0 and 100 rather than falling through', () => {
    expect(scoreToDisplay(0)).toBe(0);
    expect(scoreToDisplay(-1)).toBe(0);
    expect(scoreToDisplay(1000)).toBe(100);
    expect(tierOf(scoreToDisplay(1000)).key).toBe('critical');
  });

  it('returns null for a missing score so the No-data tier applies', () => {
    expect(scoreToDisplay(null)).toBeNull();
    expect(tierOf(scoreToDisplay(null)).key).toBe('nodata');
  });
});

describe('formatExpectedKsi', () => {
  it('names the unit and the window, never a per-trip risk', () => {
    expect(formatExpectedKsi(4.23)).toBe('4.2 KSI over 2 years');
  });

  it('handles a clean route', () => {
    expect(formatExpectedKsi(0)).toBe('no recorded blackspots');
  });
});
