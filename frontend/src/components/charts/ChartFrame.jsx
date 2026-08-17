import './ChartFrame.css';

/**
 * Every chart in the product states its date range and record count beneath
 * the title. The frame makes that structural rather than a thing an author
 * has to remember.
 */
export default function ChartFrame({ title, meta, children, className = '' }) {
  return (
    <section className={`chart-frame ${className}`}>
      <header className="chart-frame__head">
        <h3 className="panel-title">{title}</h3>
        <p className="label chart-frame__meta">{meta}</p>
      </header>
      <div className="chart-frame__body">{children}</div>
    </section>
  );
}

/** Raised Slate card, mono values. Used by every chart's Recharts tooltip. */
export function ChartTooltip({ active, payload, label, unit = 'incidents' }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <p className="chart-tooltip__label mono">{label}</p>
      {payload.map((entry) => (
        <p key={entry.dataKey} className="chart-tooltip__row">
          <span
            className="chart-tooltip__swatch"
            style={{ background: entry.color ?? entry.fill }}
            aria-hidden="true"
          />
          <span className="chart-tooltip__name">{entry.name}</span>
          <span className="chart-tooltip__value mono">
            {entry.value.toLocaleString('en-IN')}
          </span>
        </p>
      ))}
      <p className="chart-tooltip__unit">{unit}</p>
    </div>
  );
}

/* Shared Recharts axis and grid config. Horizontal gridlines only, no chart junk. */
export const AXIS = {
  stroke: 'transparent',
  tick: {
    fill: '#9AA2AE',
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 11,
  },
  tickLine: false,
  axisLine: false,
};

export const GRID = {
  stroke: 'rgba(148, 163, 184, 0.14)',
  strokeDasharray: '0',
  vertical: false,
};
