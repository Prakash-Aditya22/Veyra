/*
  The backend is the only service this app talks to. Routing and geocoding go
  through it so the OpenRouteService key stays server-side.
*/

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8081';

export class ApiError extends Error {
  constructor(status, message, options) {
    super(message, options);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, options);
  } catch (cause) {
    // An aborted request is the caller's own doing, not a failure worth
    // surfacing as "the backend is down" — let it propagate so callers can
    // ignore it.
    if (cause?.name === 'AbortError') throw cause;
    throw new ApiError(0, 'Cannot reach the API. Is the backend running?', { cause });
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.message) message = body.message;
    } catch {
      /* a non-JSON error body is not worth surfacing */
    }
    throw new ApiError(res.status, message);
  }
  return res.json();
}

export function getSegments({ bbox, minScore = 0, minCrashes = 6, limit = 500, signal } = {}) {
  const q = new URLSearchParams({ minScore, minCrashes, limit });
  if (bbox) q.set('bbox', bbox);
  return request(`/api/segments?${q}`, { signal });
}

export function getSegment(segmentId, { signal } = {}) {
  return request(`/api/segments/${encodeURIComponent(segmentId)}`, { signal });
}

export function geocode(q, { signal } = {}) {
  return request(`/api/geocode?q=${encodeURIComponent(q)}`, { signal });
}

export function routeRisk({ from, to, minCrashes, signal }) {
  return request('/api/route/risk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from, to, minCrashes }),
    signal,
  });
}
