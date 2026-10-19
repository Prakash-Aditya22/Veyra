import { tierStyle } from '../lib/priority.js';
import { rank as fmtRank } from '../lib/format.js';
import './PriorityBadge.css';

/**
 * Ramp chip + national rank group (exact ranks) + optional rank. The text label is not
 * optional: colour alone never encodes the group. Shows rank and group, never a score: the
 * forecast is an expected casualty count and is printed with its units where it appears.
 * `sm` uses the compact form of the open-ended last group ("Ranks 18,276+").
 */
export default function PriorityBadge({ segment, size = 'md', showRank = true }) {
  const t = tierStyle(segment.tier);
  const text = size === 'sm' ? `Ranks ${t.short}` : t.label;
  return (
    <span className={`priority-badge priority-badge--${size}`}>
      <span className="priority-badge__chip" style={{ background: t.color }} aria-hidden="true" />
      <span className="priority-badge__word">
        <span className="sr-only">National rank group: </span>
        {text}
      </span>
      {showRank && (
        <span className="priority-badge__score mono">
          <span className="sr-only">, national rank </span>
          {fmtRank(segment.rank)}
        </span>
      )}
    </span>
  );
}
