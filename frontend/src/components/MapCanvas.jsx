import { useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet.heat';
import { Plus, Minus, StackSimple, MapTrifold, CrosshairSimple } from '@phosphor-icons/react';
import { tierOf, markerRadius, THIN_FILL_OPACITY } from '../lib/risk.js';
import Legend from './Legend.jsx';
import Basemap from './Basemap.jsx';
import './MapCanvas.css';

// Marker outlines: the black ground separates a marker from the dark basemap;
// paper white marks the selected one.
const OUTLINE = '#0E0F11';
const OUTLINE_SELECTED = '#EEF0F4';

function prefersReducedMotion() {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/**
 * Reports the viewport as a `minLon,minLat,maxLon,maxLat` string - the order
 * BoundingBox.parse on the server expects, which is Leaflet's own reporting
 * order and not Leaflet's [lat, lng] point order.
 *
 * It emits once on mount as well as on every moveend, because Leaflet fires no
 * move event for the initial view and the first fetch would otherwise wait for
 * the user to touch the map.
 *
 * Coordinates are rounded to four decimals (about 11 m) so that a one-pixel
 * settle after a fly-to does not produce a new string and a new request.
 */
function BoundsReporter({ onChange }) {
  const map = useMap();
  useEffect(() => {
    if (!onChange) return undefined;
    const emit = () => {
      const b = map.getBounds();
      const r = (v) => Number(v.toFixed(4));
      // At low zoom the world wraps and the bounds run past ±180/±90, which
      // the server rejects.
      const west = Math.max(-180, r(b.getWest()));
      const south = Math.max(-90, r(b.getSouth()));
      const east = Math.min(180, r(b.getEast()));
      const north = Math.min(90, r(b.getNorth()));
      if (west >= east || south >= north) return;
      onChange(`${west},${south},${east},${north}`);
    };
    emit();
    map.on('moveend', emit);
    return () => map.off('moveend', emit);
  }, [map, onChange]);
  return null;
}

/**
 * Selecting a ranked row flies the map to that stretch over 600ms.
 *
 * The effect keys on the selected id, not on the selected object. Live
 * segments are rebuilt on every viewport fetch, so a dependency on object
 * identity would re-fire the fly-to after each pan and drag the user back to
 * their selection - the map would refuse to be moved.
 */
function FlyToSelected({ id, lat, lng }) {
  const map = useMap();
  const at = useRef({ lat, lng });
  at.current = { lat, lng };

  useEffect(() => {
    if (!id) return;
    const target = [at.current.lat, at.current.lng];
    if (prefersReducedMotion()) {
      map.setView(target, Math.max(map.getZoom(), 14), { animate: false });
    } else {
      map.flyTo(target, Math.max(map.getZoom(), 14), { duration: 0.6 });
    }
  }, [id, map]);
  return null;
}

/**
 * Continuous density layer using the same ramp, capped at 55% opacity so the
 * street geometry underneath stays readable.
 */
function HeatLayer({ points, active }) {
  const map = useMap();
  const layerRef = useRef(null);

  useEffect(() => {
    if (!active) return undefined;

    const layer = L.heatLayer(points, {
      radius: 34,
      blur: 24,
      maxZoom: 15,
      minOpacity: 0.18,
      max: 1,
      gradient: {
        0.0: '#F2A31B',
        0.35: '#F2A31B',
        0.65: '#D7120F',
        1.0: '#8E44AD',
      },
    });
    layer.addTo(map);
    layerRef.current = layer;

    const el = layer._canvas;
    if (el) el.style.opacity = '0.55';

    return () => {
      map.removeLayer(layer);
      layerRef.current = null;
    };
  }, [map, points, active]);

  return null;
}

/** Custom zoom and layer controls. The default Leaflet chrome is banned. */
function MapControls({ layer, onLayerChange, onRecenter, home, homeZoom, homeLabel }) {
  const map = useMap();
  return (
    <div className="map-controls">
      <div className="map-controls__cluster">
        <button
          className="map-btn"
          onClick={() => map.zoomIn()}
          aria-label="Zoom in"
        >
          <Plus size={16} weight="bold" />
        </button>
        <span className="map-controls__rule" aria-hidden="true" />
        <button
          className="map-btn"
          onClick={() => map.zoomOut()}
          aria-label="Zoom out"
        >
          <Minus size={16} weight="bold" />
        </button>
      </div>

      <div className="map-controls__cluster">
        <button
          className={`map-btn${layer === 'clusters' ? ' map-btn--on' : ''}`}
          onClick={() => onLayerChange('clusters')}
          aria-label="Show cluster markers"
          aria-pressed={layer === 'clusters'}
          title="Cluster markers"
        >
          <MapTrifold size={16} weight="regular" />
        </button>
        <span className="map-controls__rule" aria-hidden="true" />
        <button
          className={`map-btn${layer === 'heat' ? ' map-btn--on' : ''}`}
          onClick={() => onLayerChange('heat')}
          aria-label="Show density layer"
          aria-pressed={layer === 'heat'}
          title="Density layer"
        >
          <StackSimple size={16} weight="regular" />
        </button>
      </div>

      <div className="map-controls__cluster">
        <button
          className="map-btn"
          onClick={() => {
            onRecenter();
            map.setView(home, homeZoom);
          }}
          aria-label={`Reset the view to ${homeLabel}`}
          title="Reset view"
        >
          <CrosshairSimple size={16} weight="regular" />
        </button>
      </div>
    </div>
  );
}

export default function MapCanvas({
  blackspots,
  selectedId,
  onSelect,
  onBoundsChange,
  /*
    The home view is a prop because two screens frame the map differently:
    Explorer opens on the whole of Great Britain to browse, the Overview
    frames a static preview. Both pass their own; these defaults are GB.
  */
  center = [54.2, -2.6],
  zoom = 6,
  homeLabel = 'the whole of Great Britain',
  interactive = true,
  showLegend = true,
  className = '',
}) {
  const [layer, setLayer] = useState('clusters');

  const selected = useMemo(
    () => blackspots.find((b) => b.id === selectedId) ?? null,
    [blackspots, selectedId],
  );

  const maxIncidents = useMemo(
    () => Math.max(1, ...blackspots.map((b) => b.incidents)),
    [blackspots],
  );

  const heatPoints = useMemo(
    () =>
      blackspots.map((b) => [
        b.lat,
        b.lng,
        Math.min(1, (b.score ?? 5) / 100 + b.incidents / (maxIncidents * 2)),
      ]),
    [blackspots, maxIncidents],
  );

  // Touch pointers get a wider hit target without changing the visual radius.
  const coarsePointer =
    typeof window !== 'undefined' &&
    window.matchMedia('(pointer: coarse)').matches;

  return (
    <div className={`map-canvas ${className}`}>
      <MapContainer
        center={center}
        zoom={zoom}
        className="map-canvas__map"
        zoomControl={false}
        scrollWheelZoom={interactive}
        dragging={interactive}
        doubleClickZoom={interactive}
        touchZoom={interactive}
        keyboard={interactive}
        attributionControl
      >
        <Basemap />

        {layer === 'heat' && <HeatLayer points={heatPoints} active />}

        {layer === 'clusters' &&
          blackspots.map((b) => {
            const tier = tierOf(b.score);
            const r = markerRadius(b.incidents, maxIncidents);
            const isSelected = b.id === selectedId;
            const visual = (
              <CircleMarker
                /*
                  Leaflet applies `className` when the path is created and
                  ignores it on later setStyle calls, so the key carries the
                  selected state to force a recreate. Without this the white
                  ring and the pulse never appear on a click-driven selection.
                */
                key={`${b.id}-visual-${isSelected ? 'on' : 'off'}`}
                center={[b.lat, b.lng]}
                radius={r}
                interactive={!coarsePointer}
                pathOptions={{
                  color: isSelected ? OUTLINE_SELECTED : OUTLINE,
                  weight: isSelected ? 2 : 1.5,
                  fillColor: tier.hex,
                  // A segment under the six-crash floor is drawn, not hidden -
                  // absence of evidence is not evidence of safety - but it is
                  // dimmed so it never reads as an equal of a scored one. The
                  // legend shows its sample at the same constant.
                  fillOpacity: b.thinlyEvidenced ? THIN_FILL_OPACITY : 0.85,
                  opacity: b.thinlyEvidenced ? 0.55 : 1,
                  className: isSelected ? 'map-marker--selected' : undefined,
                }}
                eventHandlers={coarsePointer ? undefined : { click: () => onSelect?.(b.id) }}
              />
            );

            if (!coarsePointer) return visual;

            // Touch pointers get an invisible 22px hit target sitting under the
            // visual circle, so the marker is tappable without growing on screen.
            return [
              <CircleMarker
                key={`${b.id}-target`}
                center={[b.lat, b.lng]}
                radius={22}
                pathOptions={{ opacity: 0, fillOpacity: 0, weight: 0 }}
                eventHandlers={{ click: () => onSelect?.(b.id) }}
              />,
              visual,
            ];
          })}

        {interactive && (
          <FlyToSelected id={selected?.id} lat={selected?.lat} lng={selected?.lng} />
        )}
        {interactive && <BoundsReporter onChange={onBoundsChange} />}
        {interactive && (
          <MapControls
            layer={layer}
            onLayerChange={setLayer}
            onRecenter={() => onSelect?.(null)}
            home={center}
            homeZoom={zoom}
            homeLabel={homeLabel}
          />
        )}
      </MapContainer>

      {showLegend && <Legend />}
    </div>
  );
}
