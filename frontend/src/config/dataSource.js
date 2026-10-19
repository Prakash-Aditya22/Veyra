/*
  Data-source configuration: the only place that decides where the data comes from.

  VITE_DATA_MODE      'local' (default) - the verified demo bundle in public/data/demo-v2,
                                          generated from the v2 ML release. No backend needed.
                      'api'             - the Spring Boot backend. Not available yet: the
                                          endpoints are proposals awaiting agreement
                                          (BACKEND_INTEGRATION.md).
  VITE_API_BASE_URL   base URL of the backend API, required in 'api' mode.
  VITE_LOCAL_DATA_URL where the local bundle is served (default <base>/data/demo-v2).

  Components never read these values; they receive data through src/data/DataContext.jsx.
*/

const env = (typeof import.meta !== 'undefined' && import.meta.env) || {};

export const DATA_MODES = ['local', 'api'];

export function readDataConfig(source = env) {
  const mode = (source.VITE_DATA_MODE || 'local').trim();
  const base = source.BASE_URL || '/';
  return {
    mode,
    apiBaseUrl: (source.VITE_API_BASE_URL || '').replace(/\/+$/, ''),
    localDataUrl: (source.VITE_LOCAL_DATA_URL || `${base.replace(/\/+$/, '')}/data/demo-v2`).replace(/\/+$/, ''),
  };
}

export const DATA_CONFIG = readDataConfig();
