import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { MapContainer, TileLayer, Polyline, CircleMarker, useMap } from 'react-leaflet';
import { motion, useReducedMotion } from 'motion/react';
import { Warning } from '@phosphor-icons/react';
import RouteCompare from '../components/RouteCompare.jsx';
import RiskBadge from '../components/RiskBadge.jsx';
import Legend from '../components/Legend.jsx';
import { EmptyState, ErrorState, TableSkeleton } from '../components/States.jsx';
import { geocode, routeRisk, ApiError } from '../lib/api.js';
import { scoreToDisplay } from '../lib/riskScale.js';
import { tierOf, markerRadius } from '../lib/risk.js';
import { SPRING, staggerDelay, REVEAL_Y } from '../lib/motion.js';
import { num } from '../lib/format.js';
import './Route.css';

/* Great Britain, the extent of the STATS19 record the scores are built from. */
const GB_CENTER = [54.2, -2.6];
const GB_ZOOM = 6;

const DEBOUNCE_MS = 300;
const MIN_QUERY = 3;

/*
  The UI's own floor is six crashes: 86% of segments rest on fewer than that
  and their scores are noise. Unchecking the box drops the floor to one and
  the extra segments arrive flagged `thinlyEvidenced`, so they can be drawn
  and listed as the weaker evidence they are.
*/
const MIN_CRASHES_EVIDENCED = 6;
const MIN_CRASHES_ALL = 1;

/**
 * The brief's four cases. An aborted request never reaches here - it throws a
 * native AbortError rather than an ApiError, and callers drop it silently.
 */
function messageFor(err) {
  if (!(err instanceof ApiError)) {
    return 'Something went wrong looking up that route.';
  }
  switch (err.status) {
    case 503:
      return 'Routing is temporarily unavailable. Try again shortly.';
    case 422:
      return 'No drivable route between those points.';
    case 0:
      return 'Cannot reach the API. Is the backend running?';
    default:
      return err.message;
  }
}

/**
 * The API speaks GeoJSON order - {lon, lat} - and Leaflet speaks [lat, lng].
 * Every coordinate crossing that boundary passes through here, so the flip
 * exists in exactly one place rather than at each call site.
 */
function toLatLngs(geometry) {
  return geometry.map((c) => [c.lat, c.lon]);
}

/** Frames the chosen route. Reduced motion gets the jump, not the flight. */
function FitRoute({ positions, animate }) {
  const map = useMap();
  useEffect(() => {
    if (!positions.length) return;
    map.fitBounds(positions, { padding: [36, 36], animate, duration: 0.6 });
  }, [positions, animate, map]);
  return null;
}

/**
 * One endpoint of the journey.
 *
 * Each keystroke aborts the request the previous one started. Without that, a
 * slow reply to keystroke N can land after keystroke N+1 and overwrite the
 * newer candidate list - intermittent, and miserable to reproduce.
 *
 * The candidate list renders in normal flow rather than floating over the rail:
 * nothing in this product stacks on top of other content.
 */
