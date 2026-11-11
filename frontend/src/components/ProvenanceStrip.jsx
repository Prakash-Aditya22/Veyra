import { Fragment } from 'react';
import './ProvenanceStrip.css';

/**
 * On every screen. This product makes claims about public safety, so it must
 * always state what it is claiming from: the record, its years, and how much
 * of it the screen is drawing on. Each screen passes its own `items`, because
 * each draws on a different slice (live segments, the precomputed summary).
 */
export default function ProvenanceStrip({ items, className = '' }) {
  return (
    <p className={`provenance ${className}`}>
      {items.map((text, i) => (
        <Fragment key={text}>
          {i > 0 && <span className="provenance__sep" aria-hidden="true" />}
          <span className="mono">{text}</span>
        </Fragment>
      ))}
    </p>
  );
}
