/*
  Local data source: the verified demo bundle in public/data/demo-v2 (no backend).

  The bundle is generated on the ML branch by ml/demo/make_frontend_demo_data.py from the v2
  release and checked by ml/audit/validate_frontend_demo.py. Each file is fetched once and
  cached; filters work on the in-memory copy, so nothing is re-downloaded per interaction.

  Required: manifest.json, segments.json. Optional: geometry, explanations, stability,
  single_event, context. A missing optional file means "not available", never an error and
  never a placeholder value.
*/

const OPTIONAL = {
  geometry: 'geometry.geojson',
  explanations: 'explanations.json',
  stability: 'stability.json',
  singleEvent: 'single_event.json',
  context: 'context.json',
};

export class DataSourceError extends Error {}

export function createLocalSource({ localDataUrl, fetchImpl = globalThis.fetch }) {
  const cache = new Map();

  const getJson = (name, { optional = false } = {}) => {
    if (!cache.has(name)) {
      cache.set(
        name,
        fetchImpl(`${localDataUrl}/${name}`).then(async (res) => {
          // Static hosts and the Vite dev server answer a missing file with index.html (200),
          // so a non-JSON body counts as "file absent".
          const type = res.headers?.get?.('content-type') ?? 'application/json';
          const absent = res.status === 404 || (res.ok && !type.includes('json'));
          if (absent && optional) return null;
          if (absent || !res.ok) {
            throw new DataSourceError(`Could not load ${name} (HTTP ${res.status}) from ${localDataUrl}.`);
          }
          return res.json();
        }),
      );
    }
    return cache.get(name);
  };

  const byId = (key) => async (id) => {
    const all = await getJson(OPTIONAL[key], { optional: true });
    return all?.[id] ?? null;
  };

  return {
    mode: 'local',
    describe: () => ({ label: 'Local demo bundle (verified subset of the v2 release)', location: localDataUrl }),
    getRelease: () => getJson('manifest.json'),
    getSegments: () => getJson('segments.json'),
    getGeometry: () => getJson(OPTIONAL.geometry, { optional: true }),
    getContext: () => getJson(OPTIONAL.context, { optional: true }),
    getExplanation: byId('explanations'),
    getStability: byId('stability'),
    getSingleEvent: byId('singleEvent'),
    /**
     * Light per-segment summaries for filters and statistics, from the optional files.
     * A missing file gives an empty map, which the UI reports as "not available".
     */
    extensionSummary: async () => {
      const [e, s, x] = await Promise.all([
        getJson(OPTIONAL.explanations, { optional: true }),
        getJson(OPTIONAL.stability, { optional: true }),
        getJson(OPTIONAL.singleEvent, { optional: true }),
      ]);
      const entries = (obj, pick) => new Map(Object.entries(obj ?? {}).map(([id, v]) => [id, pick(v)]));
      return {
        provided: { explanations: !!e, stability: !!s, singleEvent: !!x },
        leadingFactor: entries(e, (v) => [...v.top].sort((a, b) => a.contrib_rank - b.contrib_rank)[0]?.label ?? null),
        stabilityClass: entries(s, (v) => v.stability_class),
        rankRange: entries(s, (v) => [v.rank_p05, v.rank_p95]),
        oneCollisionRank: entries(x, (v) => v.rank_without_largest_collision_one_at_a_time),
      };
    },
  };
}
