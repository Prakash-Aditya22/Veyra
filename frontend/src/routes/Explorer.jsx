import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { FunnelSimple, X } from '@phosphor-icons/react';
import MapCanvas from '../components/MapCanvas.jsx';
import FilterRail from '../components/FilterRail.jsx';
import ResultsPanel from '../components/ResultsPanel.jsx';
import Legend from '../components/Legend.jsx';
import ProvenanceStrip from '../components/ProvenanceStrip.jsx';
import { MapSkeleton } from '../components/States.jsx';
import { BLACKSPOTS } from '../data/blackspots.js';
import { EMPTY_FILTERS, applyFilters, sortBlackspots, countActive } from '../lib/filters.js';
import './Explorer.css';

const SORT_DIRECTION = {
  score: 'desc',
  incidents: 'desc',
  lastIncident: 'desc',
  name: 'asc',
};

export default function Explorer() {
  const reduce = useReducedMotion();
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [sortKey, setSortKey] = useState('score');
  const [booting, setBooting] = useState(true);

  /*
    Sheet visibility.

    The open and close transitions are CSS keyframe animations that run on
    mount and on the closing class, rather than a class toggled one frame
    after mount. A toggle depends on the browser painting the closed state
    before the class lands; when that ordering slips the sheet stays parked
    off screen while remaining in the DOM, which is invisible on a phone but
    still focusable. An animation on mount has no such ordering requirement.
  */
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

  // Escape closes the sheet, as a modal surface should.
  useEffect(() => {
    if (!sheetMounted) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') closeSheet();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sheetMounted]);

  // Deep link: /explorer?cluster=BBS-C0417 opens straight onto that stretch,
  // which is what the rankings table and the landing page link into.
  const selectedId = searchParams.get('cluster');

  const setSelectedId = (id) => {
    if (id) setSearchParams({ cluster: id }, { replace: true });
    else setSearchParams({}, { replace: true });
  };

  // One short boot so the skeleton is real rather than decorative. When this is
  // wired to the Spring Boot API, replace with the fetch's pending state.
  useEffect(() => {
    const t = setTimeout(() => setBooting(false), 550);
    return () => clearTimeout(t);
  }, []);

  const results = useMemo(() => {
    const filtered = applyFilters(BLACKSPOTS, filters);
    return sortBlackspots(filtered, sortKey, SORT_DIRECTION[sortKey]);
  }, [filters, sortKey]);

  // If the active filters exclude the selected cluster, drop the selection
  // rather than leaving a highlighted marker with no row beside it.
  useEffect(() => {
    if (selectedId && !results.some((b) => b.id === selectedId)) {
      setSearchParams({}, { replace: true });
    }
  }, [results, selectedId, setSearchParams]);

  const filterKey = JSON.stringify(filters);
  const activeCount = countActive(filters);

  return (
    <div className="explorer">
      <div className="explorer__bar">
        <div className="explorer__bar-main">
          <h1 className="screen-title">Blackspot explorer</h1>
          <ProvenanceStrip className="explorer__provenance" />
        </div>
        <button
          className="btn btn-secondary explorer__filter-btn"
          onClick={openSheet}
        >
          <FunnelSimple size={16} weight="bold" />
          Filters
          {activeCount > 0 && <span className="explorer__badge mono">{activeCount}</span>}
        </button>
      </div>

      {/* Legend moves off the canvas and under the header below 768px. */}
      <Legend variant="strip" />

      <div className="explorer__grid">
        <div className="explorer__rail">
          <FilterRail
            filters={filters}
            onChange={setFilters}
            resultCount={results.length}
            totalCount={BLACKSPOTS.length}
          />
        </div>

        <main className="explorer__canvas">
          {booting ? (
            <MapSkeleton />
          ) : (
            <MapCanvas
              blackspots={results}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
        </main>

        <div className="explorer__results">
          {/*
            Results cross-fade on filter change rather than blanking to a
            loader, because the data is already in memory. The key remounts the
            panel so the new content fades in; AnimatePresence is deliberately
            not used here, because `mode="wait"` would gate the incoming panel
            on an outgoing exit animation and stall the update.
          */}
          <motion.div
            key={selectedId ?? filterKey}
            className="explorer__results-inner"
            initial={reduce ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.18 }}
          >
            <ResultsPanel
              results={results}
              selectedId={selectedId}
              onSelect={setSelectedId}
              sortKey={sortKey}
              onSortChange={setSortKey}
              loading={booting}
              onResetFilters={() => setFilters(EMPTY_FILTERS)}
            />
          </motion.div>
        </div>
      </div>

      {/*
        Below 1024px the rail becomes a modal sheet.

        The enter and exit transitions are plain CSS rather than
        AnimatePresence: the exit animation has to finish before the element
        unmounts, and gating unmount on an animation callback means a stalled
        callback leaves an undismissable sheet over the whole screen. A CSS
        transition plus a timeout cannot trap the user that way.
      */}
      {sheetMounted && (
        <div
          className={`explorer__scrim${sheetClosing ? ' explorer__scrim--out' : ''}`}
          onClick={closeSheet}
          role="presentation"
        >
          <div
            className={`explorer__sheet${sheetClosing ? ' explorer__sheet--out' : ''}`}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Filters"
          >
            <div className="explorer__sheet-head">
              <span className="explorer__handle" aria-hidden="true" />
              <button
                className="explorer__sheet-close"
                onClick={closeSheet}
                aria-label="Close filters"
              >
                <X size={18} weight="bold" />
              </button>
            </div>
            <FilterRail
              filters={filters}
              onChange={setFilters}
              resultCount={results.length}
              totalCount={BLACKSPOTS.length}
            />
          </div>
        </div>
      )}
    </div>
  );
}
