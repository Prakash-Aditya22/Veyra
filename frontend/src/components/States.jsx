import './States.css';

/*
  Empty, error and loading states. Composed, not apologetic; specific, not
  generic. No emoji in any state, and no circular spinners.
*/

/** A muted line-art road fork. The only hand-drawn mark in the product. */
function RoadForkMark() {
  return (
    <svg
      className="state__mark"
      viewBox="0 0 64 48"
      width="64"
      height="48"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M32 47V29m0 0L16 13m16 16 16-16"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <path
        d="M11 8h10M43 8h10"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.5"
      />
      <path
        d="M32 41v-4m0-6v-4"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.35"
      />
    </svg>
  );
}

export function EmptyState({ title, detail, action }) {
  return (
    <div className="state">
      <RoadForkMark />
      <p className="state__title">{title}</p>
      <p className="state__detail">{detail}</p>
      {action}
    </div>
  );
}

/**
 * Inline and specific. Never a full-screen takeover, because that would
 * discard the filter state the user built.
 */
export function ErrorState({ message, onRetry }) {
  return (
    <div className="state-error" role="alert">
      <div className="state-error__body">
        <p className="state-error__title">{message}</p>
        {onRetry && (
          <button className="btn btn-secondary state-error__retry" onClick={onRetry}>
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

/** Row-height bars matching the table they replace. */
export function TableSkeleton({ rows = 8 }) {
  return (
    <div className="skeleton-rows" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton skeleton-rows__row" />
      ))}
    </div>
  );
}

/** A graphite panel the exact size of the map, with a plain statement. */
export function MapSkeleton() {
  return (
    <div className="skeleton-map">
      <p className="label">Loading incident clusters</p>
    </div>
  );
}

export function ChartSkeleton({ height = 220 }) {
  return <div className="skeleton" style={{ height }} aria-hidden="true" />;
}
