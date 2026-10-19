import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CaretDown, CaretUp, MagnifyingGlass } from '@phosphor-icons/react';
import PriorityBadge from '../components/PriorityBadge.jsx';
import ProvenanceStrip from '../components/ProvenanceStrip.jsx';
import { EmptyState, ErrorState, TableSkeleton } from '../components/States.jsx';
import { useData } from '../data/DataContext.jsx';
import { ROAD_CLASS_LABELS } from '../data/normalize.js';
import { matchesQuery, sortSegments } from '../lib/filters.js';
import { int, ksi, period, rank as fmtRank } from '../lib/format.js';
import { usePageTitle } from '../lib/usePageTitle.js';
import './Rankings.css';

const PAGE = 200;

// `sortKey` maps a column to a SORTS entry; the forecast column sorts by rank (same order,
// and rank resolves ties the rounded score cannot).
const COLUMNS = [
  { key: 'rank', label: 'Rank', sortKey: 'rank', align: 'right' },
  { key: 'segment', label: 'Segment', sortKey: 'name', align: 'left' },
  { key: 'tier', label: 'Rank group', align: 'left' },
  { key: 'score', label: 'Expected KSI', sortKey: 'rank', align: 'right' },
  { key: 'range', label: 'Rank range (refits)', align: 'right' },
  { key: 'collisions', label: 'Collisions', sortKey: 'collisions', align: 'right' },
  { key: 'ksi', label: 'KSI casualties', sortKey: 'ksiHistory', align: 'right' },
  { key: 'class', label: 'Road class', align: 'left' },
  { key: 'notes', label: 'Warnings', align: 'left' },
];

function notes(s) {
  const n = [];
  if (s.singleEvent.flag) n.push('single event');
  if (s.history.sufficiency !== 'sufficient') n.push('low history');
  if (s.rank <= 1000 && s.ext?.oneCollisionRank > 1000) n.push('one-collision sensitive');
  return n.join(', ') || '—';
}

