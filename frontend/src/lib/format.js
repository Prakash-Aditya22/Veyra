/* Formatting helpers. Every number the user sees passes through one of these. */

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

export function num(value) {
  if (value === null || value === undefined) return '--';
  return value.toLocaleString('en-IN');
}

export function score(value) {
  if (value === null || value === undefined) return '--';
  return value.toFixed(1);
}

/** Dates read as "26 Nov 2024" - unambiguous, and short enough for a table cell. */
export function shortDate(iso) {
  if (!iso) return '--';
  const d = new Date(`${iso}T00:00:00`);
  return `${String(d.getDate()).padStart(2, '0')} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** "07:00" through "23:00" for histogram axis ticks. */
export function hourLabel(hour) {
  return `${String(hour).padStart(2, '0')}:00`;
}

export function pct(part, whole) {
  if (!whole) return '0.0';
  return ((part / whole) * 100).toFixed(1);
}

export function coords(lat, lng) {
  return `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
}
