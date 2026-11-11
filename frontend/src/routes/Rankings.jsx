import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { CaretDown, CaretUp, MagnifyingGlass } from '@phosphor-icons/react';
import RiskBadge from '../components/RiskBadge.jsx';
import ProvenanceStrip from '../components/ProvenanceStrip.jsx';
import { EmptyState, ErrorState, TableSkeleton } from '../components/States.jsx';
import { getSegments, ApiError } from '../lib/api.js';
import { toView } from '../lib/geo.js';
import { MIN_CRASHES_EVIDENCED, sortBlackspots } from '../lib/filters.js';
import { num } from '../lib/format.js';
import './Rankings.css';

/*
  The national ranking, read from the live segment API.

  /api/segments without a bbox returns segments ordered by blackspot score,
  highest first, filtered to the same evidence floor as the explorer
  (n_crashes >= 6). The backend caps one response at 2,000 rows
  (blackspot.max-segments), which is the top third of the 6,213 evidenced
  segments - every Critical and Severe stretch, and the upper Elevated band.
  Search and sort run over those rows in the browser.
*/
const FETCH_LIMIT = 2000;
const EVIDENCED_TOTAL = 6213;
const PAGE = 100;

/* A1, A3220, B6243, M25, A1(M): the shape of a GB road number. */
const ROAD_NUMBER = /^[abm]\d+(\(m\))?$/;

const COLUMNS = [
  { key: 'rank', label: 'Rank', align: 'right', first: 'asc' },
  { key: 'name', label: 'Segment', align: 'left', first: 'asc' },
  { key: 'score', label: 'Danger score', align: 'left', first: 'desc' },
  { key: 'blackspotScore', label: 'Expected KSI', align: 'right', first: 'desc' },
  { key: 'incidents', label: 'Crashes', align: 'right', first: 'desc' },
  { key: 'ksi', label: 'KSI', align: 'right', first: 'desc' },
  { key: 'fatal', label: 'Fatal', align: 'right', first: 'desc' },
  { key: 'roadClass', label: 'Road', align: 'left', first: 'asc' },
  { key: 'speedLimit', label: 'Speed limit', align: 'right', first: 'desc' },
];

function messageFor(err) {
  if (err instanceof ApiError && err.status === 0) {
    return 'Cannot reach the API. Is the backend running?';
  }
  if (err instanceof ApiError) return err.message;
  return 'Something went wrong loading the ranking.';
}