export default function Rankings() {
  const navigate = useNavigate();
  const data = useData();
  const ready = data.status === 'ready';
  const [sort, setSort] = useState({ key: 'rank', direction: 'asc' });
  const [query, setQuery] = useState('');
  const [shown, setShown] = useState(PAGE);

  const rows = useMemo(() => {
    if (!ready) return [];
    return sortSegments(data.segments.filter((s) => matchesQuery(s, query)), sort.key, sort.direction);
  }, [ready, data.segments, query, sort]);

  const toggleSort = (key) =>
    setSort((s) =>
      s.key === key
        ? { key, direction: s.direction === 'asc' ? 'desc' : 'asc' }
        : { key, direction: key === 'rank' || key === 'name' ? 'asc' : 'desc' },
    );
  const open = (id) => navigate(`/explorer?segment=${encodeURIComponent(id)}`);
  usePageTitle('Rankings');
  // Arrow keys move between focusable rows; Enter or Space opens the segment on the map.
  const onTableKeyDown = (e) => {
    const rowEls = [...e.currentTarget.querySelectorAll('tr.rank-table__row')];
    const i = rowEls.indexOf(document.activeElement);
    if (i < 0) return;
    const next = { ArrowDown: Math.min(rowEls.length - 1, i + 1), ArrowUp: Math.max(0, i - 1), Home: 0, End: rowEls.length - 1 }[e.key];
    if (next !== undefined) {
      e.preventDefault();
      rowEls[next].focus();
    }
  };
  const r = ready ? data.release : null;

  return (
    <div className="rankings">
      <div className="container rankings__head">
        <div className="rankings__head-main">
          <h1 className="screen-title">Segments in national rank order</h1>
          <p className="body-secondary rankings__lede">
            {ready
              ? `The ${int(r.subset.nTop)} highest-ranked of ${int(r.nationalSegments)} scored road segments in Great Britain, plus ${int(
                  r.subset.nReference,
                )} lower-ranked reference cases. Ranked by expected serious or fatal casualties in ${period(
                  r.forecastPeriod,
                )}. Select a row to open it on the map.`
              : 'Loading the ranked segments.'}
          </p>
        </div>
        <div className="field rankings__search">
          <label className="label" htmlFor="rankings-search">
            Search road, place or segment ID
          </label>
          <div className="rankings__search-wrap">
            <MagnifyingGlass size={16} weight="bold" aria-hidden="true" />
            <input
              id="rankings-search"
              className="input rankings__input"
              type="search"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setShown(PAGE);
              }}
              placeholder="A100, Hanover Street, A57-842C"
              autoComplete="off"
            />
          </div>
          <p className="field-helper">Searches the loaded segments, not the whole national model.</p>
        </div>
      </div>

      <div className="container">
        <ProvenanceStrip />
      </div>

      <div className="container rankings__table-wrap">
        {data.status === 'error' && <ErrorState message={`The ranking could not be loaded. ${data.error}`} onRetry={data.retry} />}
        {data.status === 'loading' && <TableSkeleton rows={10} />}
        {ready && rows.length === 0 && (
          <EmptyState
            title="No loaded segment matches that search"
            detail={`Nothing among the ${int(data.segments.length)} loaded segments matches "${query.trim()}". Try a road number such as A57, or part of a street name.`}
            action={
              <button className="btn btn-secondary" onClick={() => setQuery('')}>
                Clear search
              </button>
            }
          />
        )}
        {ready && rows.length > 0 && (
          <>
            <p className="sr-only" id="rankings-keyboard-help">
              Tab to a row, use the Up and Down arrow keys to move between rows, and press Enter or Space to open the
              segment on the map.
            </p>
            <div className="rankings__scroll">
              <table className="rank-table" aria-describedby="rankings-keyboard-help" onKeyDown={onTableKeyDown}>
                <caption className="sr-only">
                  Road segments ranked by expected serious or fatal casualties, {period(r.forecastPeriod)}
                </caption>
                <thead>
                  <tr>
                    {COLUMNS.map((col) => {
                      const active = col.sortKey && sort.key === col.sortKey;
                      return (
                        <th
                          key={col.key}
                          scope="col"
                          className={`rank-table__th rank-table__th--${col.align}${active ? ' rank-table__th--active' : ''}${
                            col.key === 'rank' ? ' rank-table__sticky' : ''
                          }`}
                          aria-sort={active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
                        >
                          {col.sortKey ? (
                            <button className="rank-table__sort" onClick={() => toggleSort(col.sortKey)}>
                              <span>{col.label}</span>
                              {active ? (
                                sort.direction === 'desc' ? <CaretDown size={11} weight="bold" /> : <CaretUp size={11} weight="bold" />
                              ) : (
                                <CaretDown size={11} weight="bold" opacity={0.4} />
                              )}
                            </button>
                          ) : (
                            col.label
                          )}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, shown).map((s) => (
                    <tr
                      key={s.id}
                      className="rank-table__row"
                      onClick={() => open(s.id)}
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          open(s.id);
                        }
                      }}
                    >
                      <td className="rank-table__td rank-table__td--right rank-table__sticky mono">{int(s.rank)}</td>
                      <td className="rank-table__td rank-table__name">
                        <span className="rank-table__stretch">{s.location}</span>
                        <span className="rank-table__id mono">{s.id}</span>
                      </td>
                      <td className="rank-table__td">
                        <PriorityBadge segment={s} size="sm" showRank={false} />
                      </td>
                      <td className="rank-table__td rank-table__td--right mono">{ksi(s.score)}</td>
                      <td className="rank-table__td rank-table__td--right mono">
                        {s.ext?.rankRange ? `${fmtRank(s.ext.rankRange[0])}–${fmtRank(s.ext.rankRange[1])}` : 'Not available'}
                      </td>
                      <td className="rank-table__td rank-table__td--right mono">{int(s.history.collisions)}</td>
                      <td className="rank-table__td rank-table__td--right mono">{ksi(s.history.ksiCasualtiesAdjusted, 1)}</td>
                      <td className="rank-table__td rank-table__class">{ROAD_CLASS_LABELS[s.roadClass] ?? s.roadClass}</td>
                      <td className="rank-table__td rank-table__notes">{notes(s)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="field-helper rankings__foot">
              Expected KSI: expected killed-or-seriously-injured casualties, {period(r.forecastPeriod)} combined (DfT
              severity-adjusted). Collisions and KSI casualties: recorded in {period(r.historyPeriod)}. Rank range: 5th–95th
              percentile across 20 model refits; neighbouring ranks are not meaningfully different. Showing{' '}
              {int(Math.min(shown, rows.length))} of {int(rows.length)}.
            </p>
            {rows.length > shown && (
              <button className="btn btn-secondary" onClick={() => setShown((n) => n + PAGE)}>
                Show {int(Math.min(PAGE, rows.length - shown))} more
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
