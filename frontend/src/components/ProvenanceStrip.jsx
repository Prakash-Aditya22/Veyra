import { useData } from '../data/DataContext.jsx';
import { int, period } from '../lib/format.js';
import './ProvenanceStrip.css';

/**
 * On every screen. States what the figures are claimed from: the ML release, its periods,
 * the geography, and how much of the national model is loaded here.
 */
export default function ProvenanceStrip({ className = '' }) {
  const data = useData();
  if (data.status !== 'ready') return null;
  const r = data.release;
  return (
    <p className={`provenance ${className}`}>
      <span className="mono">ML release {r.version}</span>
      <span className="provenance__sep" aria-hidden="true" />
      <span>Great Britain (England, Scotland, Wales)</span>
      <span className="provenance__sep" aria-hidden="true" />
      <span className="mono">
        STATS19 {period(r.historyPeriod)} → forecast {period(r.forecastPeriod)}
      </span>
      <span className="provenance__sep" aria-hidden="true" />
      <span className="mono">
        {int(data.segments.length)} of {int(r.nationalSegments)} scored segments loaded
      </span>
      <span className="provenance__sep" aria-hidden="true" />
      <span>{data.source.label}</span>
    </p>
  );
}
