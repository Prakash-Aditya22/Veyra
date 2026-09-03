import { useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet.heat';
import { Plus, Minus, StackSimple, MapTrifold, CrosshairSimple } from '@phosphor-icons/react';
import { tierOf, markerRadius } from '../lib/risk.js';
import { MAP_CENTER, MAP_ZOOM } from '../data/blackspots.js';
import Legend from './Legend.jsx';
import './MapCanvas.css';

const DEEP_GRAPHITE = '#131417';
const BONE_WHITE = '#EEF1F5';

function prefersReducedMotion() {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/** Selecting a ranked row flies the map to that cluster over 600ms. */
function FlyToSelected({ selected }) {
  const map = useMap();
  useEffect(() => {
    if (!selected) return;
    const target = [selected.lat, selected.lng];
    if (prefersReducedMotion()) {
      map.setView(target, Math.max(map.getZoom(), 14), { animate: false });
    } else {
      map.flyTo(target, Math.max(map.getZoom(), 14), { duration: 0.6 });
    }
  }, [selected, map]);
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
        0.0: '#C9A227',
        0.35: '#C2711F',
        0.65: '#A33A2B',
        1.0: '#7A1F1A',
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
function MapControls({ layer, onLayerChange, onRecenter }) {
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
            map.setView(MAP_CENTER, MAP_ZOOM);
          }}
          aria-label="Reset the view to the full corridor"
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
        center={MAP_CENTER}
        zoom={MAP_ZOOM}
        className="map-canvas__map"
        zoomControl={false}
        scrollWheelZoom={interactive}
        dragging={interactive}
        doubleClickZoom={interactive}
        touchZoom={interactive}
        keyboard={interactive}
        attributionControl
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          subdomains="abcd"
          maxZoom={19}
        />

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
                  color: isSelected ? BONE_WHITE : DEEP_GRAPHITE,
                  weight: isSelected ? 2 : 1.5,
                  fillColor: tier.hex,
                  fillOpacity: 0.85,
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

        {interactive && <FlyToSelected selected={selected} />}
        {interactive && (
          <MapControls
            layer={layer}
            onLayerChange={setLayer}
            onRecenter={() => onSelect?.(null)}
          />
        )}
      </MapContainer>

      {showLegend && <Legend />}
    </div>
  );
}
