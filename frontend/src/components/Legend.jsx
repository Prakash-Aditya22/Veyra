import { TIERS, NO_DATA_TIER } from '../lib/risk.js';
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
 * labelled "Watch" is therefore below the median of the roads on screen, not
 * below the national one. Without that sentence the tiers read as absolute
 * national bands and quietly understate every segment on the map.
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
        <li className="legend__item">
          <span
            className="legend__swatch"
            style={{ background: NO_DATA_TIER.color }}
            aria-hidden="true"
          />
          <span className="legend__word">{NO_DATA_TIER.word}</span>
          <span className="legend__range mono">under 6 crashes</span>
        </li>
      </ul>
      <p className="legend__note">
        Tiers rank segments against the others with at least 6 recorded crashes,
        not against every road in Great Britain. A stretch marked Watch is still
        well above the national median.
      </p>
    </div>
  );
}
