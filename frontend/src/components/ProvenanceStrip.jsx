import { DATASET } from '../data/blackspots.js';
import { num } from '../lib/format.js';
import './ProvenanceStrip.css';

/**
 * On every screen. This product makes claims about public safety, so it must
 * always state what it is claiming from - including that the figures are a
 * demonstration fixture rather than the processed dataset.
 */
export default function ProvenanceStrip({ className = '' }) {
  return (
    <p className={`provenance ${className}`}>
      <span className="mono">{DATASET.label}</span>
      <span className="provenance__sep" aria-hidden="true" />
      <span className="mono">
        {DATASET.from} to {DATASET.to}
      </span>
      <span className="provenance__sep" aria-hidden="true" />
      <span className="mono">{num(DATASET.records)} records</span>
      <span className="provenance__sep" aria-hidden="true" />
      <span className="mono">{DATASET.clusters} clusters</span>
      <span className="provenance__sep" aria-hidden="true" />
      <span className="mono">computed {DATASET.computedOn}</span>
    </p>
  );
}
