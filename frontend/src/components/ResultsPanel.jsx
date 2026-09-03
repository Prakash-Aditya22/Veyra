import { motion, useReducedMotion } from 'motion/react';
import { CaretUpDown } from '@phosphor-icons/react';
import RiskBadge from './RiskBadge.jsx';
import DetailPanel from './DetailPanel.jsx';
import { EmptyState, ErrorState, TableSkeleton } from './States.jsx';
import { num } from '../lib/format.js';
import './ResultsPanel.css';

/*
  "Most recent" is gone with the fixture. A 500 m segment aggregates three
  years of crashes into counts and carries no date, so there is nothing
  honest to sort on.
*/
const SORTS = [
  { key: 'score', label: 'Risk score' },
  { key: 'incidents', label: 'Recorded crashes' },
  { key: 'name', label: 'Stretch name' },
];

export default function ResultsPanel({
  results,
  selectedId,
  onSelect,
  sortKey,
  onSortChange,
  loading,
  error,
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

        {!loading && error && <ErrorState message={error} />}

        {!loading && !error && results.length === 0 && (
          <EmptyState
            title="No scored segments in this view"
            detail="Pan or zoom to a stretch of road with a recorded crash history, clear the road filter, or include thinly-evidenced segments to widen the floor below six crashes."
            action={
              <button className="btn btn-secondary" onClick={onResetFilters}>
                Reset filters
              </button>
            }
          />
        )}

        {!loading &&
          !error &&
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
                  <span className="mono">{num(b.incidents)}</span> crashes
                  <span className="result-row__dot" aria-hidden="true" />
                  <span className="mono">{num(b.ksi)}</span> KSI
                  {b.thinlyEvidenced && (
                    <>
                      <span className="result-row__dot" aria-hidden="true" />
                      <span className="result-row__thin">thinly evidenced</span>
                    </>
                  )}
                </span>
              </span>
              <RiskBadge score={b.score} size="sm" />
            </motion.button>
          ))}
      </div>
    </aside>
  );
}
