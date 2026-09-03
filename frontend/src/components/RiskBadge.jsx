import { tierOf } from '../lib/risk.js';
import { score as fmtScore } from '../lib/format.js';
import './RiskBadge.css';

/**
 * Ramp colour chip + tier word + mono score.
 * The tier word is not optional: colour alone never encodes tier.
 */
export default function RiskBadge({ score, size = 'md' }) {
  const tier = tierOf(score);
  return (
    <span className={`risk-badge risk-badge--${size}`}>
      <span
        className="risk-badge__chip"
        style={{ background: tier.color }}
        aria-hidden="true"
      />
      <span className="risk-badge__word">{tier.word}</span>
      <span className="risk-badge__score mono">{fmtScore(score)}</span>
    </span>
  );
}
