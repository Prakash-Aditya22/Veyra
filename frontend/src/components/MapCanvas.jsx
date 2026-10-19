import { useEffect, useMemo, useState } from 'react';
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import { Plus, Minus, CrosshairSimple } from '@phosphor-icons/react';
import { tierStyle } from '../lib/priority.js';
import { BASEMAP } from '../config/basemap.js';
import { rank as fmtRank } from '../lib/format.js';
import { isOsmBlockTile } from '../lib/tileGuard.js';
import Legend from './Legend.jsx';
import './MapCanvas.css';

const DEEP_GRAPHITE = '#131417';
const BONE_WHITE = '#EEF1F5';

/*
  Great Britain only. The initial view frames mainland GB; panning is limited to the British
  Isles so the map never drifts to areas the model does not cover. Northern Ireland is visible
  on the basemap but has no data: STATS19 (GB) and OS Open Roads (GB) do not include it.
*/
export const GB_VIEW = [
  [49.9, -6.4],
  [58.7, 1.8],
];
const MAX_BOUNDS = [
  [48.5, -11.5],
  [61.5, 4.0],
];
// Below this zoom a ~500 m segment is under a pixel long, so midpoints are drawn instead.
const LINE_ZOOM = 12;

function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function FlyToSelected({ selected }) {
  const map = useMap();
  useEffect(() => {
    if (!selected) return;
    const animate = !prefersReducedMotion();
    if (selected.line) map.flyToBounds(selected.line, { maxZoom: 16, padding: [60, 60], animate, duration: 0.6 });
    else map.flyTo([selected.lat, selected.lon], Math.max(map.getZoom(), 15), { animate, duration: 0.6 });
  }, [selected, map]);
  return null;
}

function ZoomWatcher({ onZoom }) {
  const map = useMapEvents({ zoomend: () => onZoom(map.getZoom()) });
  useEffect(() => onZoom(map.getZoom()), [map, onZoom]);
  return null;
}

function MapControls({ onRecenter }) {
  const map = useMap();
  return (
    <div className="map-controls">
      <div className="map-controls__cluster">
        <button className="map-btn" onClick={() => map.zoomIn()} aria-label="Zoom in">
          <Plus size={16} weight="bold" />
        </button>
        <span className="map-controls__rule" aria-hidden="true" />
        <button className="map-btn" onClick={() => map.zoomOut()} aria-label="Zoom out">
          <Minus size={16} weight="bold" />
        </button>
      </div>
      <div className="map-controls__cluster">
        <button
          className="map-btn"
          onClick={() => {
            onRecenter?.();
            map.fitBounds(GB_VIEW);
          }}
          aria-label="Reset the view to Great Britain"
          title="Reset view"
        >
          <CrosshairSimple size={16} weight="regular" />
        </button>
      </div>
    </div>
  );
}

/**
 * Names the Leaflet container for assistive technology and explains the keyboard alternative.
 * Map features are drawn on a canvas and cannot take focus; the segment list can.
 */
function MapA11y({ interactive, count }) {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    if (interactive) {
      el.setAttribute('role', 'region');
      el.setAttribute('aria-label', `Map of ${count.toLocaleString('en-GB')} loaded road segments`);
      el.setAttribute('aria-describedby', 'map-keyboard-help');
    } else {
      el.setAttribute('aria-hidden', 'true');
      el.removeAttribute('tabindex');
    }
  }, [map, interactive, count]);
  return null;
}

// Credits for the data drawn on the map. Kept apart from the tile layer so they stay visible
// when the basemap is off or has been dropped.
const DATA_ATTRIBUTION = 'Roads: OS Open Roads, Crown copyright | Collisions: DfT STATS19, OGL';

function DataAttribution() {
  const map = useMap();
  useEffect(() => {
    map.attributionControl?.addAttribution(DATA_ATTRIBUTION);
    return () => map.attributionControl?.removeAttribution(DATA_ATTRIBUTION);
  }, [map]);
  return null;
}

function label(s) {
  return `${fmtRank(s.rank)} · ${tierStyle(s.tier).label} · ${s.location}`;
}

