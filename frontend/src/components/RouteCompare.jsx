import { formatExpectedKsi } from '../lib/riskScale.js';
import './RouteCompare.css';

function minutes(seconds) {
  return `${Math.round(seconds / 60)} min`;
}

function kilometres(metres) {
  return `${(metres / 1000).toFixed(1)} km`;
}

/*
  One card per candidate route. The risk figure is deliberately phrased as a
  property of the corridor over two years, not of the reader's journey - the
  score is expected casualties across all traffic, and the difference between
  those two readings is three orders of magnitude.

  The routing provider returns up to three candidates and sometimes fewer, so
  nothing here assumes a fixed count; the list is whatever came back.
*/
export default function RouteCompare({ routes, selectedIndex, onSelect }) {
  return (
    <ul className="route-compare">
      {routes.map((r) => (
        <li key={r.index}>
          <button
            type="button"
            className={`route-compare__card${r.index === selectedIndex ? ' is-selected' : ''}`}
            aria-pressed={r.index === selectedIndex}
            onClick={() => onSelect(r.index)}
          >
            <span className="route-compare__label">{r.label}</span>
            <span className="route-compare__stats mono">
              {minutes(r.durationSeconds)} · {kilometres(r.distanceMetres)}
            </span>
            {/*
              Three-digit KSI values and two-digit blackspot counts are normal
              on a long urban corridor, so the two figures sit in a wrapping
              row with a hairline separator rather than a single run of text
              that would break mid-sentence in a 280px rail.
            */}
            <span className="route-compare__risk">
              {r.blackspotCount > 0 && (
                <>
                  <span className="route-compare__figure">
                    <span className="mono">{r.blackspotCount}</span>
                    {` blackspot${r.blackspotCount === 1 ? '' : 's'}`}
                  </span>
                  <span className="route-compare__dot" aria-hidden="true" />
                </>
              )}
              {/*
                formatExpectedKsi carries its own unit and window, and reads
                "no recorded blackspots" at zero - which is why the count is
                dropped in that case rather than printed as a bare "0".
              */}
              <span className="route-compare__figure mono">
                {formatExpectedKsi(r.expectedKsi)}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