export default function Rankings() {
  const reduce = useReducedMotion();
  const [sort, setSort] = useState({ key: 'rank', direction: 'asc' });
  const [query, setQuery] = useState('');
  const [shown, setShown] = useState(PAGE);

  const [segments, setSegments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getSegments({ minCrashes: MIN_CRASHES_EVIDENCED, limit: FETCH_LIMIT, signal: controller.signal })
      .then((found) => {
        setSegments(found.map(toView));
        setLoading(false);
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return;
        setError(messageFor(err));
        setLoading(false);
      });
    return () => controller.abort();
  }, [attempt]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    let filtered = segments;
    if (ROAD_NUMBER.test(q)) {
      /*
        A road number matches the road exactly. A substring match would let
        "M25" hit "km 25.0" inside every location, and "A3" hit A30 and A38.
      */
      filtered = segments.filter((s) => s.roadClass.toLowerCase() === q);
    } else if (q) {
      filtered = segments.filter(
        (s) => s.name.toLowerCase().includes(q) || s.id.toLowerCase().includes(q),
      );
    }
    return sortBlackspots(filtered, sort.key, sort.direction);
  }, [segments, sort, query]);

  // A new search or sort starts from the top of the list again.
  useEffect(() => setShown(PAGE), [query, sort]);

  const toggleSort = (col) => {
    setSort((s) =>
      s.key === col.key
        ? { key: col.key, direction: s.direction === 'desc' ? 'asc' : 'desc' }
        : { key: col.key, direction: col.first },
    );
  };

  const visible = rows.slice(0, shown);

  return (
    <div className="rankings">
      <div className="container rankings__head">
        <div className="rankings__head-main">
          <h1 className="screen-title">Ranked road segments</h1>
          <p className="body-secondary rankings__lede">
            The highest-scoring 500 m stretches of road in Great Britain, ordered by
            expected killed-or-seriously-injured casualties over two years. Shows the
            top {num(FETCH_LIMIT)} of the {num(EVIDENCED_TOTAL)} segments with at least{' '}
            {MIN_CRASHES_EVIDENCED} recorded crashes.
          </p>
        </div>

        <div className="field rankings__search">
          <label className="label" htmlFor="rankings-search">
            Search road or segment
          </label>
          <div className="rankings__search-wrap">
            <MagnifyingGlass size={16} weight="bold" aria-hidden="true" />
            <input
              id="rankings-search"
              className="input rankings__input"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="A23, M25, A3220_run0"
            />
          </div>
          <p className="field-helper">
            Matches road numbers, segment locations and segment identifiers.
          </p>
        </div>
      </div>

      <div className="container">
        {/*
          Crash counts come from 2019 to 2021; the score is the model's
          forecast of KSI casualties in 2022 to 2023, validated on segments
          it never trained on. The strip names both halves.
        */}
        <ProvenanceStrip
          items={[
            'STATS19, Great Britain',
            'crashes 2019 to 2021',
            'KSI forecast 2022 to 2023',
            '45,014 scored 500 m segments',
            `${num(EVIDENCED_TOTAL)} with ${MIN_CRASHES_EVIDENCED}+ crashes`,
          ]}
        />
      </div>

      <div className="container rankings__table-wrap">
        {loading && <TableSkeleton rows={10} />}

        {!loading && error && (
          <ErrorState message={error} onRetry={() => setAttempt((n) => n + 1)} />
        )}

        {!loading && !error && rows.length === 0 && (
          <EmptyState
            title="No segment matches that search"
            detail={`Nothing in the top ${num(segments.length)} segments matches "${query.trim()}". Try a road number such as A23 or M25.`}
            action={
              <button className="btn btn-secondary" onClick={() => setQuery('')}>
                Clear search
              </button>
            }
          />
        )}

        {!loading && !error && rows.length > 0 && (
          <>
            <div className="rankings__scroll">
              <table className="rank-table">
                <caption className="sr-only">
                  Road segments in Great Britain ranked by blackspot score
                </caption>
                <thead>
                  <tr>
                    {COLUMNS.map((col) => {
                      const active = sort.key === col.key;
                      return (
                        <th
                          key={col.key}
                          scope="col"
                          className={`rank-table__th rank-table__th--${col.align}${
                            active ? ' rank-table__th--active' : ''
                          }${col.key === 'rank' ? ' rank-table__sticky' : ''}`}
                          aria-sort={
                            active
                              ? sort.direction === 'asc'
                                ? 'ascending'
                                : 'descending'
                              : 'none'
                          }
                        >
                          <button className="rank-table__sort" onClick={() => toggleSort(col)}>
                            <span>{col.label}</span>
                            {active ? (
                              sort.direction === 'desc' ? (
                                <CaretDown size={11} weight="bold" />
                              ) : (
                                <CaretUp size={11} weight="bold" />
                              )
                            ) : (
                              <CaretDown size={11} weight="bold" opacity={0.4} />
                            )}
                          </button>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {visible.map((s, i) => (
                    <motion.tr
                      key={s.id}
                      className="rank-table__row"
                      initial={reduce ? false : { opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{
                        type: 'spring',
                        stiffness: 100,
                        damping: 20,
                        delay: reduce ? 0 : Math.min(i, 16) * 0.03,
                      }}
                    >
                      {/* National rank among all 45,014 segments, not row position. */}
                      <td className="rank-table__td rank-table__td--right rank-table__sticky mono">
                        {num(s.rank)}
                      </td>
                      <td className="rank-table__td rank-table__name">
                        <Link
                          className="rank-table__stretch"
                          to={`/explorer?segment=${encodeURIComponent(s.id)}`}
                        >
                          {s.name}
                        </Link>
                        <span className="rank-table__id mono">{s.id}</span>
                      </td>
                      <td className="rank-table__td">
                        <RiskBadge score={s.score} />
                      </td>
                      <td className="rank-table__td rank-table__td--right mono">
                        {s.blackspotScore.toFixed(2)}
                      </td>
                      <td className="rank-table__td rank-table__td--right mono">
                        {num(s.incidents)}
                      </td>
                      <td className="rank-table__td rank-table__td--right mono">{num(s.ksi)}</td>
                      <td className="rank-table__td rank-table__td--right mono">
                        {num(s.fatal)}
                      </td>
                      <td className="rank-table__td mono rank-table__class">{s.roadClass}</td>
                      <td className="rank-table__td rank-table__td--right mono rank-table__class">
                        {s.speedLimit ? `${s.speedLimit} mph` : '--'}
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="rankings__more">
              <p className="field-helper mono">
                Showing {num(visible.length)} of {num(rows.length)}
              </p>
              {visible.length < rows.length && (
                <button className="btn btn-secondary" onClick={() => setShown((n) => n + PAGE)}>
                  Show {num(Math.min(PAGE, rows.length - visible.length))} more
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
