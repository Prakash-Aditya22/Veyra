/* Formatting helpers. Every number the user sees passes through one of these (en-GB). */

const NA = 'Not available';

export function int(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return Math.round(value).toLocaleString('en-GB');
}

/** Expected or adjusted casualty counts: two decimals, never rounded to a whole casualty. */
export function ksi(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return value.toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fixed(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return value.toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Share 0-1 -> "37%" (or with decimals). */
export function share(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return `${(value * 100).toFixed(digits)}%`;
}

/** part / whole as a percentage with the denominator kept by the caller. */
export function pct(part, whole, digits = 1) {
  if (!whole) return NA;
  return `${((part / whole) * 100).toFixed(digits)}%`;
}

export function rank(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return `#${Math.round(value).toLocaleString('en-GB')}`;
}

/** "2026-2027" -> "2026–27" */
export function period(p) {
  if (!p) return NA;
  const [a, b] = String(p).split('-');
  return b ? `${a}–${b.slice(2)}` : a;
}

export function metres(value) {
  if (value === null || value === undefined) return NA;
  return `${Math.round(value).toLocaleString('en-GB')} m`;
}

export function coords(lat, lon) {
  return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
}

export const NOT_AVAILABLE = NA;