export default function MapCanvas({ segments, selectedId, onSelect, interactive = true, showLegend = true, className = '' }) {
  const [zoom, setZoom] = useState(6);
  const selected = useMemo(() => segments.find((s) => s.id === selectedId) ?? null, [segments, selectedId]);
  // Lowest priority drawn first, so the highest-ranked segments sit on top.
  const drawOrder = useMemo(() => [...segments].sort((a, b) => b.rank - a.rank), [segments]);
  const showLines = zoom >= LINE_ZOOM;
  // Tile health. Failing tiles (none loaded) or the provider's "Access blocked" image (an HTTP 200
  // PNG that Leaflet would draw as a tile) drop the basemap: a neutral ground and a notice instead.
  const [tiles, setTiles] = useState({ ok: 0, failed: 0, blocked: 0 });
  const tileEvents = useMemo(
    () => ({
      tileload: (e) => {
        if (BASEMAP.cors && isOsmBlockTile(e.tile)) setTiles((t) => ({ ...t, blocked: t.blocked + 1 }));
        else setTiles((t) => (t.ok ? t : { ...t, ok: 1 }));
      },
      tileerror: () => setTiles((t) => ({ ...t, failed: t.failed + 1 })),
    }),
    [],
  );
  const tilesFailing = tiles.ok === 0 && tiles.failed >= 4;
  const tilesBlocked = tiles.blocked >= 2;
  const basemapOff = BASEMAP.disabled || tilesFailing || tilesBlocked;
  const help = 'Road segments, ranks and the legend are unaffected. See the README section "Map provider configuration".';
  let notice = null;
  if (BASEMAP.disabled) notice = 'Basemap unavailable: no basemap is configured (VITE_BASEMAP_URL=none). Road segments, ranks and the legend are unaffected.';
  else if (tilesBlocked) notice = `Basemap unavailable: ${BASEMAP.label} sent its "Access blocked" image instead of map tiles, so the basemap is hidden. ${help}`;
  else if (tilesFailing) notice = `Basemap unavailable: tiles from ${BASEMAP.label} could not be loaded. ${help}`;
  else if (BASEMAP.missingAttribution) notice = 'The configured basemap has no attribution set (VITE_BASEMAP_ATTRIBUTION). Most tile providers require one.';

  return (
    <div className={`map-canvas${BASEMAP.darken ? ' map-canvas--darken' : ''}${basemapOff ? ' map-canvas--no-basemap' : ''} ${className}`}>
      <MapContainer
        bounds={GB_VIEW}
        maxBounds={MAX_BOUNDS}
        minZoom={5}
        className="map-canvas__map"
        zoomControl={false}
        preferCanvas
        scrollWheelZoom={interactive}
        dragging={interactive}
        doubleClickZoom={interactive}
        touchZoom={interactive}
        keyboard={interactive}
        attributionControl
      >
        {!basemapOff && (
          <TileLayer
            url={BASEMAP.url}
            attribution={BASEMAP.attribution}
            subdomains={BASEMAP.subdomains}
            maxZoom={BASEMAP.maxZoom}
            crossOrigin={BASEMAP.cors ? 'anonymous' : undefined}
            referrerPolicy={BASEMAP.referrerPolicy}
            eventHandlers={tileEvents}
          />
        )}
        <DataAttribution />
        <ZoomWatcher onZoom={setZoom} />
        <MapA11y interactive={interactive} count={segments.length} />

        {drawOrder.map((s) => {
          const t = tierStyle(s.tier);
          const isSel = s.id === selectedId;
          const dashed = s.history.sufficiency !== 'sufficient';
          const handlers = interactive ? { click: () => onSelect?.(s.id) } : undefined;
          if (showLines && s.line) {
            return (
              <Polyline
                key={`${s.id}-line-${isSel ? 'on' : 'off'}`}
                positions={s.line}
                pathOptions={{ color: isSel ? BONE_WHITE : t.hex, weight: isSel ? 7 : 5, opacity: 0.95, dashArray: dashed ? '6 6' : undefined }}
                eventHandlers={handlers}
              >
                {interactive && <Tooltip sticky>{label(s)}</Tooltip>}
              </Polyline>
            );
          }
          return (
            <CircleMarker
              key={`${s.id}-pt-${isSel ? 'on' : 'off'}`}
              center={[s.lat, s.lon]}
              radius={isSel ? t.radius + 3 : t.radius}
              pathOptions={{
                color: isSel ? BONE_WHITE : dashed ? t.hex : DEEP_GRAPHITE,
                weight: isSel ? 2.5 : dashed ? 1.5 : 1,
                dashArray: dashed && !isSel ? '2 2' : undefined,
                fillColor: t.hex,
                fillOpacity: dashed ? 0.35 : 0.85,
              }}
              eventHandlers={handlers}
            >
              {interactive && <Tooltip>{label(s)}</Tooltip>}
            </CircleMarker>
          );
        })}

        {interactive && <FlyToSelected selected={selected} />}
        {interactive && <MapControls onRecenter={() => onSelect?.(null)} />}
      </MapContainer>

      {interactive && (
        <p className="map-canvas__zoomnote">
          {showLines
            ? 'Road lines: OS Open Roads centrelines (top 5,000 only; others as points).'
            : `Points mark segment midpoints. Zoom to level ${LINE_ZOOM}+ for road lines.`}
        </p>
      )}
      {interactive && (
        <p className="sr-only" id="map-keyboard-help">
          Arrow keys pan the map and the plus and minus keys zoom. Segments on the map cannot be selected with the
          keyboard; use the search box and the segment list, which contain every loaded segment.
        </p>
      )}
      {interactive && notice && (
        <p className="map-canvas__notice" role="status">
          {notice}
        </p>
      )}
      {showLegend && <Legend />}
    </div>
  );
}
