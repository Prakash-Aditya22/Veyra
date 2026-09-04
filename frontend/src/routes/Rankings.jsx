import { useMemo, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { CaretDown, CaretUp, MagnifyingGlass } from '@phosphor-icons/react';
import RiskBadge from '../components/RiskBadge.jsx';
import ProvenanceStrip from '../components/ProvenanceStrip.jsx';
import { EmptyState } from '../components/States.jsx';
import { BLACKSPOTS, DATASET } from '../data/blackspots.js';
import { sortBlackspots } from '../lib/filters.js';
import { num, shortDate } from '../lib/format.js';
import './Rankings.css';

const COLUMNS = [
  { key: 'rank', label: 'Rank', sortable: false, align: 'right' },
  { key: 'name', label: 'Stretch', sortable: true, align: 'left' },
  { key: 'score', label: 'Danger score', sortable: true, align: 'left' },
  { key: 'incidents', label: 'Incidents', sortable: true, align: 'right' },
  { key: 'fatal', label: 'Fatal', sortable: true, align: 'right' },
  { key: 'roadClass', label: 'Road class', sortable: true, align: 'left' },
  { key: 'lastIncident', label: 'Last incident', sortable: true, align: 'right' },
];

export default function Rankings() {
  const reduce = useReducedMotion();
  const [sort, setSort] = useState({ key: 'score', direction: 'desc' });
  const [query, setQuery] = useState('');

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? BLACKSPOTS.filter(
          (b) =>
            b.name.toLowerCase().includes(q) ||
            b.roadClass.toLowerCase().includes(q) ||
            b.id.toLowerCase().includes(q) ||
            b.landmarks.some((l) => l.toLowerCase().includes(q)),
        )
      : BLACKSPOTS;
    return sortBlackspots(filtered, sort.key, sort.direction);
  }, [sort, query]);

  const toggleSort = (key) => {
    setSort((s) =>
      s.key === key
        ? { key, direction: s.direction === 'desc' ? 'asc' : 'desc' }
        : { key, direction: key === 'name' || key === 'roadClass' ? 'asc' : 'desc' },
    );
  };

  return (
    <div className="rankings">
      <div className="container rankings__head">
        <div className="rankings__head-main">
          <h1 className="screen-title">Ranked road stretches</h1>
          <p className="body-secondary rankings__lede">
            Every detected cluster on the corridor, ordered by composite danger score.
          </p>
        </div>

        <div className="field rankings__search">
          <label className="label" htmlFor="rankings-search">
            Search stretch, road class or landmark
          </label>
          <div className="rankings__search-wrap">
            <MagnifyingGlass size={16} weight="bold" aria-hidden="true" />
            <input
              id="rankings-search"
              className="input rankings__input"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="NH-16, Rasulgarh, BBS-C0417"
            />
          </div>
          <p className="field-helper">
            Matches stretch names, road classes, cluster identifiers and landmarks.
          </p>
        </div>
      </div>

      <div className="container">
        <ProvenanceStrip />
      </div>

      <div className="container rankings__table-wrap">
        {rows.length === 0 ? (
          <EmptyState
            title="No stretch matches that search"
            detail={`Nothing in the ${DATASET.clusters} detected clusters matches "${query.trim()}". Try a road class such as NH-16, or a landmark such as Rasulgarh.`}
            action={
              <button className="btn btn-secondary" onClick={() => setQuery('')}>
                Clear search
              </button>
            }
          />
        ) : (
          <div className="rankings__scroll">
            <table className="rank-table">
              <caption className="sr-only">
                Road stretches ranked by composite danger score
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
                        {col.sortable ? (
                          <button
                            className="rank-table__sort"
                            onClick={() => toggleSort(col.key)}
                          >
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
                        ) : (
                          col.label
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((b, i) => (
                  <motion.tr
                    key={b.id}
                    className="rank-table__row"
                    /*
                      Rows do not navigate in Phase 1. This screen still reads
                      the Bhubaneswar fixture, whose ids (BBS-C0417) cannot
                      resolve against /api/segments/{id}, so a deep link here
                      would open the explorer on nothing. The link returns in
                      Phase 2, when Rankings moves onto the segment API and its
                      ids become real segment ids.
                    */
                    initial={reduce ? false : { opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      type: 'spring',
                      stiffness: 100,
                      damping: 20,
                      delay: reduce ? 0 : Math.min(i, 16) * 0.03,
                    }}
                  >
                    <td className="rank-table__td rank-table__td--right rank-table__sticky mono">
                      {String(i + 1).padStart(2, '0')}
                    </td>
                    <td className="rank-table__td rank-table__name">
                      <span className="rank-table__stretch">{b.name}</span>
                      <span className="rank-table__id mono">{b.id}</span>
                    </td>
                    <td className="rank-table__td">
                      <RiskBadge score={b.score} />
                    </td>
                    <td className="rank-table__td rank-table__td--right mono">
                      {num(b.incidents)}
                    </td>
                    <td className="rank-table__td rank-table__td--right mono">
                      {num(b.fatal)}
                    </td>
                    <td className="rank-table__td mono rank-table__class">{b.roadClass}</td>
                    <td className="rank-table__td rank-table__td--right mono rank-table__date">
                      {shortDate(b.lastIncident)}
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
