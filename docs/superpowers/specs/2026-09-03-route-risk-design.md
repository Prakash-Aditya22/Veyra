# Route Risk — Design

**Date:** 2026-09-03
**Status:** Approved, ready for implementation planning
**Branch:** `integration` (merge of `main` + `ML` + `frontend-v1`)

## Problem

The project has blackspot scores for 45,014 segments of British road and a React
frontend that displays them, but the two were built against different contracts
and never connected. There is no backend at all.

This design connects them and adds the feature that makes the data actionable:
**a driver enters A and B, and sees which blackspots lie on the way — and
whether a different route avoids them.**

## Scope

**In:** Spring Boot backend on Supabase Postgres/PostGIS; segment API; route
risk API with scored alternatives; a new Route screen; retheming the existing
four screens from the Indian demo fixture to the real UK data.

**Out:** the 15-task ML remediation (shelved — see Limitations); community
hazard reporting; weather overlay; time-based playback; proximity alerts.

### Phasing

The scope check says this is more than one implementation plan. It splits at a
natural seam, and **Phase 1 is what was actually asked for**:

**Phase 1 — the two features.** Backend, Supabase schema, loader, segment API,
route-risk API, the new Route screen, and Explorer switched from the fixture to
the live API. This is "the blackspot feature and the path-finding feature", end
to end and demonstrable.

**Phase 2 — the remaining retheme.** Rankings and Statistics still read
`blackspots.js` and `series.js`. They keep working on the fixture throughout
Phase 1, so nothing breaks; moving them to the API is its own plan, and needs
the EDA aggregates that do not exist yet (a shelved remediation task).

Only Phase 1 goes to `writing-plans` from this spec.

## Architecture

```
data/road_segments_ranked.csv  ──(Java loader, one-off)──▶  Supabase
                                                            Postgres + PostGIS
                                                                  ▲
                                                                  │ JDBC
                                            ┌─────────────────────┴──────────┐
                                            │  Spring Boot (Java 22, Maven)  │
   OpenRouteService  ◀──── ORS_API_KEY ─────┤  /api/geocode                  │
   (routing + geocode)                      │  /api/segments                 │
                                            │  /api/route/risk               │
                                            └─────────────────┬──────────────┘
                                                              │ REST
                                            ┌─────────────────┴──────────────┐
                                            │  React + Leaflet (frontend/)   │
                                            │  Landing · Explorer · Rankings │
                                            │  Statistics · Route  ← new     │
                                            └────────────────────────────────┘
```

Repo layout after this work: `frontend/ backend/ ml/ data/ docs/`.

The ORS key lives only in `backend/.env` (gitignored) and is read from the
environment. It never reaches the browser — the frontend talks only to Spring
Boot.

## Components

Each unit below has one responsibility and is testable on its own.

| Unit | Responsibility | Depends on |
|---|---|---|
| `SegmentLoader` | One-off CSV → Postgres load, behind `--load-data` | JDBC |
| `SegmentRepository` | Segment queries: by id, by bbox, top-N, corridor | JDBC, PostGIS |
| `RoutingClient` | ORS directions + geocode, HTTP only, no domain logic | ORS |
| `RouteRiskService` | Orchestrates: route → corridor match → aggregate | `RoutingClient`, `SegmentRepository` |
| `SegmentController` | `/api/segments*` | `SegmentRepository` |
| `RouteController` | `/api/route/risk`, `/api/geocode` | `RouteRiskService` |
| `RiskScale` (frontend) | `blackspot_score` → the existing 0–100 tier scale | — |
| `Route.jsx` (frontend) | The new screen | API client, Leaflet |

`RoutingClient` is deliberately dumb — it returns ORS's response shape and
knows nothing about blackspots. That keeps `RouteRiskService` unit-testable
against a fake client with no HTTP.

## Database