function EndpointField({ id, label, placeholder, value, onChange }) {
  const [text, setText] = useState('');
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [note, setNote] = useState(null);

  const chosenLabel = value?.label ?? null;

  useEffect(() => {
    const q = text.trim();

    // Selecting a candidate writes its label into the field; re-querying it
    // would spend a request to be told what the user just picked.
    if (chosenLabel && q === chosenLabel) return undefined;

    if (q.length < MIN_QUERY) {
      setItems([]);
      setOpen(false);
      setNote(null);
      return undefined;
    }

    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const found = await geocode(q, { signal: controller.signal });
        setItems(found);
        setActive(-1);
        setOpen(true);
        // An empty array is a valid "no match", not a failure.
        setNote(
          found.length
            ? null
            : { kind: 'helper', text: 'No place matched that name. Try a fuller one.' },
        );
      } catch (err) {
        if (err.name === 'AbortError') return; // our own doing
        setItems([]);
        setOpen(false);
        setNote({ kind: 'error', text: messageFor(err) });
      }
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [text, chosenLabel]);

  const choose = (candidate) => {
    setText(candidate.label);
    setItems([]);
    setOpen(false);
    setActive(-1);
    setNote(null);
    onChange(candidate);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (!open || items.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => (i + 1) % items.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => (i <= 0 ? items.length - 1 : i - 1));
    } else if (e.key === 'Enter' && active >= 0) {
      e.preventDefault();
      choose(items[active]);
    }
  };

  const listId = `${id}-candidates`;

  return (
    <div className="field route-field">
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="input"
        type="text"
        value={text}
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-expanded={open && items.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        onChange={(e) => {
          setText(e.target.value);
          // Editing after a selection retires it, so "Find route" cannot run
          // against an endpoint the field no longer shows.
          if (value) onChange(null);
        }}
        onKeyDown={onKeyDown}
      />

      {open && items.length > 0 && (
        <ul className="route-field__list" id={listId} role="listbox" aria-label={label}>
          {items.map((c, i) => (
            <li key={`${c.label}-${c.lon}-${c.lat}`} role="option" aria-selected={i === active}>
              <button
                type="button"
                className={`route-field__option${i === active ? ' is-active' : ''}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(c)}
              >
                <span className="route-field__name">{c.label}</span>
                <span className="route-field__coord mono">
                  {c.lat.toFixed(3)}, {c.lon.toFixed(3)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {note && (
        <p className={note.kind === 'error' ? 'field-error' : 'field-helper'}>{note.text}</p>
      )}
    </div>
  );
}

export default function RouteScreen() {
  const reduce = useReducedMotion();

  const [from, setFrom] = useState(null);
  const [to, setTo] = useState(null);
  const [includeThin, setIncludeThin] = useState(false);

  const [result, setResult] = useState(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const inFlight = useRef(null);
  useEffect(() => () => inFlight.current?.abort(), []);

  const routes = result?.routes ?? [];
  const selected = routes.find((r) => r.index === selectedIndex) ?? routes[0] ?? null;
  const blackspots = selected?.blackspots ?? [];

  const find = async () => {
    if (!from || !to) return;

    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setLoading(true);
    setError(null);
    try {
      const found = await routeRisk({
        from: [from.lon, from.lat],
        to: [to.lon, to.lat],
        minCrashes: includeThin ? MIN_CRASHES_ALL : MIN_CRASHES_EVIDENCED,
        signal: controller.signal,
      });
      setResult(found);
      setSelectedIndex(found.routes[0]?.index ?? 0);
    } catch (err) {
      if (err.name === 'AbortError') return; // superseded by a newer lookup
      setResult(null);
      setError(messageFor(err));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  /*
    Drawn last means drawn on top, so the selected route is not buried under
    an alternative that happens to share a stretch of road with it.
  */
  const lines = useMemo(() => {
    const drawn = routes.map((r) => ({ index: r.index, positions: toLatLngs(r.geometry) }));
    return drawn.sort((a, b) => (a.index === selectedIndex ? 1 : 0) - (b.index === selectedIndex ? 1 : 0));
  }, [routes, selectedIndex]);

  const selectedPositions = useMemo(
    () => (selected ? toLatLngs(selected.geometry) : []),
    [selected],
  );

  const maxCrashes = useMemo(
    () => Math.max(1, ...blackspots.map((b) => b.nCrashes)),
    [blackspots],
  );

  return (
    <div className="route">
      <div className="route__bar">
        <div className="route__bar-main">
          <h1 className="screen-title">Route risk check</h1>
          <p className="route__provenance">
            <span className="mono">STATS19 2019 to 2023</span>
            <span className="route__sep" aria-hidden="true" />
            <span className="mono">45,014 scored 500 m segments</span>
            <span className="route__sep" aria-hidden="true" />
            <span className="mono">routing by OpenRouteService</span>
          </p>
        </div>
      </div>

      {/* Below 768px the legend leaves the canvas and sits under the header. */}
      <Legend variant="strip" />

      {result?.coverageWarning && (
        <div className="route__banner" role="status">
          <Warning size={16} weight="bold" aria-hidden="true" />
          <p>{result.coverageWarning}</p>
        </div>
      )}

      <div className="route__grid">
        <div className="route__rail">
          <div className="route-form">
            <EndpointField
              id="route-from"
              label="Start"
              placeholder="Croydon"
              value={from}
              onChange={setFrom}
            />
            <EndpointField
              id="route-to"
              label="Destination"
              placeholder="Camden"
              value={to}
              onChange={setTo}
            />

            <label className={`route-check${includeThin ? ' route-check--on' : ''}`}>
              <input
                type="checkbox"
                className="route-check__input"
                checked={includeThin}
                onChange={(e) => setIncludeThin(e.target.checked)}
              />
              <span className="route-check__text">
                Include thinly-evidenced segments (fewer than 6 recorded crashes)
              </span>
            </label>

            <button
              className="btn btn-primary route-form__submit"
              onClick={find}
              disabled={!from || !to || loading}
            >
              {loading ? 'Finding route' : 'Find route'}
            </button>
          </div>

          {routes.length > 0 && (
            <div className="route-form__compare">
              <p className="label route-form__compare-title">
                {routes.length === 1 ? 'One route found' : `${routes.length} routes found`}
              </p>
              <RouteCompare
                routes={routes}
                selectedIndex={selected?.index ?? selectedIndex}
                onSelect={setSelectedIndex}
              />
              <p className="route-form__note">
                Risk figures are recorded killed-or-seriously-injured casualties
                accumulated on each corridor over two years, across all traffic.
                They are not the risk of a single journey.
              </p>
            </div>
          )}
        </div>

        <main className="route__canvas">
          <MapContainer
            center={GB_CENTER}
            zoom={GB_ZOOM}
            className="route__map"
            zoomControl={false}
            attributionControl
          >
            <TileLayer
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
              subdomains="abcd"
              maxZoom={19}
            />

            {lines.map((l) => {
              const isSelected = l.index === (selected?.index ?? selectedIndex);
              return (
                <Polyline
                  /*
                    Leaflet applies `className` when the path is created and
                    ignores it on later setStyle calls, so the key carries the
                    selected state and forces a recreate. Colour lives in
                    Route.css, where it can be a token: an SVG presentation
                    attribute cannot resolve var().
                  */
                  key={`${l.index}-${isSelected ? 'on' : 'off'}`}
                  positions={l.positions}
                  pathOptions={{
                    className: `route-line${isSelected ? ' route-line--selected' : ''}`,
                    weight: isSelected ? 6 : 3,
                    opacity: isSelected ? 1 : 0.5,
                  }}
                  eventHandlers={{ click: () => setSelectedIndex(l.index) }}
                />
              );
            })}

            {blackspots.map((b) => {
              const display = scoreToDisplay(b.blackspotScore);
              const tier = tierOf(display);
              return (
                <CircleMarker
                  key={`${b.segmentId}-${tier.key}`}
                  center={[b.lat, b.lon]}
                  radius={markerRadius(b.nCrashes, maxCrashes)}
                  /*
                    The list beside the map is the affordance for a blackspot,
                    so the markers stay out of the way: an inert marker keeps
                    the route underneath clickable and offers no dead pointer.
                  */
                  interactive={false}
                  pathOptions={{
                    className: `route-spot route-spot--${tier.key}`,
                    weight: 1.5,
                    fillOpacity: b.thinlyEvidenced ? 0.45 : 0.85,
                    opacity: b.thinlyEvidenced ? 0.45 : 1,
                  }}
                />
              );
            })}

            <FitRoute positions={selectedPositions} animate={!reduce} />
          </MapContainer>

          <Legend />
        </main>

        <div className="route__results">
          {/*
            Switching route cross-fades rather than blanking, because the data
            for every candidate arrived in the same response and is already in
            memory. AnimatePresence is deliberately not used: `mode="wait"`
            would gate the incoming list on an outgoing exit animation.
          */}
          <motion.aside
            key={selected?.index ?? 'none'}
            className="route-spots"
            aria-label="Blackspots along the selected route"
            initial={reduce ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.18 }}
          >
            <div className="route-spots__head">
              <h2 className="panel-title">Blackspots on this route</h2>
              {selected && (
                <p className="label route-spots__count">
                  <span className="mono">{num(blackspots.length)}</span> in order of distance
                </p>
              )}
            </div>

            <div className="route-spots__scroll">
              {loading && <TableSkeleton rows={6} />}

              {!loading && error && <ErrorState message={error} onRetry={find} />}

              {!loading && !error && !selected && (
                <EmptyState
                  title="Set a start and a destination"
                  detail="Each candidate route is matched against the scored 500 m segments within 50 m of its path, then listed in the order you would meet them."
                />
              )}

              {!loading && !error && selected && blackspots.length === 0 && (
                <EmptyState
                  title="No recorded blackspots on this route."
                  detail={
                    includeThin
                      ? 'No segment along this corridor carries a recorded crash history in the STATS19 data.'
                      : 'No segment along this corridor met the six-crash evidence floor. Including thinly-evidenced segments will widen the search.'
                  }
                />
              )}

              {!loading &&
                !error &&
                blackspots.map((b, i) => {
                  const display = scoreToDisplay(b.blackspotScore);
                  return (
                    <motion.div
                      key={b.segmentId}
                      initial={reduce ? false : { opacity: 0, y: REVEAL_Y }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ ...SPRING, delay: reduce ? 0 : staggerDelay(i) }}
                    >
                      <Link
                        className="route-spot-row"
                        to={`/explorer?segment=${encodeURIComponent(b.segmentId)}`}
                      >
                        <span className="route-spot-row__at mono">
                          {(b.metresAlongRoute / 1000).toFixed(1)} km
                        </span>
                        <span className="route-spot-row__main">
                          <span className="route-spot-row__name">{b.location}</span>
                          <span className="route-spot-row__meta">
                            <span className="mono">{num(b.nCrashes)}</span> crashes
                            <span className="route-spot-row__dot" aria-hidden="true" />
                            <span className="mono">{num(b.nKsi)}</span> KSI
                            {b.thinlyEvidenced && (
                              <>
                                <span className="route-spot-row__dot" aria-hidden="true" />
                                <span className="route-spot-row__thin">thinly evidenced</span>
                              </>
                            )}
                          </span>
                        </span>
                        <RiskBadge score={display} size="sm" />
                      </Link>
                    </motion.div>
                  );
                })}
            </div>
          </motion.aside>
        </div>
      </div>
    </div>
  );
}
