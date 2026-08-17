import { TIERS, NO_DATA_TIER } from '../lib/risk.js';
import './Legend.css';

/**
 * Permanently docked, never collapsible on desktop. A risk map without a
 * visible legend is unreadable, so this component has no dismiss affordance.
 * Tier boundaries are the published ones and do not rescale with the filters.
 */
export default function Legend({ variant = 'docked' }) {
  return (
    <div className={`legend legend--${variant}`}>
      <p className="label legend__title">Composite danger score</p>
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
          <span className="legend__range mono">under 12 records</span>
        </li>
      </ul>
    </div>
  );
}