Supabase has PostGIS pre-installed; `CREATE EXTENSION` is still issued so the
schema is self-contained.

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE road_segment (
  segment_id       TEXT PRIMARY KEY,
  road_id          TEXT NOT NULL,
  run              INTEGER NOT NULL,
  location         TEXT NOT NULL,
  km_from          DOUBLE PRECISION,
  km_to            DOUBLE PRECISION,
  geom             GEOGRAPHY(POINT,4326) NOT NULL,
  blackspot_score  DOUBLE PRECISION NOT NULL,
  rank             INTEGER NOT NULL,
  n_crashes        INTEGER NOT NULL,
  n_ksi            INTEGER NOT NULL,
  n_fatal          INTEGER NOT NULL,
  ksi_rate         DOUBLE PRECISION,
  crashes_per_year DOUBLE PRECISION,
  speed_max        DOUBLE PRECISION,
  pct_night        DOUBLE PRECISION,
  pct_junction     DOUBLE PRECISION
);
CREATE INDEX idx_seg_geom  ON road_segment USING GIST (geom);
CREATE INDEX idx_seg_score ON road_segment (blackspot_score DESC);
CREATE INDEX idx_seg_road  ON road_segment (road_id, run, km_from);
```

Two loader requirements, both from defects found in the existing data:

1. **`future_ksi` and `future_fatal` are dropped, not loaded.** They are the
   2022–23 outcome the model is validated against. There is no column for
   them, so they cannot leak into an API response.
2. **`run` is not a column in the CSV**, although the segment identity depends
   on it — a road number can cover geographically separate stretches (crashes
   tagged `A503` appear 543 km apart). The loader parses it from
   `segment_id`: `A23_run3_km0.5` → `run = 3`. A row whose id does not match
   `^(.+)_run(\d+)_km([\d.]+)$` aborts the load rather than defaulting to 0.

## API

### `GET /api/segments?bbox=&minScore=&minCrashes=&limit=`

Segments for the Explorer map. `bbox` is `minLon,minLat,maxLon,maxLat`.
Default `limit` 500, hard cap 2000.

### `GET /api/segments/{segmentId}`

One segment, for the detail panel. 404 if unknown.

### `GET /api/geocode?q=`

Proxies ORS geocoding, `boundary.country=GB`. Returns at most 5 candidates as
`{ label, lon, lat }`. Empty list when nothing matches — not an error.

### `POST /api/route/risk`

```json
{
  "from": [-0.0982, 51.3762],
  "to":   [-0.1426, 51.5390],
  "minCrashes": 6,
  "corridorMetres": 50
}
```

Response:

```json
{
  "routes": [
    {
      "index": 0,
      "label": "Fastest",
      "distanceMetres": 18240,
      "durationSeconds": 2040,
      "geometry": { "type": "LineString", "coordinates": [[-0.098, 51.376], "..."] },
      "expectedKsi": 4.23,
      "blackspotCount": 6,
      "worstSegmentId": "A23_run3_km0.5",
      "blackspots": [
        {
          "segmentId": "A23_run3_km0.5",
          "location": "A23 km 0.5-1.0 (seg 3)",
          "lat": 51.4607, "lon": -0.1160,
          "blackspotScore": 9.67,
          "nCrashes": 60, "nKsi": 10, "nFatal": 0,
          "speedMax": 30,
          "metresAlongRoute": 1420
        }
      ]
    }
  ],
  "coverageWarning": null
}
```

`label` is assigned by the service: the shortest `durationSeconds` is
`"Fastest"`, the lowest `expectedKsi` is `"Safest"`, and one route can hold
both labels. Remaining routes are `"Alternative"`.

### Corridor query

For each route, its LineString is passed to PostGIS:

```sql
SELECT s.*,
       ST_LineLocatePoint(:route::geometry, s.geom::geometry) AS frac
FROM road_segment s
WHERE ST_DWithin(s.geom, :route::geography, :corridorMetres)
  AND s.n_crashes >= :minCrashes
