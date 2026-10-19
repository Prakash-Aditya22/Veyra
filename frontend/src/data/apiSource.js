/*
  Backend API source. NOT CONNECTED: the Spring Boot API does not provide these endpoints yet.

  The paths below are the ones *suggested* in data/v2/INTEGRATION_CONTRACT.md section 8. They
  are proposals, not an agreed interface. Everything marked DECISION is not specified by the
  contract and must be agreed between the ML and backend developers before this file is
  relied on (see BACKEND_INTEGRATION.md). Until then the app runs in 'local' mode.

  Responses are expected to use the contract field names unchanged (segment_id, rank,
  blackspot_score, ...), so src/data/normalize.js serves both sources. A 404 on an optional
  extension means "not available", never zero.
*/

import { DataSourceError } from './localSource.js';

export class NotAgreedError extends DataSourceError {}

export function createApiSource({ apiBaseUrl, fetchImpl = globalThis.fetch }) {
  if (!apiBaseUrl) {
    throw new DataSourceError(
      'API mode is selected but VITE_API_BASE_URL is not set. Use VITE_DATA_MODE=local for the demo bundle.',
    );
  }
  const get = async (path, { optional = false } = {}) => {
    const res = await fetchImpl(`${apiBaseUrl}${path}`, { headers: { Accept: 'application/json' } });
    if (res.status === 404 && optional) return null;
    if (!res.ok) throw new DataSourceError(`Backend request failed: GET ${path} (HTTP ${res.status}).`);
    return res.json();
  };
  const notAgreed = (what, decision) => async () => {
    throw new NotAgreedError(`${what}: no backend endpoint has been agreed (BACKEND_INTEGRATION.md, ${decision}).`);
  };
  const enc = encodeURIComponent;

  return {
    mode: 'api',
    describe: () => ({ label: 'Backend API (proposed endpoints, not yet agreed)', location: apiBaseUrl }),
    // DECISION D1: release metadata (version, periods, national counts, tiers). Not in the contract.
    getRelease: notAgreed('Release metadata', 'D1'),
    // Suggested in contract section 8: GET /segments?bbox=&limit= (rank order is required).
    getSegments: () => get('/segments?order=rank'),
    // DECISION D2: line geometry (GeoJSON) endpoint and its filtering. Not in the contract.
    getGeometry: async () => null,
    getContext: async () => null,
    // Suggested in contract section 8.
    getExplanation: (id) => get(`/segments/${enc(id)}/explanation`, { optional: true }),
    getStability: (id) => get(`/segments/${enc(id)}/stability`, { optional: true }),
    // DECISION D3: single-event sensitivity endpoint. Not in the contract.
    getSingleEvent: async () => null,
    // Per-segment summaries for filters need a bulk endpoint (DECISION D4); not available.
    extensionSummary: async () => null,
  };
}
