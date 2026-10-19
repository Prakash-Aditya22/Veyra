import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { createDataSource, loadCatalog } from './catalog.js';
import { explanationView, singleEventView, stabilityView } from './normalize.js';

/*
  The single place screens get data from. The catalog loads once per session and is shared by
  every route, so changing a filter or a screen never refetches. Per-segment extensions load on
  selection and are cached by the source.
*/

const DataContext = createContext(null);

export function DataProvider({ children, config }) {
  const [state, setState] = useState({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const source = useMemo(() => {
    try {
      return { ok: createDataSource(config) };
    } catch (error) {
      return { error };
    }
  }, [config, attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (source.error) {
      setState({ status: 'error', error: source.error.message });
      return undefined;
    }
    let live = true;
    setState({ status: 'loading' });
    loadCatalog(source.ok)
      .then((catalog) => live && setState({ status: 'ready', ...catalog, sourceImpl: source.ok }))
      .catch((error) => live && setState({ status: 'error', error: error.message }));
    return () => {
      live = false;
    };
  }, [source]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const value = useMemo(() => ({ ...state, retry }), [state, retry]);
  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

export function useData() {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error('useData must be used inside <DataProvider>');
  return ctx;
}

/** Optional extensions for one segment. Each part is independently "not available". */
export function useSegmentDetail(segment) {
  const data = useData();
  const [detail, setDetail] = useState({ status: 'idle' });
  useEffect(() => {
    if (!segment || data.status !== 'ready') return undefined;
    let live = true;
    setDetail({ status: 'loading' });
    const src = data.sourceImpl;
    const soft = (p) => p.catch(() => null); // an extension failure means "not available", not a crash
    Promise.all([soft(src.getExplanation(segment.id)), soft(src.getStability(segment.id)), soft(src.getSingleEvent(segment.id))])
      .then(([e, s, x]) => {
        if (!live) return;
        setDetail({
          status: 'ready',
          explanation: explanationView(e),
          stability: stabilityView(s),
          singleEvent: singleEventView(segment, x),
        });
      });
    return () => {
      live = false;
    };
  }, [segment, data.status, data.sourceImpl]);
  return detail;
}
