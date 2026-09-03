import { motion, useReducedMotion } from 'motion/react';
import { CaretUpDown } from '@phosphor-icons/react';
import RiskBadge from './RiskBadge.jsx';
import DetailPanel from './DetailPanel.jsx';
import { EmptyState, TableSkeleton } from './States.jsx';
import { num, shortDate } from '../lib/format.js';
import { DATASET } from '../data/blackspots.js';
import './ResultsPanel.css';

const SORTS = [
  { key: 'score', label: 'Danger score' },
  { key: 'incidents', label: 'Incident count' },
  { key: 'lastIncident', label: 'Most recent' },
  { key: 'name', label: 'Stretch name' },
];

export default function ResultsPanel({
  results,
  selectedId,
  onSelect,
  sortKey,
  onSortChange,
  loading,
  onResetFilters,
}) {
  const reduce = useReducedMotion();
  const selected = results.find((b) => b.id === selectedId);

  if (selected) {
    return (
      <aside className="results" aria-label="Blackspot detail">
        <DetailPanel
          blackspot={selected}
          rank={results.findIndex((b) => b.id === selectedId) + 1}
          onBack={() => onSelect(null)}
        />
      </aside>
    );
  }

  return (
    <aside className="results" aria-label="Ranked results">
      <div className="results__head">
        <div>
          <h2 className="panel-title">Ranked stretches</h2>
          <p className="label results__count">
            <span className="mono">{results.length}</span> in view
          </p>
        </div>

        <label className="results__sort">
          <span className="sr-only">Sort results by</span>
          <select
            className="results__select"
            value={sortKey}
            onChange={(e) => onSortChange(e.target.value)}
          >
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
          <CaretUpDown size={13} weight="bold" aria-hidden="true" />
        </label>
      </div>

      <div className="results__scroll">
        {loading && <TableSkeleton rows={7} />}

        {!loading && results.length === 0 && (
          <EmptyState
            title="No clusters match this filter combination"
            detail={`Widen the time period, or clear the road-class filter. The corridor has ${DATASET.clusters} detected clusters in total.`}
            action={
              <button className="btn btn-secondary" onClick={onResetFilters}>
                Reset filters
              </button>
            }
          />
        )}

        {!loading &&
          results.map((b, i) => (
            <motion.button
              key={b.id}
              className="result-row"
              onClick={() => onSelect(b.id)}
              initial={reduce ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                type: 'spring',
                stiffness: 100,
                damping: 20,
                delay: reduce ? 0 : Math.min(i, 12) * 0.03,
              }}
            >
              <span className="result-row__rank mono">
                {String(i + 1).padStart(2, '0')}
              </span>
              <span className="result-row__main">
                <span className="result-row__name">{b.name}</span>
                <span className="result-row__meta">
                  <span className="mono">{num(b.incidents)}</span> incidents
                  <span className="result-row__dot" aria-hidden="true" />
                  <span className="mono">{shortDate(b.lastIncident)}</span>
                </span>
              </span>
              <RiskBadge score={b.score} size="sm" />
            </motion.button>
          ))}
      </div>
    </aside>
  );
}
