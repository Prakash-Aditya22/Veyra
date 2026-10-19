import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { FunnelSimple, X } from '@phosphor-icons/react';
import MapCanvas from '../components/MapCanvas.jsx';
import FilterRail from '../components/FilterRail.jsx';
import ResultsPanel from '../components/ResultsPanel.jsx';
import Legend from '../components/Legend.jsx';
import ProvenanceStrip from '../components/ProvenanceStrip.jsx';
import { ErrorState, MapSkeleton } from '../components/States.jsx';
import { useData } from '../data/DataContext.jsx';
import { useFilters } from '../data/FiltersContext.jsx';
import { EMPTY_FILTERS, applyFilters, countActive, filterOptions, sortSegments } from '../lib/filters.js';
import { tierStyle } from '../lib/priority.js';
import { int, ksi, period } from '../lib/format.js';
import { usePageTitle } from '../lib/usePageTitle.js';
import './Explorer.css';

export default function Explorer() {
  const reduce = useReducedMotion();
  const data = useData();
  const ready = data.status === 'ready';
  const [searchParams, setSearchParams] = useSearchParams();
  const { filters, setFilters } = useFilters();
  const [sortKey, setSortKey] = useState('rank');
  const [sheetMounted, setSheetMounted] = useState(false);
  const [sheetClosing, setSheetClosing] = useState(false);

  const openSheet = () => {
    setSheetClosing(false);
    setSheetMounted(true);
  };
  const closeSheet = () => {
    setSheetClosing(true);
    setTimeout(() => {
      setSheetMounted(false);
      setSheetClosing(false);
    }, 240);
  };
  useEffect(() => {
    if (!sheetMounted) return undefined;
    const onKey = (e) => e.key === 'Escape' && closeSheet();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sheetMounted]);

  // Deep link: /explorer?segment=<segment_id> opens that segment (stable contract ID).
  const selectedId = searchParams.get('segment');
  // focusDetail: opened from the list, so focus moves to the panel heading.
  // returnFocusId: closed with "Back", so focus returns to that row of the list.
  const [focusDetail, setFocusDetail] = useState(false);
  const [returnFocusId, setReturnFocusId] = useState(null);
  const setSelectedId = (id, opts = {}) => {
    setFocusDetail(Boolean(id && opts.focus));
    setReturnFocusId(opts.back ?? null);
    setSearchParams(id ? { segment: id } : {}, { replace: true });
  };

  const segments = ready ? data.segments : [];
  const options = useMemo(() => (ready ? filterOptions(data.segments, data.release.tiers) : {}), [ready, data.segments, data.release]);
  const results = useMemo(() => sortSegments(applyFilters(segments, filters), sortKey), [segments, filters, sortKey]);
  // The selection survives filtering: a segment opened by search or deep link stays open.
  const selected = ready && selectedId ? data.byId.get(selectedId) ?? null : null;
  const onMap = useMemo(
    () => (selected && !results.some((s) => s.id === selected.id) ? [...results, selected] : results),
    [results, selected],
  );
  usePageTitle(selected ? `${selected.location} · Explorer` : 'Explorer');

  // Polite announcements for screen readers: the selection, and (after typing settles) how many
  // loaded segments match the current search and filters.
  const [announcement, setAnnouncement] = useState('');
  useEffect(() => {
    if (!selected) return;
    setAnnouncement(
      `Selected ${selected.location}. National rank ${int(selected.rank)} of ${int(data.release.nationalSegments)}, ` +
        `${tierStyle(selected.tier).label}. ${ksi(selected.score)} expected serious or fatal casualties, ${period(selected.forecastPeriod)}.`,
    );
  }, [selected, data.release]);
  useEffect(() => {
    if (!ready || selected) return undefined;
    const t = setTimeout(() => setAnnouncement(`${int(results.length)} of ${int(segments.length)} loaded segments match.`), 700);
    return () => clearTimeout(t);
  }, [ready, selected, results.length, segments.length]);

  const rail = (prefix) =>
    ready && (
      <FilterRail
        filters={filters}
        onChange={setFilters}
        options={options}
        tiers={data.release.tiers}
        resultCount={results.length}
        totalCount={segments.length}
        idPrefix={prefix}
      />
    );

  return (
    <div className="explorer">
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {announcement}
      </p>
      <div className="explorer__bar">
        <div className="explorer__bar-main">
          <h1 className="screen-title">Great Britain road segments</h1>
          <ProvenanceStrip className="explorer__provenance" />
        </div>
        <button className="btn btn-secondary explorer__filter-btn" onClick={openSheet}>
          <FunnelSimple size={16} weight="bold" aria-hidden="true" />
          Find and filter
          {countActive(filters) > 0 && (
            <span className="explorer__badge mono">
              {countActive(filters)}
              <span className="sr-only"> active</span>
            </span>
          )}
        </button>
      </div>

      {ready && <Legend variant="strip" />}

      {data.status === 'error' && (
        <div className="explorer__error">
          <ErrorState message={`The road-segment data could not be loaded. ${data.error}`} onRetry={data.retry} />
        </div>
      )}

      {data.status !== 'error' && (
        <div className="explorer__grid">
          <div className="explorer__rail">{rail('rail')}</div>

          <main className="explorer__canvas" aria-label="Map of the loaded road segments">
            {ready && (
              <a
                className="skip-link"
                href="#segment-list"
                onClick={(e) => {
                  e.preventDefault();
                  // the list, or the open segment's heading
                  (document.getElementById('segment-list') ?? document.querySelector('.detail__name'))?.focus();
                }}
              >
                Skip the map: go to the segment list
              </a>
            )}
            {ready ? (
              <MapCanvas segments={onMap} selectedId={selectedId} onSelect={setSelectedId} />
            ) : (
              <MapSkeleton />
            )}
          </main>

          <div className="explorer__results">
            <motion.div
              key={selectedId ?? 'list'}
              className="explorer__results-inner"
              initial={reduce ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.18 }}
            >
              <ResultsPanel
                results={results}
                selected={selected}
                onSelect={setSelectedId}
                sortKey={sortKey}
                onSortChange={setSortKey}
                loading={!ready}
                onResetFilters={() => setFilters(EMPTY_FILTERS)}
                forecastPeriod={ready ? data.release.forecastPeriod : ''}
                focusDetail={focusDetail}
                returnFocusId={returnFocusId}
              />
            </motion.div>
          </div>
        </div>
      )}

      {sheetMounted && (
        <div className={`explorer__scrim${sheetClosing ? ' explorer__scrim--out' : ''}`} onClick={closeSheet} role="presentation">
          <div
            className={`explorer__sheet${sheetClosing ? ' explorer__sheet--out' : ''}`}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Find and filter"
          >
            <div className="explorer__sheet-head">
              <span className="explorer__handle" aria-hidden="true" />
              <button className="explorer__sheet-close" onClick={closeSheet} aria-label="Close filters">
                <X size={18} weight="bold" />
              </button>
            </div>
            {rail('sheet')}
          </div>
        </div>
      )}
    </div>
  );
}
