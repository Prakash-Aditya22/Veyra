import { useEffect, useRef, useState } from 'react';
import { CaretUpDown, Warning } from '@phosphor-icons/react';
import PriorityBadge from './PriorityBadge.jsx';
import DetailPanel from './DetailPanel.jsx';
import { EmptyState, TableSkeleton } from './States.jsx';
import { SORTS } from '../lib/filters.js';
import { tierStyle } from '../lib/priority.js';
import { int, ksi, period } from '../lib/format.js';
import './ResultsPanel.css';

const PAGE = 150; // rows rendered at once; the rest on request, so long lists stay responsive

/** What a screen reader hears for one row: rank, place, forecast with units, group, warnings. */
export function rowLabel(s) {
  const warn = [];
  if (s.singleEvent.flag) warn.push('single-event warning');
  if (s.history.sufficiency !== 'sufficient') warn.push('low recent history');
  return (
    `Rank ${int(s.rank)}: ${s.location}. ${ksi(s.score)} expected serious or fatal casualties, ${period(s.forecastPeriod)}. ` +
    `${tierStyle(s.tier).label}. ${int(s.history.collisions)} collisions in ${period(s.historyPeriod)}.` +
    (warn.length ? ` Warning: ${warn.join(', ')}.` : '')
  );
}

/**
 * The keyboard alternative to the map: every loaded segment can be reached here (Tab into the
 * list, then Arrow keys, Home, End; Enter opens the segment). Map lines themselves are drawn on
 * a canvas and are not focusable.
 */
export default function ResultsPanel({
  results, selected, onSelect, sortKey, onSortChange, loading, onResetFilters, forecastPeriod, focusDetail, returnFocusId,
}) {
  const [shown, setShown] = useState(PAGE);
  const listRef = useRef(null);

  // Coming back from a segment: put focus back on its row, so keyboard users keep their place.
  useEffect(() => {
    if (selected || !returnFocusId || !listRef.current) return;
    const row = listRef.current.querySelector(`[data-segment-id="${CSS.escape(returnFocusId)}"]`);
    if (row) row.focus();
  }, [selected, returnFocusId]);

  if (selected) {
    return (
      <aside className="results" aria-label="Segment detail">
        <DetailPanel segment={selected} onBack={() => onSelect(null, { back: selected.id })} focusOnOpen={focusDetail} />
      </aside>
    );
  }

  const onKeyDown = (e) => {
    const rows = [...listRef.current.querySelectorAll('button.result-row')];
    const i = rows.indexOf(document.activeElement);
    if (i < 0) return;
    const next = { ArrowDown: Math.min(rows.length - 1, i + 1), ArrowUp: Math.max(0, i - 1), Home: 0, End: rows.length - 1 }[e.key];
    if (next !== undefined) {
      e.preventDefault();
      rows[next].focus();
    }
  };

  return (
    <aside className="results" aria-label="Segments in national rank order">
      <div className="results__head">
        <div>
          <h2 className="panel-title" id="segment-list-title">
            Segments
          </h2>
          <p className="label results__count">
            <span className="mono">{int(results.length)}</span> in view · forecast {period(forecastPeriod)}
          </p>
        </div>
        <label className="results__sort">
          <span className="sr-only">Sort segments by</span>
          <select className="results__select" value={sortKey} onChange={(e) => onSortChange(e.target.value)}>
            {Object.entries(SORTS).map(([key, s]) => (
              <option key={key} value={key}>
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
            title="No segment matches this search and filter combination"
            detail="Clear a filter or shorten the search. Only the segments loaded in this demo are searched, not the whole national model."
            action={
              <button className="btn btn-secondary" onClick={onResetFilters}>
                Reset filters
              </button>
            }
          />
        )}

        {!loading && results.length > 0 && (
          <>
            <p className="sr-only" id="segment-list-help">
              Use Tab to reach the list, the Up and Down arrow keys to move between segments, Home and End to jump, and
              Enter to open a segment. Showing {int(Math.min(shown, results.length))} of {int(results.length)}.
            </p>
            <ul
              className="results__list"
              id="segment-list"
              ref={listRef}
              tabIndex={-1}
              aria-labelledby="segment-list-title"
              aria-describedby="segment-list-help"
              onKeyDown={onKeyDown}
            >
              {results.slice(0, shown).map((s) => (
                <li key={s.id}>
                  <button className="result-row" data-segment-id={s.id} aria-label={rowLabel(s)} onClick={() => onSelect(s.id, { focus: true })}>
                    <span className="result-row__rank mono">{int(s.rank)}</span>
                    <span className="result-row__main">
                      <span className="result-row__name">{s.location}</span>
                      <span className="result-row__meta">
                        <span className="mono">{ksi(s.score)}</span> expected KSI
                        <span className="result-row__dot" aria-hidden="true" />
                        <span className="mono">{int(s.history.collisions)}</span> collisions 2023–25
                        {(s.singleEvent.flag || s.history.sufficiency !== 'sufficient') && (
                          <>
                            <span className="result-row__dot" aria-hidden="true" />
                            <Warning size={12} weight="bold" aria-hidden="true" />
                            <span className="result-row__warn">{s.singleEvent.flag ? 'single event' : 'low history'}</span>
                          </>
                        )}
                      </span>
                    </span>
                    <PriorityBadge segment={s} size="sm" showRank={false} />
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        {!loading && results.length > shown && (
          <div className="results__more">
            <button className="btn btn-secondary" onClick={() => setShown((n) => n + PAGE)}>
              Show {int(Math.min(PAGE, results.length - shown))} more of {int(results.length - shown)}
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
