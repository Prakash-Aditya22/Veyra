import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { FunnelSimple, X } from '@phosphor-icons/react';
import MapCanvas from '../components/MapCanvas.jsx';
import FilterRail from '../components/FilterRail.jsx';
import ResultsPanel from '../components/ResultsPanel.jsx';
import Legend from '../components/Legend.jsx';
import { getSegments, getSegment, ApiError } from '../lib/api.js';
// The API's lon -> Leaflet's lng happens in lib/geo.js and only there.
import { toView } from '../lib/geo.js';
import { CROSSFADE } from '../lib/motion.js';
import {
  EMPTY_FILTERS,
  MIN_CRASHES_ALL,
  MIN_CRASHES_EVIDENCED,
  matchesFilters,
  sortBlackspots,
  countActive,
} from '../lib/filters.js';
import './Explorer.css';

/* Great Britain, the extent of the STATS19 record the scores are built from. */
const GB_CENTER = [54.2, -2.6];
const GB_ZOOM = 6;

/*
  Panning is cheap - /api/segments is a PostGIS query and touches no third
  party - but a request per animation frame is still waste, so the viewport
  settles for 400ms before it is asked about.
*/
const DEBOUNCE_MS = 400;
const LIMIT = 500;

const SORT_DIRECTION = {
  score: 'desc',
  incidents: 'desc',
  name: 'asc',
};

/** An aborted request never reaches here; callers drop those silently. */
function messageFor(err) {
  if (err instanceof ApiError && err.status === 0) {
    return 'Cannot reach the API. Is the backend running?';
  }
  if (err instanceof ApiError) return err.message;
  return 'Something went wrong loading segments for this view.';
}

export default function Explorer() {
  const reduce = useReducedMotion();
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [sortKey, setSortKey] = useState('score');

  const [bbox, setBbox] = useState(null);
  const [segments, setSegments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pinned, setPinned] = useState(null);

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

  /*
    Deep link: /explorer?segment=A23_run3_km0.5 opens straight onto that
    stretch. This is the one place the route screen touches this one - a
    blackspot row on a route links here by segment id - so the parameter name
    is the segment id the API knows, not the fixture's cluster id.
  */
  const selectedId = searchParams.get('segment');

  const setSelectedId = (id) => {
    if (id) setSearchParams({ segment: id }, { replace: true });
    else setSearchParams({}, { replace: true });
  };

  const minCrashes = filters.includeThin ? MIN_CRASHES_ALL : MIN_CRASHES_EVIDENCED;

  /*
    The viewport query. Every pan supersedes the one before it: without the
    abort, a slow reply for an old viewport can land after a fast reply for
    the current one and repopulate the map with segments that are no longer
    on screen.
  */
  useEffect(() => {
    if (!bbox) return undefined;

    const controller = new AbortController();
    setLoading(true);

    const timer = setTimeout(async () => {
      try {
        const found = await getSegments({
          bbox,
          minCrashes,
          limit: LIMIT,
          signal: controller.signal,
        });
        setSegments(found.map(toView));
        setError(null);
      } catch (err) {
        if (err.name === 'AbortError') return; // our own doing
        setSegments([]);
        setError(messageFor(err));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [bbox, minCrashes]);

  /*
    The selected segment is fetched by id rather than taken from the viewport
    list. A deep link arrives before any viewport query has run, and it may
    name a stretch outside the current view or below the evidence floor -
    either way the list cannot be relied on to contain it.

    A 404 means the link names a segment this dataset does not have, so the
    selection is dropped rather than left pointing at nothing.
  */
  useEffect(() => {
    if (!selectedId) {
      setPinned(null);
      return undefined;
    }

    const controller = new AbortController();
    let live = true;

    (async () => {
      try {
        const s = await getSegment(selectedId, { signal: controller.signal });
        if (live) setPinned(toView(s));
      } catch (err) {
        if (err.name === 'AbortError' || !live) return;
        setPinned(null);
        setSearchParams({}, { replace: true });
      }
    })();

    return () => {
      live = false;
      controller.abort();
    };
  }, [selectedId, setSearchParams]);

  /*
    The selected segment is exempt from the client-side filters. Arriving from
    a route result only to be dropped because a tier box happens to be ticked
    would sever the one link between the two screens, and would do it
    silently.
  */
  const results = useMemo(() => {
    const byId = new Map(segments.map((s) => [s.id, s]));
    if (pinned) byId.set(pinned.id, pinned);
    const list = [...byId.values()].filter(
      (s) => s.id === selectedId || matchesFilters(s, filters),
    );
    return sortBlackspots(list, sortKey, SORT_DIRECTION[sortKey]);
  }, [segments, pinned, filters, sortKey, selectedId]);

  const filterKey = JSON.stringify(filters);
  const activeCount = countActive(filters);
  const inView = segments.length + (pinned && !segments.some((s) => s.id === pinned.id) ? 1 : 0);

  return (
    <div className="explorer">
      <div className="explorer__bar">
        <div className="explorer__bar-main">
          <h1 className="screen-title">Blackspot explorer</h1>
          {/*
            Provenance, on every screen, naming what the claim is made from.
            The recorded counts come from 2019 to 2021 and the scores are
            validated against 2022 to 2023, so the strip states the span of
            the record rather than of either half.
          */}
          <p className="explorer__provenance">
            <span className="mono">STATS19 2019 to 2023</span>
            <span className="explorer__sep" aria-hidden="true" />
            <span className="mono">45,014 scored 500 m segments</span>
            <span className="explorer__sep" aria-hidden="true" />
            <span className="mono">Great Britain</span>
          </p>
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
            totalCount={inView}
          />
        </div>

        <main className="explorer__canvas">
          {/*
            The map renders immediately rather than behind a skeleton: it is
            what reports the viewport, so nothing can be fetched until it
            exists. Loading is expressed in the results panel instead.
          */}
          <MapCanvas
            blackspots={results}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onBoundsChange={setBbox}
            center={GB_CENTER}
            zoom={GB_ZOOM}
            homeLabel="the whole of Great Britain"
          />
        </main>

        <div className="explorer__results">
          {/*
            Results cross-fade on filter change rather than blanking to a
            loader, because the segments for this viewport are already in
            memory. The key remounts the panel so the new content fades in;
            AnimatePresence is deliberately not used here, because
            `mode="wait"` would gate the incoming panel on an outgoing exit
            animation and stall the update.
          */}
          <motion.div
            key={selectedId ?? filterKey}
            className="explorer__results-inner"
            initial={reduce ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: CROSSFADE }}
          >
            <ResultsPanel
              results={results}
              selectedId={selectedId}
              onSelect={setSelectedId}
              sortKey={sortKey}
              onSortChange={setSortKey}
              loading={loading && !results.length}
              error={error}
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
              totalCount={inView}
            />
          </div>
        </div>
      )}
    </div>
  );
}
