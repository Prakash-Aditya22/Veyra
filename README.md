# Veyra — Blackspot Atlas

**Accident blackspot detection and visualisation for Great Britain.**

Veyra scores every 500 m stretch of numbered road in Great Britain by how many
people it is expected to kill or seriously injure. It puts those scores on an
interactive map and checks a planned journey against them. Commuters can see
which roads on a route have a history of serious crashes. Road-safety
authorities get a ranked, evidence-backed list of where to intervene first.

The scores come from a model trained on the Department for Transport's
**STATS19** records: 1,049,378 police-reported collisions, 2015–2023.

---

## Contents

- [What it does](#what-it-does)
- [How the score works](#how-the-score-works)
- [Results, stated honestly](#results-stated-honestly)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Running it](#running-it)
- [API](#api)
- [Testing](#testing)
- [Known limits](#known-limits)
- [Further reading](#further-reading)
- [Team](#team)
- [Licence and data](#licence-and-data)

---

## What it does

The web app (**Blackspot Atlas**) has five screens:

| Screen | Route | What it shows | Data source |
|---|---|---|---|
| **Overview** | `/` | What the project is, the method and headline numbers | Precomputed `gbStats.json` |
| **Explorer** | `/explorer` | Map of scored segments with filters, a ranked side panel and a permanent legend. Click a segment for its detail (`/explorer?segment=A23_run3_km0.5`) | Live API |
| **Route** | `/route` | Enter a start and destination (geocoded within GB). Up to three candidate routes, each scored by the blackspots within 50 m of its path | Live API + OpenRouteService |
| **Rankings** | `/rankings` | Sortable, searchable table of the top 2,000 evidenced segments | Live API |
| **Statistics** | `/statistics` | Validation results, tier distribution, speed-limit breakdown, weighted factor ranking | Precomputed `gbStats.json` |

Overview and Statistics read a precomputed summary, so they still render when
the backend is down.

## How the score works

A segment's **blackspot score** is a model prediction with one specific
meaning:

> **Expected killed-or-seriously-injured (KSI) casualties on that 500 m over two years.**

- **Segments.** Each road number is first split into geographic stretches,
  because road numbers are not unique (crashes tagged `A503` appear 543 km
  apart). Distance along each stretch (chainage) comes from a minimum spanning
  tree over its own crash points, and is then cut into 500 m blocks. No
  external road geometry is used.
- **Features.** 24 inputs from 2019–2021 crashes on the segment: crash
  history, speed limit, road and junction type, urban/rural, lighting, night
  share, location and extent, and position along the road (the full list is in
  [`ml/README.md`](ml/README.md)).
- **Target.** The segment's KSI count in **2022–2023**, a period the model
  never saw.
- **Model.** LightGBM with a Poisson objective, since the target is a count.
  Segments are split train/test, so reported scores come from road the model
  never trained on.

In the UI, scores map onto four tiers on a 0–100 display scale:

| Tier | Display | Raw score | Colour |
|---|---|---|---|
| Watch | 0–24 | < 0.94 | Orange Yellow |
| Elevated | 25–49 | 0.94–1.57 | Orange Yellow |
| Severe | 50–74 | 1.57–3.09 | Spectrum Red |
| Critical | 75–100 | ≥ 3.09 | Aconite Violet |

These cutoffs are the 50th, 80th and 95th percentiles of the segments the UI
actually shows: those with **at least 6 recorded crashes** (6,213 of 45,014).
They rank segments that have enough evidence to be ranked. They are not
absolute national bands: a "Watch" segment can still sit well above the
national median of 0.25. The cutoffs live only in
[`frontend/src/lib/riskScale.js`](frontend/src/lib/riskScale.js).

## Results, stated honestly

| Measure | Result |
|---|---|
| Blackspot model, top 20% of segments | captures **50.4%** of future KSI |
| Ranking by raw crash count, same 20% | captures **49.35%** |
| Severity model, deployable (24 features) | ROC-AUC **0.658** |
| Severity model, explanatory (236 features) | ROC-AUC 0.765 — *not deployable* |

- **The model beats simple crash counting by about one point.** Crash history
  dominates, which is why it is the standard blackspot criterion in practice.
  The model refines that ranking rather than replacing it.
- **86% of segments rest on fewer than six crashes**, and their scores are
  noisy. That is why everything user-facing filters to `n_crashes >= 6`.
- **The explanatory severity model is not deployable.** It uses facts that
  only exist after a crash, such as casualty ages and point of impact.
  The deployable model is the honest one, and it is weak. Nothing in the app
  presents a "predicted severity".
- `ml/archive/` keeps the negative results: SVMs and neural nets losing to
  gradient boosting, a 2×2 feature ablation, and an evaluation-protocol
  experiment where the same model scored 0.379 or 0.729 depending on whether
  class balancing came before or after the train/test split.

## Architecture

```
 DfT STATS19 CSVs (collision, vehicle, casualty)
            │
            ▼
 ┌─────────────────────────────┐
 │ ml/  (Python, offline)      │  build_recent.py → road_segments.py
 │ segments, scores, SHAP      │  → severity_final.py → severity_deployable.py
 └──────────────┬──────────────┘
                │ data/road_segments_ranked.csv  (45,014 rows, committed)
                ▼
 ┌─────────────────────────────┐        ┌──────────────────────┐
 │ PostgreSQL + PostGIS        │        │ OpenRouteService     │
 │ (Supabase)                  │        │ directions + geocode │
 └──────────────┬──────────────┘        └──────────┬───────────┘
                │ JDBC                             │ HTTPS (key server-side)
                ▼                                  ▼
 ┌────────────────────────────────────────────────────────────┐
 │ backend/  Spring Boot 3.4, Java 21         :8081           │
 │ /api/segments  /api/route/risk  /api/geocode  /api/health  │
 └──────────────────────────────┬─────────────────────────────┘
                                │ JSON
                                ▼
 ┌────────────────────────────────────────────────────────────┐
 │ frontend/  React 18 + Vite, Leaflet, Recharts    :5173     │
 │ Overview · Explorer · Route · Rankings · Statistics        │
 └────────────────────────────────────────────────────────────┘
```

The browser only ever talks to the backend. Routing and geocoding go through
it, so the OpenRouteService key never reaches the client.

| Layer | Stack |
|---|---|
| ML | Python 3.10+, pandas, NumPy, scikit-learn, LightGBM, SHAP, SciPy, joblib, PyArrow |
| Backend | Java 21, Spring Boot 3.4 (Web, JDBC), Maven wrapper |
| Database | PostgreSQL with PostGIS, hosted on Supabase |
| Routing | OpenRouteService (directions with alternatives, geocoding) |
| Frontend | React 18, Vite 6, React Router 6, Leaflet + react-leaflet + leaflet.heat, Recharts, Motion, GSAP, OGL, Phosphor icons |
| Tests | JUnit 5 + Spring MockMvc / MockRestServiceServer; Vitest |

## Repository layout

```
Veyra/
├── backend/                  Spring Boot API
│   ├── src/main/java/com/veyra/blackspot/
│   │   ├── web/              controllers, request types, error mapping
│   │   ├── service/          RouteRiskService: scores routes against segments
│   │   ├── routing/          OpenRouteService client
│   │   ├── repo/             PostGIS queries (segments, bounding boxes)
│   │   ├── load/             CSV → database loader (--load-data)
│   │   ├── domain/           records: Segment, RouteRisk
│   │   └── config/           ORS properties, CORS
│   ├── src/main/resources/   application.yml, schema.sql
│   └── .env.example          DATABASE_URL, ORS_API_KEY
├── frontend/                 React app ("Blackspot Atlas")
│   ├── src/routes/           the five screens
│   ├── src/components/       map, panels, legend, charts, motion helpers
│   ├── src/lib/              API client, risk tiers, geo helpers (+ tests)
│   ├── src/data/gbStats.json precomputed summary for Overview/Statistics
│   ├── src/styles/           tokens.css (design tokens), global.css
│   └── DESIGN.md             design system: single source of truth for the UI
├── ml/                       offline pipeline
│   ├── build_recent.py  road_segments.py  severity_final.py  severity_deployable.py
│   ├── build_stats_summary.py   regenerates frontend/src/data/gbStats.json
│   ├── models/  shap/  reports/   severity models, SHAP tables, full run logs
│   ├── demo/blackspot_map.html    standalone map, no server needed
│   └── archive/                   superseded experiments, kept for the record
├── data/                     road_segments_ranked.csv (+ top-500 JSON, metadata)
└── docs/                     design spec, implementation plans, decision record
```

## Running it

The committed CSV is enough to run the whole stack. You only need the ML
pipeline to regenerate the data.

### Prerequisites

- **Java 21+** (JDK 22 works; the build targets 21)
- **Node.js 20+**
- A **Supabase** project (Postgres + PostGIS)
- An **OpenRouteService** API key. It's free at
  <https://openrouteservice.org/dev/#/signup>. The free tier allows
  **200 directions requests per day**, so use it deliberately before a demo.

`JAVA_HOME` must be set, or the Maven wrapper refuses to start:

```bash
export JAVA_HOME="/c/Program Files/Java/jdk-22"
```

```powershell
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-22'
```

### 1. Configure

Copy `backend/.env.example` to `backend/.env` and fill in `DATABASE_URL` and
`ORS_API_KEY`. `.env` is gitignored.

Spring Boot does not read `.env` itself, so export it into the shell first.
**Don't `source` it.** The `&` in `DATABASE_URL` gets parsed as a shell
operator. Load it one line at a time, splitting on the first `=` only, from
`backend/`:

```bash
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%$'\r'}"
  case "$line" in ''|'#'*) continue ;; esac
  export "${line%%=*}=${line#*=}"
done < .env
```

```powershell
Get-Content .env | Where-Object { $_ -match '^\s*[^#\s]' } | ForEach-Object {
  $k, $v = $_ -split '=', 2
  Set-Item -Path "Env:$($k.Trim())" -Value $v
}
```

[`backend/README.md`](backend/README.md#configure) explains why the simpler
loaders silently corrupt one value or the other.

### 2. Create the schema (once)

Paste [`backend/src/main/resources/schema.sql`](backend/src/main/resources/schema.sql)
into the Supabase SQL editor and run it. It starts with `DROP TABLE IF EXISTS`,
so re-running it wipes the table.

### 3. Load the data

From `backend/`:

```bash
./mvnw spring-boot:run -Dspring-boot.run.arguments=--load-data
```

This loads all 45,014 segments. It truncates the table first, so it's safe to
re-run after a data refresh.

### 4. Start the backend

From `backend/`, with the environment loaded:

```bash
./mvnw spring-boot:run
```

It serves on **`http://localhost:8081`**, not 8080, because Oracle's TNS
Listener occupies 8080 on the development machine. Check it with
`curl localhost:8081/api/health`.

### 5. Start the frontend

From `frontend/`:

```bash
npm install
```

```bash
npm run dev
```

Open **`http://localhost:5173`**. The API base URL comes from
`frontend/.env.development` (`VITE_API_BASE=http://localhost:8081`).

### Regenerating the data (optional)

The ML pipeline needs Python 3.10+ and three DfT STATS19 CSVs (collision,
vehicle, casualty). Download them manually from
`data.dft.gov.uk/road-accidents-safety-data/` into `ml/stats19_raw/`. They are
not shipped. Then, from `ml/`:

```bash
pip install -r requirements.txt
```

```bash
python build_recent.py && python road_segments.py && python severity_final.py && python severity_deployable.py
```

The steps take about 30, 15, 20 and 10 minutes, and none needs internet.
Afterwards, rebuild the frontend summary with `python build_stats_summary.py`,
then re-run step 3 to load the new CSV. [`ml/README.md`](ml/README.md) and
[`CLAUDE.md`](CLAUDE.md) document the data traps the pipeline guards against
(severity label drift, target leakage, non-unique road numbers, silently
truncated downloads).

For a look at the results without any setup, open
[`ml/demo/blackspot_map.html`](ml/demo/blackspot_map.html) in a browser.

## API

All endpoints are served by the backend on port 8081. Errors return JSON
`{"message": "..."}`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness: `{"status":"ok"}` |
| `GET` | `/api/segments` | Scored segments, highest score first |
| `GET` | `/api/segments/{segmentId}` | One segment, e.g. `A23_run3_km0.5` (404 if unknown) |
| `GET` | `/api/geocode?q=Camden` | Up to 5 place candidates within Great Britain |
| `POST` | `/api/route/risk` | Candidate routes between two points, each scored |

**`GET /api/segments`** query parameters:

| Parameter | Default | Notes |
|---|---|---|
| `bbox` | none | `minLon,minLat,maxLon,maxLat`. Omit for the national top list |
| `minScore` | `0` | Minimum blackspot score |
| `minCrashes` | `6` | Minimum recorded crashes, must be ≥ 1 |
| `limit` | `500` | 1–2,000 |

**`POST /api/route/risk`** body (coordinates are `[lon, lat]`, as in GeoJSON):

```json
{ "from": [-0.0982, 51.3762], "to": [-0.1426, 51.5390], "minCrashes": 6, "corridorMetres": 50 }
```

`minCrashes` and `corridorMetres` (10–500) are optional. The response holds
up to three `routes`. Each has a `label` ("Fastest and safest", "Alternative"),
`distanceMetres`, `durationSeconds`, `expectedKsi` (the sum of segment scores
along the route), `blackspotCount`, `worstSegmentId` and its blackspots in
travel order. There is also an optional `coverageWarning`. Status codes:
`422` when no drivable route exists, `503` when OpenRouteService is
unavailable.

## Testing

```bash
cd backend && ./mvnw test                     # 64 tests, no database or network
```

```bash
cd backend && ./mvnw test -Dgroups=postgis    # adds live PostGIS tests, needs DATABASE_URL
```

```bash
cd frontend && npm test                       # 16 Vitest tests: risk tiers, coordinate handling
```

The backend unit tests cover the controllers, the route-risk service, the CSV
loader and the OpenRouteService client. The client is tested against a mock
server, so the tests use no API key and no quota.

## Known limits

- **Evidence, not prediction of individual journeys.** Route risk adds up
  expected KSI across a corridor over two years, across all traffic. It is not
  the risk of one trip.
- **Numbered roads only.** Segments come from crashes tagged with a road
  number. Unclassified roads are not scored.
- **No crash-level breakdowns in the UI.** The 581 MB crash file isn't
  shipped, so Statistics can't break results down by month, hour or year.
- **Long routes get one candidate.** OpenRouteService only computes
  alternatives for trips up to 100 km. Longer trips fall back to the single
  best route.
- **Rankings shows the top 2,000** evidenced segments, the API's per-request
  cap.
- **API quota.** The free OpenRouteService tier allows 200 directions requests
  per day.

## Further reading

| Document | What's in it |
|---|---|
| [`frontend/DESIGN.md`](frontend/DESIGN.md) | The design system: palette, type, components, layout, motion, copy rules |
| [`frontend/README.md`](frontend/README.md) | Frontend screens, data sources, hero animation |
| [`backend/README.md`](backend/README.md) | Backend setup in detail, including the `.env` loader |
| [`ml/README.md`](ml/README.md) | The ML pipeline, features, colour bands, outputs |
| [`CLAUDE.md`](CLAUDE.md) | Data-source traps and modelling decisions |
| [`docs/route-risk-decision-record.md`](docs/route-risk-decision-record.md) | Why route risk works the way it does |
| [`docs/superpowers/`](docs/superpowers/) | Design spec and implementation plans |

## Team

| Name | Role |
|---|---|
| TBD | ML/Data Lead |
| TBD | Backend Lead |
| TBD | Frontend Lead |
| TBD | Integration/Docs Lead |

## Licence and data

The project's own code licence has not been chosen yet.

Crash data: **STATS19**, Department for Transport, published under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Map tiles © Esri, HERE, Garmin and © OpenStreetMap contributors. Routing and
geocoding by [OpenRouteService](https://openrouteservice.org).
