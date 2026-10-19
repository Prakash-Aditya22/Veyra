import { styledTiers } from '../lib/priority.js';
import { useData } from '../data/DataContext.jsx';
import './Legend.css';

/**
 * Permanently docked, never collapsible on desktop. Groups are contiguous, mutually exclusive
 * bands of national rank published by the release; they do not rescale with the filters.
 * Every colour has its text label; colour is never the only cue.
 */
export default function Legend({ variant = 'docked' }) {
  const data = useData();
  if (data.status !== 'ready') return null;
  const tiers = styledTiers(data.release.tiers);
  const rules = data.release.tierRules;
  return (
    <section className={`legend legend--${variant}`} aria-label="Map legend: national rank groups">
      <p className="label legend__title" id={`legend-title-${variant}`}>
        National rank group
      </p>
      <ul className="legend__list" aria-labelledby={`legend-title-${variant}`}>
        {tiers.map((t) => (
          <li key={t.key} className="legend__item">
            <span className="legend__swatch" style={{ background: t.color }} aria-hidden="true" />
            <span className="legend__word">{t.label}</span>
            {t.description && <span className="legend__range">{t.description}</span>}
          </li>
        ))}
        <li className="legend__item legend__item--note">
          <span className="legend__swatch legend__swatch--dashed" aria-hidden="true" />
          <span className="legend__word">Dashed outline</span>
          <span className="legend__range">under 6 collisions, 2023–25</span>
        </li>
      </ul>
      {variant === 'docked' && (
        <p className="legend__note">
          Ranked by expected serious or fatal casualties, 2026–27: a burden, not a per-vehicle risk.
          {rules?.top1pct_cutoff_rank &&
            ` Top-1% cutoff: 1% of ${data.release.nationalSegments.toLocaleString('en-GB')} scored segments, rounded down, is rank ${rules.top1pct_cutoff_rank.toLocaleString('en-GB')}.`}
        </p>
      )}
    </section>
  );
}
