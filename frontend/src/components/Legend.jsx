import { TIERS, THIN_FILL_OPACITY } from '../lib/risk.js';
import './Legend.css';

/**
 * Permanently docked, never collapsible on desktop. A risk map without a
 * visible legend is unreadable, so this component has no dismiss affordance.
 *
 * The boundaries are fixed and published here; they never rescale with the
 * filters or the viewport. But they ARE relative, and the legend says so:
 * riskScale.js calibrates them to the 50th, 80th and 95th percentiles of the
 * population the UI shows - segments with at least six recorded crashes -
 * whose median score is 0.94 against 0.25 across all 45,014. A stretch
 * labelled "Watch" is therefore at or below the median of the roads on screen
 * while it may still be above the national one - Watch spans 0 to 0.94, so
 * that holds from 0.25 upwards and not below it. Without that sentence the
 * tiers read as absolute national bands and quietly understate every segment
 * on the map.
 */
export default function Legend({ variant = 'docked' }) {
  return (
    <div className={`legend legend--${variant}`}>
      <p className="label legend__title">Blackspot risk tier</p>
      <ul className="legend__list">
        {TIERS.map((t) => (
          <li key={t.key} className="legend__item">
            <span
              className="legend__swatch"
              style={{ background: t.color }}
              aria-hidden="true"
            />
            <span className="legend__word">{t.word}</span>
            <span className="legend__range mono">
              {t.min} to {t.max}
            </span>
          </li>
        ))}
        {/*
          Not a "No data" row. blackspot_score is NOT NULL on every segment, so
          nothing the map draws is ever unscored; the row that needs explaining
          is the dimmed one. A segment with fewer than six recorded crashes
          keeps its tier colour and is drawn at THIN_FILL_OPACITY, so the
          sample is the tier ramp at that same opacity rather than a colour of
          its own - the reader should be able to match it to what they see.
        */}
        <li className="legend__item">
          <span
            className="legend__swatch legend__swatch--thin"
            style={{ opacity: THIN_FILL_OPACITY }}
            aria-hidden="true"
          />
          <span className="legend__word">Thinly evidenced</span>
          <span className="legend__range mono">under 6 crashes</span>
        </li>
      </ul>
      <p className="legend__note">
        Tiers rank segments against the others with at least 6 recorded crashes,
        not against every road in Great Britain. A stretch marked Watch can
        still sit above the national median of 0.25 expected KSI.
      </p>
    </div>
  );
}