ORDER BY frac;
```

`ST_DWithin` on `geography` gives true metre distances. Ordering by
`ST_LineLocatePoint` returns blackspots in the order a driver passes them;
`metresAlongRoute` is `frac × distanceMetres`.

**Defaults and why.** `corridorMetres = 50` — segment coordinates are the mean
of their crash positions, not a surveyed centreline, so a tighter buffer drops
real matches. `minCrashes = 6` — **86% of segments rest on fewer than six
crashes** and their scores are noise; the ML README states this filter
explicitly for anything user-facing. The frontend exposes a toggle that lowers
it to 1 and renders those results greyed, so the filter is visible rather than
silent.

## Risk scale

The frontend already has a published tier scale in `frontend/src/lib/risk.js`:
Watch 0–24, Elevated 25–49, Severe 50–74, Critical 75–100, plus a No-data tier.
`blackspot_score` is expected KSI casualties over two years and runs 0–9.67.

**The mapping lives on the frontend only.** The API returns raw
`blackspotScore`; `scoreToDisplay` converts it for rendering. Keeping one
representation on the wire means the tier constants have exactly one home.

Rather than change the published tiers or map by percentile — which would make
a quarter of all British road "Critical" — the ML's own band cutoffs are mapped
piecewise-linearly onto the existing 0–100 scale, so the tier words keep the
meaning the ML gave them:

| `blackspot_score` | Display 0–100 | Tier | Share of displayed segments |
|---|---|---|---|
| 0 → 0.94 | 0 → 24 | Watch | 50% |
| 0.94 → 1.57 | 25 → 49 | Elevated | 30% |
| 1.57 → 3.09 | 50 → 74 | Severe | 15% |
| 3.09 → 9.67 | 75 → 100 | Critical | 5% |

**Revised 2026-09-03 after measuring the data.** Cutoffs are calibrated to the
population the UI actually displays, not to all 45,014 segments. The UI filters
to `n_crashes >= 6`, which strips out overwhelmingly low-scoring rows: the
median over all segments is 0.25, but over the 6,213 displayed it is 0.94.
Cutoffs drawn from the full population put **23.3% of displayed segments in
"Critical"** and 60% in Severe-or-worse — the very outcome percentile mapping
was rejected to avoid. The values above are the 50th/80th/95th percentiles of
the displayed population.

The legend must state that tiers rank segments with enough evidence to be
ranked, and are not absolute national bands — a segment shown as "Watch" at
0.90 still sits above the national median. That disclosure is what makes this
calibration honest rather than flattering. `lib/risk.js` keeps `tierOf`, `markerRadius`, and
`worstTier` unchanged; a new `scoreToDisplay(blackspotScore)` does the mapping
and is the only place the constants live. The raw expected-KSI value is shown
alongside the tier in the detail panel, never replaced by it.

## The Route screen

Left rail: two inputs with geocode autocomplete, or click-to-drop pins on the
map. A `minCrashes` toggle ("include thinly-evidenced segments").

Centre: Leaflet map. Selected route bold, alternatives thin. Blackspot markers
sized by `markerRadius(nCrashes, maxCrashes)` and coloured by tier — the same
components the Explorer already uses.

Right: one comparison card per route —

```
Fastest   34 min · 18.2 km · 6 blackspots · 4.2 KSI over 2 years
Safest    39 min · 19.8 km · 2 blackspots · 1.1 KSI over 2 years
```

— then the ordered blackspot list for the selected route. Each row deep-links
to `/explorer?segment=<id>`, reusing the existing detail panel.

### Wording is a requirement, not a preference

`expectedKsi` is **expected killed-or-seriously-injured casualties on that
corridor over two years, across all traffic**. It is not the user's risk on one
trip, and the difference is three orders of magnitude.

The UI says *"this corridor is expected to produce 4.2 KSI casualties over two years."*
It must never say *"your journey is 4.2 dangerous"*, show a per-trip
probability, or label anything "predicted severity". The severity model behind
this data has ROC-AUC 0.658 and its own documentation forbids that framing.

## Frontend contract gap

`frontend/src/data/blackspots.js` is a hand-authored fixture whose header
states it stands in for a DBSCAN pipeline over Bhubaneswar/Cuttack/Puri. Four
of its fields have no counterpart in the real data:

| Fixture field | Resolution |
|---|---|
| `lastIncident` | **Removed.** No date survives the segment aggregation. Recency was a shelved remediation task. |
| `factors` | **Replaced** by global SHAP from `ml/shap/subcategory_ranking.csv`, labelled as dataset-wide, not per-segment. `police_force` is excluded — it is administrative, not causal. |
| `landmarks` | **Removed.** No gazetteer. `location` ("A23 km 0.5-1.0") is the human-readable handle. |
| `hourlyProfile` | **Replaced** by the segment's real `pct_night`. |
| `fatal`/`serious`/`slight` | Only `n_fatal` and `n_ksi` exist; `n_serious = n_ksi − n_fatal`, and slight is not stored. The severity chart shows fatal/KSI, not a three-way split. |

## Error handling

| Case | Behaviour |
|---|---|
| `ORS_API_KEY` unset | Fail fast at startup, named error. Not a 500 at first request. |
| ORS 429 or 5xx | `503` + "routing temporarily unavailable". Segment endpoints unaffected. |
| ORS returns no route | `422` + "no drivable route between those points". |
| Geocode no match | `200` with an empty candidate list. Not an error. |
| Route has zero blackspots | **A valid, good result.** "No recorded blackspots on this route." Never an error state. |
| Route outside Great Britain | Route returned; `coverageWarning` set to "blackspot data covers Great Britain only". |
| Supabase unreachable | Fail fast at startup. |
| `bbox` malformed, `limit` over cap | `400` naming the offending parameter. |

## Testing

**Backend, JUnit 5.**

- `RouteRiskService` against a fake `RoutingClient` and a stub repository:
  blackspots ordered by distance along route; `expectedKsi` summation;
  label assignment when one route is both fastest and safest; the
  zero-blackspot case returning a valid empty list; `coverageWarning` when
  the route bbox misses Great Britain.
- `SegmentLoader`: `run` parsed from `segment_id`; a malformed id aborts the
  load; `future_*` columns are absent from the insert.
- One Testcontainers PostGIS test for the real `ST_DWithin` + `ST_LineLocatePoint`
  corridor query, since that logic lives in SQL and a stub cannot verify it.
  Docker is available locally.

**Frontend, Vitest.** `scoreToDisplay` boundary cases only — that each cutoff
lands in the intended tier, and that 0 and the maximum do not fall through.
The existing project has no test setup and this design does not build one out
beyond that one module.

## Limitations to state in the report

1. **`blackspot_score` is partly an in-sample prediction.** The pipeline trains
   on 70% of segments and then scores 100% of them, so 77% of the top 500 are
   rows the model memorised. The remediation plan at
   `docs/superpowers/plans/2026-09-01-ml-remediation.md` fixes this and was
   deliberately shelved to ship this feature. The route feature works; the
   ranking beneath it is less trustworthy than it looks.
2. **No exposure normalisation.** Segments rank by expected casualties, not
   casualties per vehicle-km, so 419 of the top 500 fall inside Greater London
   — a traffic-density map as much as a danger map. Route comparisons between
   two London routes are still meaningful; comparisons between London and rural
   routes are not.
3. **The model beats crash-counting by about one point** (50.4% vs 49.35% of
   future KSI captured in the top 20%). Crash history dominates, which is why
   it is the standard blackspot criterion in practice.
4. **Injury collisions only.** STATS19 never records damage-only crashes.
5. **Great Britain only.** No Indian equivalent dataset with this coordinate
   precision and road numbering was available; the method transfers to any
   dataset carrying `(lat, lon, road id, date, severity)`.
