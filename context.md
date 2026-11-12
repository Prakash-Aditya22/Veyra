# Veyra (Blackspot Atlas): full project context

> **Instructions for the AI reading this file.**
> This document is the complete briefing on a university group project prepared
> for a graded course (report, demo and viva). Use it to explain any part of the
> project, from the one-line pitch down to individual functions, SQL queries,
> model settings and design decisions.
>
> Rules for answering:
> 1. **Answer from this document.** Every number here was taken from the code,
>    the logged model output or the project's own decision records. Do not
>    invent figures, team members, dates or features.
> 2. **If something is not covered here, say so** ("that isn't in the project
>    context") rather than guessing.
> 3. **Keep the project's honesty rules** (section 14). In particular: the
>    blackspot score is a *prediction of expected casualties*, not a recorded
>    count and not the risk of one journey. The severity model is weak and
>    nothing in the app is called "predicted severity". The model beats simple
>    crash counting by only about one percentage point. Examiners reward
>    students who state limits plainly.
> 4. Pitch the answer to the question: a short plain-English answer for
>    general questions, and exact detail (file, function, parameter, number) for
>    technical ones.

---

## Table of contents

1. [The project in one paragraph](#1-the-project-in-one-paragraph)
2. [Problem statement, objectives and scope](#2-problem-statement-objectives-and-scope)
3. [History: how the project got its current shape](#3-history-how-the-project-got-its-current-shape)
4. [System architecture](#4-system-architecture)
5. [The data: STATS19](#5-the-data-stats19)
6. [ML pipeline: blackspot scoring](#6-ml-pipeline-blackspot-scoring)
7. [ML pipeline: severity models and SHAP](#7-ml-pipeline-severity-models-and-shap)
8. [Database: PostgreSQL + PostGIS](#8-database-postgresql--postgis)
9. [Backend: Spring Boot API](#9-backend-spring-boot-api)
10. [Frontend: React app "Blackspot Atlas"](#10-frontend-react-app-blackspot-atlas)
11. [Design system and theme](#11-design-system-and-theme)
12. [End-to-end walkthroughs](#12-end-to-end-walkthroughs)
13. [Results and verification](#13-results-and-verification)
14. [Honesty constraints](#14-honesty-constraints)
15. [Engineering decisions and defects found](#15-engineering-decisions-and-defects-found)
16. [Limitations and future work](#16-limitations-and-future-work)
17. [Running and testing](#17-running-and-testing)
18. [Repository and file map](#18-repository-and-file-map)
19. [Glossary](#19-glossary)
20. [Likely viva questions with model answers](#20-likely-viva-questions-with-model-answers)

---

## 1. The project in one paragraph

**Veyra** (the web app is branded **Blackspot Atlas**) detects and visualises
road-accident **blackspots** in **Great Britain**. An offline Python pipeline
takes the UK Department for Transport's **STATS19** police collision records
(1,049,378 collisions, 2015–2023), cuts every numbered road into **500 m
segments** measured along the road, and trains a **LightGBM Poisson regression**
that predicts, for each segment, the **expected number of people killed or
seriously injured (KSI) on it over two years**. The 45,014 scored segments are
loaded into **PostgreSQL + PostGIS** (hosted on Supabase) and served by a
**Spring Boot (Java 21) REST API**. A **React 18 + Vite + Leaflet** front end shows
them on a map, ranks them in a table, summarises the statistics, and, using
**OpenRouteService** for routing, compares up to three candidate routes between
two places by the expected KSI along each one.

**Who it is for:** commuters (choose a route with less blackspot exposure) and
road-safety authorities (a ranked, evidence-backed list of where to intervene).

---

## 2. Problem statement, objectives and scope

**Problem.** Road crashes cluster at particular stretches of road because of
layout, speed, junctions, lighting and traffic. The raw records exist, but
there is no easy way for a commuter or an authority to see *where* the dangerous
stretches are, how dangerous they are relative to each other, or how a planned
journey passes through them.

**Objectives.**
1. Turn point-level crash records into **road-level units** (500 m segments)
   that a highway engineer would recognise ("A38, km 128.0–128.5").
2. Score each segment with a model that is **validated on future data**
   (trained on 2019–2021 features, tested on 2022–2023 outcomes).
3. **Explain** which conditions are associated with severe crashes (SHAP).
4. Build a full-stack web app: an interactive map, rankings, statistics and a
   **route risk check**.
5. Be **honest about what the model can and cannot claim**.

**Scope.**
- Great Britain only (England, Scotland, Wales), numbered roads only (M, A(M),
  A, B, C roads).
- Injury collisions only. STATS19 does not record damage-only crashes.
- Scores are precomputed offline. The app is not real-time.

---

## 3. History: how the project got its current shape

This history explains several design choices and is useful viva material.

- The project started as three disconnected pieces on three git branches:
  - `ML`: a finished Python pipeline and 45,014 scored GB road segments.
  - `frontend-v1`: a working React/Leaflet app built against a **made-up
    fixture for an Indian corridor** (Bhubaneswar / Cuttack / Puri) and a
    planned DBSCAN-clustering pipeline that was never built.
  - `main`: only a README.
- Their data contracts did not match. The UI wanted a 0–100 "composite score",
  incident dates and per-blackspot factors. The ML output had expected KSI on a
  0–9.67 scale, crash counts, and no dates. **There was no backend at all.**
- **Decision:** keep the British data (no Indian dataset with comparable
  coordinate precision and road numbering was available), re-theme the
  frontend onto GB data, and write the Spring Boot backend from scratch. The
  method itself transfers to any dataset with `(lat, lon, road id, date,
  severity)`.
- A leftover of the Indian framing: the pipeline's severity labels are
  **Fatal / Grievous / Minor** (Indian MoRTH terms) instead of the UK's
  **Fatal / Serious / Slight**. They mean the same: Grievous = Serious,
  Minor = Slight.
- Branches today: `final` holds the complete, current project (and is what
  should be demonstrated). `integration` is the earlier merge point.
  `ml-remediation` holds an unfinished plan to fix the in-sample scoring issue
  (section 16). `main` on GitHub holds only the project README.
- Repository: `github.com/Prakash-Aditya22/Veyra`.

---

## 4. System architecture

```
 DfT STATS19 CSVs (collision, vehicle, casualty)  -- downloaded manually
            |
            v
 ml/ (Python, offline, run once)
   build_recent.py      -> stats19_recent.csv (merged 2015-2023, leakage removed)
   road_segments.py     -> data/road_segments_ranked.csv (45,014 scored segments)
   severity_final.py    -> severity models, SHAP tables
   severity_deployable.py -> deployable vs explanatory comparison
   build_stats_summary.py -> frontend/src/data/gbStats.json
            |
            v  (CSV loaded once with `--load-data`)
 PostgreSQL + PostGIS on Supabase  (table road_segment, GIST spatial index)
            |  JDBC
            v
 backend/ Spring Boot 3.4, Java 21, port 8081  <---->  OpenRouteService
   GET  /api/health                                   (directions + geocoding,
   GET  /api/segments, /api/segments/{id}              key kept server-side)
   GET  /api/geocode
   POST /api/route/risk
            |  JSON over HTTP (CORS allows localhost:5173)
            v
 frontend/ React 18 + Vite, port 5173
   Overview  Explorer  Route  Rankings  Statistics
```

**Key architectural points:**
- **Offline ML, online serving.** Training is slow (tens of minutes) and the
  data is historical, so scores are computed once and stored. The API never
  runs a model at request time.
- **The browser only talks to our backend.** Routing and geocoding are proxied
  through Spring Boot so the OpenRouteService API key never reaches the client.
- **Spatial work happens in the database.** "Which segments lie within 50 m of
  this route, in travel order?" is one PostGIS query.
- **Two screens (Overview, Statistics) read a precomputed JSON summary**, so
  they work even when the backend or database is down.

**Technology stack:**

| Layer | Technologies |
|---|---|
| ML | Python 3.10+, pandas, NumPy, SciPy (sparse graphs, MST, Dijkstra), scikit-learn (kNN, train/test split, metrics), LightGBM, SHAP, joblib, PyArrow |
| Database | PostgreSQL + PostGIS extension, hosted on Supabase |
| Backend | Java 21, Spring Boot 3.4.1 (spring-boot-starter-web, -jdbc, -validation), PostgreSQL JDBC driver, Maven wrapper |
| External API | OpenRouteService (directions with alternative routes, geocoding) |
| Frontend | React 18, Vite 6, React Router 6, Leaflet 1.9 + react-leaflet 4 + leaflet.heat, Recharts 2, Motion 11 (animation), GSAP 3 + ScrollTrigger (landing scroll), OGL (WebGL background), Phosphor icons |
| Tests | JUnit 5, Spring MockMvc, MockRestServiceServer, AssertJ (backend); Vitest (frontend) |
| Map tiles | Esri World Dark Gray Canvas (no API key needed) |

---

## 5. The data: STATS19

**Source.** UK Department for Transport, "Road Safety Data" (STATS19),
`data.dft.gov.uk/road-accidents-safety-data/`, published under the **Open
Government Licence v3.0**. Police record every reported road collision that
causes personal injury.

**Three linked tables**, joined on `collision_index`:
- **collision**: one row per crash: date, time, location (lat/long), road
  class and number, speed limit, junction details, light, weather, road
  surface, urban/rural, police force, severity.
- **vehicle**: one row per vehicle: type, manoeuvre, point of impact, driver
  details.
- **casualty**: one row per injured person: severity, age, class
  (driver/passenger/pedestrian).

All fields are **numerically coded** (for example light condition 1 = daylight).

**Volume used.** 1,049,378 collisions, 2015–2023 (`build_recent.py` output,
`stats19_recent.csv`, 581 MB, not in git). The raw downloads are gitignored and
must be fetched manually into `ml/stats19_raw/`.

**Severity.** Each collision is Fatal, Serious or Slight (labelled Fatal /
Grievous / Minor in the pipeline). **KSI** = Killed or Seriously Injured =
Fatal + Serious. KSI is the standard UK road-safety measure.

### Four data traps the pipeline guards against

1. **Severity labels drift.** The share of "serious" crashes rose from 14.3% to
   22.5% between 2015 and 2023 because police forces switched, force by force,
   to injury-based reporting systems (CRASH/COPA). It never settles. A model
   trained across the change learns *which reporting system a force used*, not
   what makes a crash severe. **Fix:** the severity models use 2022–2023 only
   (22.01% and 22.48%, adjacent and stable, still 210,262 collisions). Fatal
   counts are stable throughout, and crash *locations* are unaffected, so the
   blackspot work can use more years.
2. **Target leakage across ten fields.** `collision_severity` is the target,
   but nine other fields encode the same answer: `casualty_severity`,
   `enhanced_casualty_severity`, `casualty_injury_based`,
   `casualty_adjusted_severity_serious`, `casualty_adjusted_severity_slight`,
   `enhanced_severity_collision`, `collision_injury_based`,
   `collision_adjusted_severity_serious`, `collision_adjusted_severity_slight`.
   They are listed in `LEAKY` in `build_recent.py`, dropped, and an `assert`
   proves none survived the merge. `did_police_officer_attend_scene_of_accident`
   is also dropped, because attendance is a *response* to severity.
3. **Road numbers are not geographically unique.** Crashes tagged `A503`
   appear from London to Scotland, 543 km apart, though the real A503 is a
   10 km London road (numbers are reused or misrecorded). Treating one number
   as one road gave 576 km of chainage on a 10 km road (57× too long). **Fix:**
   split each road number into separate geographic "stretches" first (section 6).
4. **Large downloads truncate silently.** A collision-table download once
   stopped at 1.4 GB of 1.5 GB and still parsed as a valid CSV. **Fix:** check
   that the last line has the full field count before trusting a download.

**COVID note.** Traffic collapsed in 2020–2021. Crash locations stay valid but
counts drop, which `build_recent.py` flags rather than hiding.

---

## 6. ML pipeline: blackspot scoring

File: `ml/road_segments.py`. Runtime about 15 minutes. Reads
`stats19_recent.csv`, writes `road_segments_ranked.csv` and
`road_segments_top500.json` (both copied into `data/`).

### 6.1 Why segments along the road, not a grid or clusters

An earlier version used a 500 m × 500 m grid. A grid square can contain two
different roads, ignores the road's direction, and its label ("cell
-13_11468") means nothing to an engineer. What the project needs is
**chainage**: distance measured *along* the road, so a blackspot can be stated
as "A38, km 128.0–128.5". DBSCAN clustering was in the original plan but was
never used; segments are more interpretable and give fixed-size units that can
be compared fairly.

### 6.2 Step by step

1. **Filter.** Keep crashes from 2019–2023 with valid coordinates, on numbered
   roads (`first_road_class` 1–6 and `first_road_number > 0`). Build a road id
   from class + number: class 1 = M, 2 = A(M), 3 = A, 4 = B, 5 = C,
   6 = U (unclassified). So class 3, number 38 is `A38`. This is a true
   identifier: no fuzzy string matching of road names.
2. **Keep roads with enough data.** Only roads with at least `MIN_CRASHES = 60`
   crashes can support a chainage estimate.
3. **Split each road number into stretches.** Project lat/long to metres. Build
   a k-nearest-neighbour graph (k = 10) over the road's crash points, dropping
   any edge longer than `STRETCH_GAP_M = 10,000 m`. Each connected component is a
   separate stretch (the `run` number). This fixes the A503 problem.
4. **Chainage within a stretch, via a minimum spanning tree (MST).** The
   crashes themselves trace the road, because no road geometry library (osmnx,
   shapely) is used.
   - Build the **MST** over the stretch's crash points: exact, from the full
     distance matrix, for up to 4,000 points; for busier roads, an MST over a
     k = 15 nearest-neighbour graph, with any disconnected pieces stitched at
     their closest pair of points.
   - Why an MST: it is **connected by construction**, and because it always
     joins nearest points it follows the road's curve instead of cutting
     across it. An earlier plain kNN-graph version fragmented: the A23 broke
     into 52 pieces, each restarting at "km 0".
   - Find the stretch's two ends by a **double sweep**: the farthest node from
     an arbitrary start is one end; the farthest node from *that* is the other
     (the tree's diameter). Shortest-path (Dijkstra) distance from that end is
     the chainage.
   - This approximates the centreline from crash positions. It is honest to
     call it an approximation.
5. **Cut into 500 m segments** (`SEG_M = 500`): `seg_km = floor(chainage/500) × 0.5`.
   Segment id format: `<road>_run<n>_km<start>`, for example `A23_run3_km0.5`
   (the A23, stretch 3, km 0.5–1.0).
6. **Build features from 2019–2021 crashes** (the "build" window). One row per
   segment that had at least one crash in those years: **45,014 segments**.
7. **Build the target from 2022–2023 crashes** (the "future" window):
   `future_ksi` = KSI crashes on that segment in 2022–2023 (0 if none).
8. **Split segments 70/30** (`train_test_split`, `test_size = 0.3`,
   `random_state = 42`).
9. **Train** `LGBMRegressor(objective="poisson", n_estimators=500,
   num_leaves=63, learning_rate=0.05, min_child_samples=30,
   colsample_bytree=0.7, reg_lambda=1.0, random_state=42)` on the training
   segments, predicting `future_ksi`.
10. **Score every segment**: `blackspot_score = model.predict(X)`, then rank
    1..45,014 by score.
11. **Validate** on the 30% held-out segments (section 13).

### 6.3 The 24 model features

All computed from that segment's 2019–2021 crashes. The code uses every
segment column except the id and target columns, which gives **24**. (Older
versions of the READMEs said 18; that was corrected.)

| Group | Features |
|---|---|
| Crash history | `n_crashes`, `n_ksi`, `n_fatal`, `crashes_per_year` (= n_crashes / 3), `ksi_rate` (= n_ksi / n_crashes), `n_years` (distinct years with a crash) |
| Road | `speed_max`, `speed_mean`, `mode_road_type`, `mode_junction_detail`, `pct_junction` (share of crashes at a junction) |
| Context | `mode_urban_or_rural_area`, `mode_light_conditions`, `pct_night` (share between 22:00 and 05:59) |
| Crash shape | `n_veh_mean`, `n_cas_mean` (mean vehicles and casualties per crash) |
| Location | `lat`, `lon` (mean), `lat_min`, `lat_max`, `lon_min`, `lon_max` (the segment's extent) |
| Position on road | `run` (stretch number), `km_from` (chainage of the segment start) |

`mode_*` = the most common category among the segment's crashes.

### 6.4 Why a Poisson objective

The target is a **count** (number of KSI casualties), mostly 0, 1 or 2, with a
long tail, and its variance grows with its mean. Squared-error regression would
treat a miss of 0 vs 2 the same as 20 vs 22. Poisson regression models counts
directly, and its prediction is an *expected count*, which is exactly what the
score is defined to mean.

### 6.5 Why LightGBM

Gradient-boosted trees handle mixed numeric and categorical features, non-linear
effects and interactions without manual feature engineering, and train fast on
tabular data. Experiments archived in `ml/archive/` show SVMs and neural
networks losing to gradient boosting on this data.

### 6.6 Outputs

`data/road_segments_ranked.csv`, 45,014 rows, columns: `rank, segment_id,
location, road_id, km_from, km_to, lat, lon, blackspot_score, n_crashes, n_ksi,
n_fatal, ksi_rate, crashes_per_year, speed_max, pct_night, pct_junction,
future_ksi, future_fatal`. `location` is human-readable, for example
`A23 km 0.5-1.0 (seg 3)`. The `future_*` columns are the validation answer and
**are never loaded into the database** (section 8).

**Score scale:** 0 to 9.67. National median 0.25, 90th percentile about 0.81.
The top segment is `A23_run3_km0.5` (A23, south London, score 9.67, 60 crashes,
10 KSI, 0 fatal, 30 mph, 70% at junctions).

**Evidence:** 86% of segments rest on fewer than 6 crashes. Only **6,213**
segments have 6 or more. The app shows only those by default.

---

## 7. ML pipeline: severity models and SHAP

The severity models are a **secondary deliverable**. They answer "what
conditions are associated with a crash being severe?", not "where are the
blackspots?".

### 7.1 `severity_final.py` (about 20 min)

- **Window:** 2022–2023 only (210,262 collisions, 236 features) because of
  label drift (section 5).
- **Split:** 80/20, stratified by severity class, `random_state = 42`.
- **Model:** `LGBMClassifier(n_estimators=600, num_leaves=127,
  learning_rate=0.05, min_child_samples=40, ...)`.
- **KSI binary model** (KSI vs Slight, 23.7% positive):
  ROC-AUC **0.769**, PR-AUC 0.517 against a no-skill baseline of 0.237
  (lift 2.18), at a decision threshold of 0.33 chosen **on training data only**:
  precision 0.485, recall 0.513, F1 0.499.
- **Three-class model** (Fatal / Serious / Slight): accuracy 0.759, macro-F1
  0.475. Per-class multipliers (Fatal ×2.75, Serious ×1.75) were tuned on
  training predictions and then frozen, to counter class imbalance. Average
  precision: Fatal 0.18, Serious 0.44, Slight 0.91.
- **SHAP** values via `shap.TreeExplainer`: global importance, plus per-level
  ("sub-category") SHAP for every categorical feature.

### 7.2 Deployable vs explanatory (`severity_deployable.py`, about 10 min)

The 236-feature model scores well, but many features are only known **after** a
crash has been investigated: casualty ages, whether a pedestrian was struck,
first point of impact, vehicle manoeuvre. A live service could never have them.
So two models are trained on the **same rows and split**:

| Model | Features | ROC-AUC | PR-AUC | Notes |
|---|---|---|---|---|
| **Deployable** | 24 (road layout, speed limit, junction, weather, light, surface, time, location) | **0.658** | 0.362 | The honest number for any live use. Top 1% of predictions: KSI rate 56%, lift 2.37 |
| Explanatory | 236 (everything, including post-crash detail) | 0.765 | 0.510 | Useful for explaining past crashes, useless for prediction |

The gap between them is "the honest cost of deployability". The deployable
model is a **weak predictor**, so **the app never shows a "predicted severity"**.
(The explanatory model scores 0.769 in `severity_final.py` and 0.765 in this
comparison run. The small difference comes from the two separate training runs.)

### 7.3 SHAP: rank by spread, not mean |SHAP|

The usual ranking, mean absolute SHAP, put a **98%-missing column first**. Its
one giant "unknown" level shifted every prediction by the same amount: high
mean |SHAP|, zero ability to tell crashes apart. The pipeline instead ranks
categorical features by **between-level spread**: the weighted standard
deviation of the mean SHAP value across the feature's levels, meaning how much
the prediction moves when the level changes. `police_force` scores high on
spread but reflects **recording differences between forces**, not real risk,
so it is excluded from anything presented as a cause.

**Factor ranking shown on the Statistics screen** (share relative to the top
factor):

| Factor | Share | Highest-risk level | Lowest-risk level |
|---|---|---|---|
| Speed limit | 100 | 50 mph | 20 mph |
| Urban or rural | 43 | Rural | Urban |
| Light conditions | 41 | Dark, no lighting | Daylight |
| Weather | 36 | Fine | Rain and wind |
| Road type | 30 | Single carriageway | Roundabout |
| Junction control | 29 | Traffic signals | Give way or uncontrolled |
| Day of week | 26 | Saturday | Tuesday |
| Road surface | 20 | Dry | Frost/ice |
| Junction layout | 10 | (not labelled) | (not labelled) |
| Road class | 7 | A road | C road |

Interpretation caution: "Fine weather" ranking above rain is a classic
**confounder**. Fine weather brings higher speeds and more vulnerable road users
(motorcyclists, cyclists), and drivers slow down in rain. SHAP shows
association with severity, not causation.

### 7.4 `ml/archive/`: negative results kept on purpose

- A hierarchical severity **cascade**, superseded by simple threshold tuning.
- **SVM and neural networks** lost to gradient boosting.
- A **2×2 feature ablation**.
- An **evaluation-protocol experiment**: the same model scored **0.379 or
  0.729** depending on whether class balancing was applied before or after the
  train/test split. Balancing before the split leaks duplicated rows into the
  test set and inflates the score. This is a good viva example of why
  evaluation protocol matters.

### 7.5 `build_stats_summary.py`

Generates `frontend/src/data/gbStats.json`, read by the Overview and Statistics
screens. Totals: 145,634 crashes, 30,427 KSI and 2,509 fatal on scored segments
(2019–2021), 45,014 segments, 6,213 evidenced segments, 1,027 roads. It also
contains the validation table, the evidenced score distribution, KSI share by
speed limit, top roads, SHAP factors, severity model metrics and the top
segments.

**KSI share by speed limit** (share of crashes that were KSI): 20 mph 17.8%,
30 mph 18.5%, 40 mph 19.8%, 50 mph 19.9%, **60 mph 30.3%** (highest; mostly rural
single carriageways), 70 mph 21.3% (motorways and dual carriageways, which are
safer per crash).

**Top roads by KSI (2019–2021, scored segments):** A259 (340 KSI), A38 (319),
A6 (313), A3 (298), A23 (296).

---

## 8. Database: PostgreSQL + PostGIS

Hosted on **Supabase**. The schema is in `backend/src/main/resources/schema.sql`,
applied once by hand in the Supabase SQL editor. It starts with
`DROP TABLE IF EXISTS`, so re-running it wipes the table.

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE road_segment (
  segment_id TEXT PRIMARY KEY, road_id TEXT NOT NULL, run INTEGER NOT NULL,
  location TEXT NOT NULL, km_from DOUBLE PRECISION, km_to DOUBLE PRECISION,
  geom GEOGRAPHY(POINT,4326) NOT NULL,
  blackspot_score DOUBLE PRECISION NOT NULL, rank INTEGER NOT NULL,
  n_crashes INTEGER NOT NULL, n_ksi INTEGER NOT NULL, n_fatal INTEGER NOT NULL,
  ksi_rate, crashes_per_year, speed_max, pct_night, pct_junction  -- DOUBLE PRECISION
);
CREATE INDEX idx_seg_geom  ON road_segment USING GIST (geom);
CREATE INDEX idx_seg_score ON road_segment (blackspot_score DESC);
CREATE INDEX idx_seg_road  ON road_segment (road_id, run, km_from);
```

- **`GEOGRAPHY(POINT, 4326)`**: each segment is stored as one point (the mean
  position of its crashes) in WGS84 lat/long (SRID 4326, the GPS system).
  `geography`, not `geometry`, so distances are computed **in metres on the
  Earth's surface**, which is what a "50 m corridor" needs.
- **GIST index** on `geom` makes spatial queries (bounding box, distance) fast.
- **Score index** supports "top N by score". The road index supports ordering
  along a road.
- **No `future_ksi` / `future_fatal` columns, by design.** They are the
  2022–2023 outcome the model was graded on. Serving them would show the answer.
  The missing column *is* the enforcement, and a backend test asserts the API's
  JSON has exactly 18 named keys, so a leaked column under any name fails the
  build.
- **Row Level Security (RLS)** is enabled. Supabase exposes an auto-generated
  REST API using a public `anon` key that is designed to ship in frontend code.
  Without RLS, anyone with that key could read *and delete* all rows. The
  backend connects as the table owner, which bypasses RLS, so enabling it costs
  nothing.
- 45,014 rows is small. A database is "academically expected rather than
  technically required" (the project says this plainly), but PostGIS gives
  real metre-accurate corridor queries in one statement.

---

## 9. Backend: Spring Boot API

Folder `backend/`, package `com.veyra.blackspot`, Java 21, Spring Boot 3.4.1,
built with the Maven wrapper (`./mvnw`). Runs on **port 8081** because Oracle's
TNS Listener permanently occupies 8080 on the development machine.

### 9.1 Package structure

| Package | Class | Responsibility |
|---|---|---|
| (root) | `BlackspotApplication` | `@SpringBootApplication` entry point |
| `web` | `SegmentController` | `GET /api/segments`, `GET /api/segments/{id}` |
| `web` | `RouteController` | `POST /api/route/risk`, `GET /api/geocode` |
| `web` | `HealthController` | `GET /api/health` returns `{"status":"ok"}` |
| `web` | `RouteRiskRequest` | Request record: `from`, `to` as `[lon, lat]`, optional `minCrashes`, `corridorMetres` |
| `web` | `ApiExceptionHandler` | `@RestControllerAdvice` mapping exceptions to HTTP codes with `{"message": ...}` |
| `service` | `RouteRiskService` | Route → corridor match → aggregate → dedupe → label |
| `routing` | `RoutingClient` (interface), `OrsRoutingClient` | OpenRouteService directions and geocoding |
| `routing` | `RoutingException` | Kinds `NO_ROUTE` and `UNAVAILABLE` |
| `repo` | `SegmentRepository` | All SQL, via `JdbcTemplate` |
| `repo` | `BoundingBox` | Parses `minLon,minLat,maxLon,maxLat` (Leaflet's order) |
| `load` | `SegmentLoader` | `ApplicationRunner`: with `--load-data`, loads the CSV into the database |
| `load` | `SegmentCsvReader`, `SegmentIdParser` | CSV parsing; recovers `run` from ids like `A23_run3_km0.5` with a regex |
| `domain` | `Segment`, `RouteRisk` | Java records (immutable data classes) |
| `config` | `OrsProperties` | `@ConfigurationProperties(prefix="ors")`; fails at startup if the key is missing |
| `config` | `WebConfig` | CORS: allows `GET`/`POST` on `/api/**` from `localhost:5173` and `127.0.0.1:5173` |

Design choices: **plain JDBC (`JdbcTemplate`), not JPA/Hibernate**, because the
queries are PostGIS-specific SQL; **Java records** for immutable DTOs;
**constructor injection** everywhere; the routing client sits behind an
**interface** so tests can mock it.

### 9.2 Configuration (`application.yml`)

```yaml
spring.datasource.url: ${DATABASE_URL:}      # from the environment
ors.api-key: ${ORS_API_KEY:}
ors.base-url: https://api.openrouteservice.org
ors.alternatives: { target-count: 3, share-factor: 0.2, weight-factor: 2.0 }
blackspot: { corridor-metres: 50, min-crashes: 6, max-segments: 2000 }
server.port: 8081
```

Secrets live in `backend/.env` (gitignored), which must be exported into the
shell first, because Spring Boot does not read `.env` files (section 15.4).

### 9.3 Endpoints

| Method and path | Parameters | Returns |
|---|---|---|
| `GET /api/health` | none | `{"status":"ok"}` |
| `GET /api/segments` | `bbox` (optional, `minLon,minLat,maxLon,maxLat`), `minScore` (default 0), `minCrashes` (default 6, must be ≥ 1), `limit` (default 500, 1–2000) | List of segments, highest score first. With `bbox`: those inside the box; without: the national top list |
| `GET /api/segments/{segmentId}` | path id | One segment, or 404 `{"message":"no segment ..."}` |
| `GET /api/geocode?q=Camden` | `q` (required) | Up to 5 `{label, lon, lat}` candidates, restricted to GB (`boundary.country=GB`) |
| `POST /api/route/risk` | JSON `{from:[lon,lat], to:[lon,lat], minCrashes?, corridorMetres? (10–500, default 50)}` | `{routes:[...], coverageWarning}` |

**Segment JSON** (18 keys): `segmentId, roadId, run, location, kmFrom, kmTo,
lat, lon, blackspotScore, rank, nCrashes, nKsi, nFatal, ksiRate,
crashesPerYear, speedMax, pctNight, pctJunction`.

**Route JSON** per route: `index, label, distanceMetres, durationSeconds,
geometry (list of {lon,lat}), expectedKsi, blackspotCount, worstSegmentId,
blackspots[]`. Each blackspot has `segmentId, location, lat, lon,
blackspotScore, nCrashes, nKsi, nFatal, speedMax, metresAlongRoute,
thinlyEvidenced`.

**Error mapping** (`ApiExceptionHandler`): `IllegalArgumentException` → 400;
`NotFoundException` → 404; `RoutingException` `NO_ROUTE` → **422**, and
`UNAVAILABLE` → **503**.

### 9.4 The SQL (`SegmentRepository`)

- **Bounding box:** `WHERE geom && ST_MakeEnvelope(minLon,minLat,maxLon,maxLat,4326)::geography
  AND blackspot_score >= ? AND n_crashes >= ? ORDER BY blackspot_score DESC LIMIT ?`.
  `&&` is a fast index-backed bounding-box overlap test.
- **National top:** the same filters, `ORDER BY rank ASC LIMIT ?`. (There used
  to be an unfiltered version that silently ignored `minCrashes`; it was
  removed.)
- **Corridor query** (the heart of route risk):
  ```sql
  SELECT <cols>, ST_LineLocatePoint(ST_GeomFromText(:route, 4326), geom::geometry) AS frac
  FROM road_segment
  WHERE ST_DWithin(geom, ST_GeomFromText(:route, 4326)::geography, :corridorMetres)
    AND n_crashes >= :minCrashes
  ORDER BY frac
  ```
  `ST_DWithin` on geography = "within N **metres** of the route line".
  `ST_LineLocatePoint` returns the segment's position along the route as a
  fraction from 0 to 1, and ordering by it turns a *set* of segments into a
  *journey* (blackspots in the order a driver meets them). The route is passed
  as WKT `LINESTRING(lon lat, ...)`.
- Coordinates are read back with `ST_Y(geom::geometry)` (lat) and
  `ST_X(geom::geometry)` (lon).

### 9.5 Route risk algorithm (`RouteRiskService.assess`)

1. Ask OpenRouteService for up to **3 routes** (`target-count`) between the two
   points.
2. For each route, run the **corridor query** (segments with ≥ 6 crashes within
   **50 m** of the line, in travel order).
3. **`expectedKsi` = sum of those segments' scores**, rounded to 2 decimals.
   Also record the count, the worst segment, and each blackspot's distance along
   the route (`fraction × route length`).
4. **Drop indistinguishable alternatives.** ORS sometimes returns near-identical
   routes: two Croydon → Camden alternatives came back 17.8 m and 10.3 s apart,
   with different geometries (845 vs 849 points), so an equality check catches
   nothing. A route is dropped only if, compared with one already kept, **both**
   (a) it passes exactly the same blackspots in the same order, **and** (b) its
   distance and duration are within **1%**. Both are required: (a) alone would
   merge two genuinely different routes that each happen to pass no blackspots.
5. **Label across the set:** the quickest is "Fastest", the lowest
   `expectedKsi` is "Safest", one route can be "Fastest and safest", others are
   "Alternative".
6. **Coverage warning** if no route point falls inside a generous GB box
   (lon −8.7 to 2.0, lat 49.8 to 61.0).

`expectedKsi` is the expected KSI casualties on that corridor over two years,
**across all traffic**. It is **not** the risk of one journey, and it grows
with route length (it is an unnormalised sum). The UI says both.

### 9.6 OpenRouteService client (`OrsRoutingClient`)

- **Directions:** `POST /v2/directions/driving-car/geojson` with
  `coordinates` and `alternative_routes {target_count, share_factor: 0.2,
  weight_factor: 2.0}`. `share_factor` is the maximum share of road an
  alternative may share with the best route; `weight_factor` is how much longer
  an alternative may be.
- **Geocoding:** `GET /geocode/search?text=...&boundary.country=GB&size=5`.
  The query is passed as a URI template variable so it is percent-encoded
  ("Trafalgar Square" and "&size=1" are encoded, not injected).
- **The API key is always sent as an `Authorization` header, never in the
  URL**, because URLs end up in logs, debug output and proxy access logs.
- **Timeouts:** 5 s connect, 20 s read. Without them a hung upstream would
  block a servlet thread forever and eventually drain the thread pool.
- **Error handling:**
  - HTTP error with ORS code **2010 or 2009** → `NO_ROUTE` (422: "no drivable
    route between those points"). ORS reports "no route" as a 404 with a
    structured body, not as an empty result.
  - ORS code **2004** (the trip is longer than 100 km, the limit for the
    alternative-routes algorithm) → **retry once asking for a single route**.
    Before this fix, every trip over 100 km (for example Cheltenham → Camden,
    about 150 km) showed "Routing is temporarily unavailable".
  - Anything else → `UNAVAILABLE` (503).
  - The error body is parsed only for `error.code` and is never logged, because
    it may echo request details.

### 9.7 Data loading (`SegmentLoader`)

Run once: `./mvnw spring-boot:run -Dspring-boot.run.arguments=--load-data`
(optionally `--csv=<path>`). It parses `../data/road_segments_ranked.csv`,
`TRUNCATE`s the table, inserts in batches of 1,000 with
`ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography` (longitude first), and
logs the final row count. Because it truncates first, re-running is safe
(idempotent). `SegmentIdParser` recovers `run` from the id with the regex
`^(.+)_run(\d+)_km([0-9]+(?:\.[0-9]+)?)$`. A malformed id throws instead of
defaulting `run` to 0, which would silently merge separate stretches.

### 9.8 Backend tests (64, all passing)

| Test class | Covers |
|---|---|
| `SegmentControllerTest`, `RouteControllerTest`, `HealthControllerTest` | HTTP layer via MockMvc: parameters, validation, status codes, exact JSON key set (leak guard) |
| `RouteRiskServiceTest` (13 tests) | Corridor aggregation, ordering, dedupe of near-identical routes, labelling, coverage warning |
| `OrsRoutingClientTest` | Outgoing requests against `MockRestServiceServer`: URL encoding, key only in header, the 2004 fallback. No network, key or quota |
| `SegmentCsvReaderTest`, `SegmentIdParserTest` | CSV parsing, id regex, including `A1(M)` roads |
| `BoundingBoxTest`, `SegmentTest`, `OrsPropertiesTest` | Value objects and config |
| `SegmentRepositoryPostgisTest` | Live PostGIS queries; only with `-Dgroups=postgis` and a `DATABASE_URL` |

---

## 10. Frontend: React app "Blackspot Atlas"

Folder `frontend/`. React 18 + Vite 6, routing with React Router 6. Dev server
on **port 5173**. The API base URL comes from `VITE_API_BASE` in
`.env.development` (`http://localhost:8081`).

### 10.1 App shell (`App.jsx`)

- `<MotionConfig reducedMotion="user">` makes every Motion animation respect
  the operating-system "reduce motion" setting.
- `ScrollToTop` scrolls to the top on every route change.
- `Nav` (top bar; becomes a sheet menu on mobile), then the routes: `/`,
  `/explorer`, `/route`, `/rankings`, `/statistics`; anything else redirects
  to `/`.

### 10.2 Screens

**Overview / Landing (`/`, `routes/Landing.jsx`).** A centred hero over an
animated **WebGL wave background** (`GradientWaves.jsx`, a raymarched shader
built on OGL, tinted to the theme, skipped entirely under reduced motion), two
capability rows, methodology, metrics and provenance. Scroll motion is
choreographed with **GSAP ScrollTrigger** (`lib/gsapScroll.js`): sections pin
and content slides in. `gsap.context()` scopes and reverts everything on
unmount, so ScrollTrigger instances do not leak across page navigation. Pinned
sections start below the sticky nav (`top {navHeight}px`). This page is a
deliberate exception to the design system's "restrained motion" rule. All
numbers come from `gbStats.json`.

**Explorer (`/explorer`, `routes/Explorer.jsx`).** The primary screen, laid out
as a three-zone grid: a **280 px filter rail**, a **fluid map**, and a **380 px
docked results panel**, plus a permanent legend.
- When the map moves, it reports its bounding box. After a **400 ms debounce**
  the app calls `getSegments({bbox, minCrashes, limit: 500})`. Each new request
  **aborts** the previous one (`AbortController`), so a slow old reply can never
  overwrite newer data.
- **Filters:** risk tiers (Critical / Severe / Elevated / Watch / No data),
  road search, and "Include thinly-evidenced segments". That checkbox changes
  `minCrashes` on the *server request* from 6 to 1, because the tier cutoffs
  are calibrated on the ≥ 6 population. Thin segments are drawn at 45% opacity
  (`THIN_FILL_OPACITY`) and flagged, not hidden.
- Filters that the data cannot support (date period, carriageway type,
  per-segment factors) were removed: "a filter that silently matches nothing is
  worse than an absent one."
- Clicking a segment opens the **detail panel**, deep-linkable as
  `/explorer?segment=A23_run3_km0.5`. It shows the tier badge and display
  score, the raw `blackspotScore` (expected KSI), the recorded crash counts
  split into fatal / serious / slight, speed limit, night share and junction
  share. It deliberately has **no** "last incident" date, landmarks or
  per-segment factors, because the data has none and an invented date "is a
  claim about when someone was hurt".
- On mobile the filters become a modal sheet (Escape closes it).

**Route (`/route`, `routes/Route.jsx`).** Start and destination fields with
**autocomplete** (geocoding with a 300 ms debounce, abort on every keystroke,
an accessible **listbox** with arrow keys and Enter, and the list rendered
inline rather than floating over content). "Find route" calls
`POST /api/route/risk`. Results: route cards (label, time, distance,
blackspot count, expected KSI over 2 years); the selected route drawn on the
map with its blackspots coloured by tier; and a side list "Blackspots on this
route" in travel order with distance along the route. Error states: no route
(422), routing unavailable (503, with Retry), backend unreachable. Text on the
screen explains that risk figures are expected casualties on the corridor
across all traffic and grow with route length.

**Rankings (`/rankings`, `routes/Rankings.jsx`).** Fetches the top **2,000**
evidenced segments in one call (`FETCH_LIMIT`), then search and sort run in the
browser. Shown 100 rows at a time (`PAGE`). Sticky header and sticky rank
column; sortable columns with `aria-sort`; search by road number or location.

**Statistics (`/statistics`, `routes/Statistics.jsx`).** Reads `gbStats.json`
(works without the backend). Panels: a KPI strip (crashes, KSI, fatal,
segments); "Share of future serious harm found by each ranking" (model vs past
crash count vs past KSI count at top 1/5/10/20%); "Evidenced segments by risk
tier"; "Crashes that were fatal or serious, by speed limit"; "Roads with the
most fatal or serious crashes"; and "Conditions linked to more serious
crashes" (the SHAP factor ranking). The severity model metrics are in
`gbStats.json` but not shown on this screen. Charts use Recharts.
Monthly or hourly breakdowns are impossible because the crash-level file is not
shipped.

### 10.3 Libraries (`src/lib/`)

| File | What it does |
|---|---|
| `api.js` | The only network module. `getSegments`, `getSegment`, `geocode`, `routeRisk`. Wraps `fetch`, converts errors into `ApiError(status, message)`, re-throws `AbortError` untouched so callers can ignore it, and reports "Cannot reach the API. Is the backend running?" on network failure |
| `riskScale.js` | Maps the raw score (0–9.67) to the 0–100 display scale with piecewise-linear bands: [0, 0.94) → 0–24, [0.94, 1.57) → 25–49, [1.57, 3.09) → 50–74, [3.09, 9.67] → 75–100. **The only place the cutoffs live** |
| `risk.js` | Tier definitions (`TIERS`: word, range, colour), `tierOf(score)`, the `NO_DATA_TIER`, `THIN_FILL_OPACITY = 0.45`, `markerRadius` (6–22 px, scaled by square root of crash count), `worstTier` (a cluster takes its worst member's colour, never an average) |
| `geo.js` | `toView(segment)` converts API records to the UI shape, **flipping `lon` → Leaflet's `lng`** in one place only; `toLatLngs(geometry)` flips route coordinates to `[lat, lng]`. Kept separate so it can be unit-tested without loading Leaflet |
| `filters.js` | Explorer filter definitions, `applyFilters`, `sortBlackspots` (null scores always sink), `MIN_CRASHES_EVIDENCED = 6`, `MIN_CRASHES_ALL = 1` |
| `format.js` | Every displayed number passes through here (`en-GB` locale, one-decimal scores, "26 Nov 2024" dates, "--" for missing values) |
| `motion.js` | Shared animation timings: spring stiffness 100 / damping 20, 30 ms stagger, 180 ms cross-fade |
| `gsapScroll.js` | Landing page ScrollTrigger setup |

### 10.4 Map details (`MapCanvas.jsx`, `Basemap.jsx`)

- **Basemap:** Esri World Dark Gray Canvas (no API key; replaced CARTO), so the
  dark theme carries through. Colourful OSM tiles are banned because their road
  colours clash with the risk colours.
- **Markers:** filled circles (never Leaflet's default blue pin), radius 6–22 px
  by crash count, tier colour, a 1.5 px black outline, and a paper-white outline
  when selected.
- **Heat layer** (`leaflet.heat`): the same yellow → red → violet ramp.
- **Legend:** always visible. It states that tiers rank segments with at least
  6 crashes against each other, not against every road in Britain, and that a
  "Watch" stretch can still sit above the national median of 0.25 expected KSI.
- Attribution: "Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors".

### 10.5 Motion components (`src/components/motion/`)

`Reveal` (fade plus a 14 px settle when scrolled into view, once only),
`CountUp` (numbers spring up from zero; renders the true value on first paint
and force-writes it after 1.2 s, so a casualty count is never left frozen half
way), `SpringBar` (bars grow with `scaleX`, never `width`, because animating
width forces layout every frame).

### 10.6 Layout notes

Each full-height screen is a flex column of exactly `100dvh − nav height`
(with a `100vh` fallback for browsers without `dvh`), and the map grid takes
the remaining height (`flex: 1`). Below 768 px everything collapses to one
column, map first. Horizontal page scroll on mobile counts as a failure.

### 10.7 Frontend tests (16, Vitest)

`riskScale.test.js` (8: tier cutoffs, interior boundaries) and `geo.test.js`
(8: the lon/lat flip and route conversion). No component tests: Vitest runs in a
Node environment without jsdom, a deliberate phase-1 decision.

---

## 11. Design system and theme

`frontend/DESIGN.md` is the single source of truth. `src/styles/tokens.css`
transcribes it into CSS custom properties.

- **Mood:** "night-shift control room, not consumer travel app". The product
  reports where people have been hurt, so nothing is celebratory or playful.
  Quiet interface, loud data.
- **Palette: four colours from a Japanese traditional colour plate**, on a
  black ground with paper-white type:
  - 青色 **Blue** `#1F4FBF`: the only interface accent (buttons, active chips,
    selected route).
  - 山吹色 **Orange Yellow** `#F2A31B`: risk tiers Watch and Elevated; notices.
  - 赤色 **Spectrum Red** `#D7120F`: risk tier Severe; errors.
  - 半色 **Aconite Violet** `#8E44AD`: risk tier Critical.
  - Neutrals: canvas `#0E0F11`, panel `#16171A`, raised `#212327`, ink
    `#EEF0F4` (with 72% and 52% variants), lines at 12% white.
- **Rules:** the accent never borrows a risk colour (a red button would read as
  a hazard). **Colour never encodes a tier on its own**: every tier display
  carries its word, which is essential because Watch and Elevated share a
  colour. Tier boundaries are fixed, never rescaled per view.
- **Type:** Satoshi for the interface; **JetBrains Mono for every number**
  (tabular figures, so columns align). Inter and serif fonts are banned.
- **Layout:** asymmetric, rail-driven; the results panel is docked, never
  floating over the map; 8 px spacing scale; 44 px minimum touch targets.
- **Motion:** spring physics (stiffness 100, damping 20); animate only
  `transform` and `opacity`; honour `prefers-reduced-motion`.
- **Copy:** factual, never dramatised ("Score 78.4, Critical", not "death
  trap"); never imply certainty of prediction; every figure attributed to its
  dataset and years; each screen has a provenance line (for example
  "STATS19 2019 to 2023 · 45,014 scored 500 m segments · routing by
  OpenRouteService").
- **States:** skeleton loaders instead of spinners; empty states say why the
  view is empty and how to fill it; errors are inline with a retry, never a
  full-page takeover.

---

## 12. End-to-end walkthroughs

### 12.1 Opening the Explorer

1. React mounts `Explorer`; Leaflet shows Great Britain on the Esri dark tiles.
2. The map reports its bounds; 400 ms later `api.getSegments` sends
   `GET /api/segments?minScore=0&minCrashes=6&limit=500&bbox=minLon,minLat,maxLon,maxLat`.
3. `SegmentController` validates `limit` (1–2000) and `minCrashes` (≥ 1), and
   calls `SegmentRepository.findInBbox`.
4. PostGIS uses the GIST index (`geom && ST_MakeEnvelope(...)`) and returns up
   to 500 segments, highest score first.
5. Spring serialises the `Segment` records to JSON (18 keys).
6. `geo.toView` converts each one (lon → lng; raw score → 0–100 display score
   via `riskScale`; recorded counts kept as-is).
7. `MapCanvas` draws circles coloured by `tierOf(score)`; the results panel
   lists them sorted by score; panning repeats from step 2 and aborts any
   request still in flight.

### 12.2 Checking a route (Croydon → Camden)

1. The user types "Croydon": after 300 ms, `GET /api/geocode?q=Croydon` →
   `OrsRoutingClient.geocode` → ORS → up to 5 GB candidates → the user picks
   one. The same happens for "Camden".
2. "Find route" → `POST /api/route/risk {from:[lon,lat], to:[lon,lat]}`.
3. `RouteController` applies defaults (minCrashes 6, corridor 50 m) and
   validates them.
4. `RouteRiskService` → `OrsRoutingClient.route(from, to, 3)` → ORS returns up
   to 3 GeoJSON routes (or, for trips over 100 km, the client retries for 1).
5. For each route, the WKT line goes into the PostGIS corridor query → segments
   within 50 m, ordered along the route.
6. Sum the scores → `expectedKsi`; drop near-duplicates; label
   Fastest / Safest.
7. The UI draws the cards, the selected route and its blackspots in order.

**Measured result (Croydon → Camden):** two distinct routes, "Fastest and
safest" 67 min / 27.8 km / 36 blackspots / 63.3 expected KSI, and an
"Alternative" 67 min / 24.1 km / 38 blackspots / 75.5. In the original
phase-1 verification, the safest route carried about **30% less expected KSI
for about 9% more travel time**, and the worst segment moved to a different
corridor (A23 → A40).

---

## 13. Results and verification

### 13.1 Blackspot model validation

On the 30% held-out segments, predicting 2022–2023 KSI: the share of all future
KSI captured by the top x% of segments, ranked three ways:

| Ranking method | Top 1% | Top 5% | Top 10% | Top 20% |
|---|---|---|---|---|
| **Blackspot model** | **8.02%** | **23.02%** | **34.93%** | **50.4%** |
| Past crash count | 7.39% | 22.91% | 34.45% | 49.35% |
| Past KSI count | 6.64% | 18.33% | 26.88% | 38.32% |

**How to read it:** if authorities treated the top 20% of segments ranked by
the model, those segments would contain 50.4% of the serious and fatal
casualties of the next two years. The model **beats raw crash counting by
about 1 point** and beats past-KSI counting by about 12 points. Crash history
dominates, which is why it is the standard blackspot criterion in practice; the
model refines it. Past KSI counts are a poor guide because KSI events are rare
and noisy, while total crashes carry more signal.

### 13.2 Severity models

Deployable ROC-AUC 0.658 (weak); explanatory 0.765–0.769 (not deployable).
Details in section 7.

### 13.3 Route-risk verification

The corridor query was computed **three independent ways** for Croydon →
Camden (Python from the CSV, the Java service layer, and over HTTP). The
results agreed: Fastest 44/45 blackspots (sum 107.90 vs 109.43), Safest 40/42
(74.18 vs 76.76). The 1–2 segment difference comes from the Python version
approximating "within 50 m of a route vertex" instead of PostGIS's true
point-to-line distance. Same order, same magnitudes.

### 13.4 Tier distribution

Displayed tiers come out at roughly 50% Watch, 30% Elevated, 15% Severe and 5%
Critical, by design (section 15.2).

### 13.5 Test status

64 backend tests and 16 frontend tests, all passing; clean production build.

---

## 14. Honesty constraints

These rules are load-bearing; several were broken during development and had
to be fixed.

1. **`blackspot_score` is a prediction, not a tally**: the expected KSI on that
   500 m over two years, across all traffic. (An early version of the Route
   screen wrongly called the figures "recorded casualties accumulated", the
   opposite of the truth; it was fixed.)
2. **But `n_crashes`, `n_ksi` and `n_fatal` *are* real recorded counts** from
   2019–2021. Calling *those* "expected" would be equally wrong.
3. **Route `expectedKsi` is a corridor total across all traffic, not the risk
   of one trip**, and it grows with route length. "Safest" means the lowest
   unnormalised sum.
4. **`future_ksi` / `future_fatal` never reach the database or the API**
   (enforced by the schema and an exact-key-set test).
5. **Nothing is labelled "predicted severity"** (the deployable model is weak).
6. **Tiers are relative**: they rank segments with ≥ 6 crashes against each
   other. The legend says so.
7. **The model beats crash counting by about 1 point.** Do not overstate it.
8. **Thin evidence is flagged, not hidden or ranked as equal.**
9. **No claim of real-time data**: the scores are precomputed.

---

## 15. Engineering decisions and defects found

### 15.1 Architecture decisions

| Decision | Chosen | Rejected and why |
|---|---|---|
| Where route-risk logic runs | Spring Boot backend | Frontend-only would put the ORS key in the browser |
| Database | Supabase Postgres + PostGIS | In-memory would work for 45k rows, but PostGIS gives metre-accurate `ST_DWithin` corridors |
| Routing and geocoding | OpenRouteService | OSRM demo + Nominatim ("no heavy use" policies); self-hosted OSRM (1.5 GB extract, an hour of preprocessing) |
| Data access | JDBC `JdbcTemplate` | JPA does not fit hand-written PostGIS SQL |
| Spatial unit | 500 m segments by chainage | A 500 m grid (mixes roads, meaningless ids); DBSCAN (variable-size clusters, hard to compare) |
| Chainage | MST over crash points | kNN graph (fragmented: A23 → 52 pieces); OSM geometry (extra dependencies) |
| Backend port | 8081 | 8080 held by Oracle TNS Listener |

### 15.2 Two calibrations that were measured, not guessed

**Route alternatives: `share_factor` 0.6 → 0.2.** With the default, ORS's three
"alternatives" for Croydon → Camden were all 22.3 km and 62–63 min, sharing
about **46%** of their geometry with the fastest route, so the
fastest-versus-safest comparison showed near-identical cards. Measured overlap:
0.6/1.6 → 45.8% and 45.6%; 0.4/1.6 → 28.6% and 34.1%; **0.2/2.0 → 1.9% and
7.0%**. "This single parameter is the difference between the feature working
and being pointless." It is configurable in `application.yml`.

**Risk tiers recalibrated to what users see.** The first cutoffs
(0.45 / 0.85 / 1.45) came from all 45,014 segments. But the UI shows only the
6,213 segments with ≥ 6 crashes, whose median is 0.94 (vs 0.25 overall) and
90th percentile 2.24 (vs 0.81). Under the old cutoffs, **23.3% of displayed
segments were "Critical" and 60% Severe-or-worse**: a red screen that
distinguishes nothing. The new cutoffs **0.94 / 1.57 / 3.09** are the 50th, 80th
and 95th percentiles of the displayed population (≈ 50/30/15/5%). The price is
that tiers become relative, which the legend states.

### 15.3 Defects found and fixed (good viva stories)

1. **Credential leak.** An ad-hoc database probe threw an `SQLException` whose
   message contained the full `DATABASE_URL` including the password. It was
   never committed; the password was rotated. Lesson: "never print `.env`" is
   not enough, because **JDBC exceptions embed connection strings**; report
   only the exception type and message.
2. **`.env` loader truncating the API key.** `while IFS='=' read -r key value`
   splits on *every* `=`, so the base64 ORS key lost its trailing `=` and ORS
   answered `403 Access to this API has been disallowed`. The database URL
   survived only because it does not end in `=`, which made the loader look
   correct. Fix: split on the first `=` only with `${line%%=*}` and
   `${line#*=}`. Also, `source .env` breaks because the `&` in `DATABASE_URL`
   is a shell background operator.
3. **Tests that would pass with the feature broken.** A corridor test asserted
   `strict.size() <= loose.size()`, which holds even if the filter is ignored.
   Replaced with "loose contains segments strict excludes". A leak guard
   checked two specific field names; replaced with an exact key-set assertion.
4. **`NO_ROUTE` never fired.** The client expected an empty result, but ORS
   returns **HTTP 404 with code 2010**, so impossible routes showed "temporarily
   unavailable, try again".
5. **A rename broke working links.** Explorer's deep-link parameter went from
   `?cluster=` to `?segment=`, but two callers were not updated. Caught only by
   a whole-branch review.
6. **`/api/segments` ignored filters without a bbox**: `minScore` and
   `minCrashes` were accepted and then dropped. Fixed; both branches apply both
   filters.
7. **Duplicate route cards** from near-identical ORS alternatives: fixed with
   the dedupe in section 9.5.
8. **Trips over 100 km failed** with "routing unavailable" (ORS code 2004):
   fixed with a single-route fallback, plus a test reproducing ORS's real error.
9. **Route and Explorer maps cut off** when the screen height was not enforced:
   the grid landed in a content-sized row. Fixed by making the screens flex
   columns with the map taking the remaining height, and adding a `100vh`
   fallback.

### 15.4 Security and robustness practices

API key server-side and only in headers; secrets in a gitignored `.env`; RLS on
Supabase; CORS limited to the dev origin; HTTP timeouts on the external
dependency; input validation with clear 400 messages; geocoding input
percent-encoded; ORS error bodies never logged; startup fails fast if the ORS
key is missing (`OrsProperties.validate`).

---

## 16. Limitations and future work

**Limitations (state these in the report and viva):**
1. **Partly in-sample scores.** The pipeline trains on 70% of segments but
   scores 100% of them, so the served scores for training segments are
   in-sample (about 77% of the top 500 are rows the model trained on). The
   *validation* numbers are honest (held-out 30% only), but the served ranking
   mixes in- and out-of-sample predictions. A fix (road-grouped out-of-fold
   prediction) is written up in `docs/superpowers/plans/2026-09-01-ml-remediation.md`
   and was deliberately shelved to ship the app.
2. **No exposure normalisation.** Segments are ranked by expected casualties,
   not casualties per vehicle-kilometre, so busy roads dominate: 419 of the top
   500 are in Greater London. It is partly a traffic-density map. Comparing two
   London routes is meaningful; comparing a London route to a rural one is
   less so.
3. **Small gain over crash counting** (about 1 point).
4. **Injury crashes only**; damage-only crashes are not in STATS19.
5. **Great Britain and numbered roads only.**
6. **Chainage is approximated from crash positions**, not real road geometry.
7. **Segment position is one point** (the mean crash location), so the corridor
   match is point-to-line within 50 m.
8. **Route risk is an unnormalised sum** (longer routes accumulate more).
9. **No crash-level time breakdowns** in the UI (crash file not shipped).
10. **External dependency:** ORS free tier, 200 directions requests a day;
    alternatives only up to 100 km.
11. **The deployable severity model is weak** (ROC-AUC 0.658).

**Future work:** the out-of-fold scoring fix; exposure normalisation using DfT
traffic counts (AADF); real road geometry from OpenStreetMap; per-km-normalised
route risk; time-of-day or weather-aware routing; component tests and CI;
production deployment (hosting, HTTPS, an environment-based CORS list);
self-hosted routing to remove the quota; extending to other countries with the
same `(lat, lon, road, date, severity)` data.

---

## 17. Running and testing

**Prerequisites:** Java 21+ (JDK 22 works; `JAVA_HOME` must be set), Node.js
20+, a Supabase project with PostGIS, an OpenRouteService key; Python 3.10+
only to regenerate data.

1. Copy `backend/.env.example` to `backend/.env`; fill in `DATABASE_URL` and
   `ORS_API_KEY`; export them into the shell line by line (see section 15.3,
   item 2).
2. Run `schema.sql` once in the Supabase SQL editor.
3. From `backend/`: `./mvnw spring-boot:run -Dspring-boot.run.arguments=--load-data`
   (loads 45,014 rows).
4. From `backend/`: `./mvnw spring-boot:run` → `http://localhost:8081`
   (check `/api/health`).
5. From `frontend/`: `npm install`, then `npm run dev` → `http://localhost:5173`.

**Tests:** `./mvnw test` (64 backend, no database needed);
`./mvnw test -Dgroups=postgis` (adds live PostGIS tests); `npm test` (16 Vitest).

**Regenerating data:** download the three STATS19 CSVs into `ml/stats19_raw/`,
then from `ml/` run `build_recent.py` (~30 min) → `road_segments.py` (~15) →
`severity_final.py` (~20) → `severity_deployable.py` (~10), then
`build_stats_summary.py`, then reload the database. **No-setup demo:**
`ml/demo/blackspot_map.html` opens in any browser.

---

## 18. Repository and file map

```
Veyra/
├── README.md                     project README
├── CLAUDE.md                     ML pipeline notes: data traps, honest results
├── context.md                    this file
├── data/
│   ├── road_segments_ranked.csv  45,014 scored segments (input to the backend)
│   ├── road_segments_top500.json
│   └── road_segments_meta.json
├── ml/
│   ├── build_recent.py           merge 3 STATS19 tables, 2015-2023, drop leaky fields
│   ├── road_segments.py          stretches, MST chainage, 500 m segments, Poisson model
│   ├── severity_final.py         KSI and 3-class severity models, SHAP (spread ranking)
│   ├── severity_deployable.py    deployable (24) vs explanatory (236) comparison
│   ├── build_stats_summary.py    -> frontend/src/data/gbStats.json
│   ├── clean_road_accident_data.py  older 2009-10 cleaner, unused
│   ├── models/                   .joblib models, severity_metrics.json, deployable_vs_explanatory.json
│   ├── shap/                     global + 11 per-level SHAP tables, subcategory ranking
│   ├── reports/                  full console logs of the runs
│   ├── reference/                DfT casualty valuation tables (RAS4001/4101)
│   ├── demo/blackspot_map.html   standalone demo map
│   └── archive/                  superseded experiments and their results
├── backend/
│   ├── pom.xml, mvnw, .env.example
│   └── src/main/java/com/veyra/blackspot/
│       ├── BlackspotApplication.java
│       ├── web/      SegmentController, RouteController, HealthController,
│       │             RouteRiskRequest, ApiExceptionHandler
│       ├── service/  RouteRiskService
│       ├── routing/  RoutingClient, OrsRoutingClient, RoutingException
│       ├── repo/     SegmentRepository, BoundingBox
│       ├── load/     SegmentLoader, SegmentCsvReader, SegmentIdParser
│       ├── domain/   Segment, RouteRisk
│       └── config/   OrsProperties, WebConfig
│     src/main/resources/ application.yml, schema.sql
├── frontend/
│   ├── DESIGN.md                 design system (single source of truth)
│   ├── README.md
│   ├── package.json, vite.config.js, vitest.config.js, .env.development
│   └── src/
│       ├── App.jsx, main.jsx
│       ├── routes/      Landing, Explorer, Route, Rankings, Statistics (+ .css)
│       ├── components/  MapCanvas, Basemap, DetailPanel, FilterRail, ResultsPanel,
│       │                RouteCompare, Legend, RiskBadge, ProvenanceStrip, States,
│       │                Nav, GradientWaves, MapFragment, charts/ChartFrame,
│       │                motion/ (Reveal, CountUp, SpringBar)
│       ├── lib/         api, riskScale, risk, geo, filters, format, motion, gsapScroll
│       ├── data/gbStats.json
│       └── styles/      tokens.css, global.css
└── docs/
    ├── route-risk-decision-record.md   decisions, calibrations, defects
    └── superpowers/                    design spec and implementation plans
```

---

## 19. Glossary

| Term | Meaning |
|---|---|
| **Blackspot** | A location where crashes cluster more than expected; here, a 500 m road segment with a high predicted KSI |
| **STATS19** | The UK's police-recorded road injury collision dataset, published by the DfT |
| **DfT** | Department for Transport (UK) |
| **KSI** | Killed or Seriously Injured: fatal + serious casualties, the standard UK severity measure |
| **Chainage** | Distance measured along a road from a reference point, as engineers use it ("km 128.4") |
| **Segment / stretch / run** | Segment = a 500 m piece; stretch (`run`) = a geographically continuous part of a road number |
| **MST** | Minimum Spanning Tree: the cheapest set of edges connecting all points with no loops; used to trace a road through its crash points |
| **Double sweep** | Finding a tree's two most distant nodes (its diameter) with two shortest-path searches |
| **Dijkstra** | Shortest-path algorithm on a weighted graph |
| **kNN** | k-nearest neighbours |
| **Poisson regression** | Regression for count data; predicts an expected count; variance grows with the mean |
| **LightGBM** | Microsoft's fast gradient-boosted decision tree library |
| **Gradient boosting** | Builds trees one after another, each correcting the previous ones' errors |
| **Train/test split, held-out** | Data the model never sees in training, used to measure it honestly |
| **Temporal validation** | Features from an earlier period, target from a later one (2019–21 → 2022–23) |
| **Target leakage** | A feature that secretly contains the answer, inflating scores |
| **ROC-AUC** | Probability that a random positive case is ranked above a random negative one; 0.5 = chance, 1.0 = perfect |
| **PR-AUC / average precision** | Area under the precision-recall curve; more informative when positives are rare; compare with the no-skill rate (the positive share) |
| **Lift** | How many times better than random a model's selection is |
| **Precision / recall / F1** | Precision = share of flagged cases that are real; recall = share of real cases flagged; F1 = their harmonic mean |
| **Capture rate (top x%)** | Share of all future KSI that falls in the top x% of ranked segments; the main blackspot metric here |
| **SHAP** | SHapley Additive exPlanations: how much each feature pushed one prediction up or down, based on game theory |
| **Between-level spread** | This project's SHAP ranking: how much the prediction changes across a feature's categories |
| **Confounder** | A hidden factor that creates a misleading association (fine weather ↔ higher speeds) |
| **Deployable vs explanatory model** | Uses only pre-crash information vs also post-crash detail |
| **PostGIS** | The spatial extension for PostgreSQL |
| **Geography vs geometry** | Geography computes on the globe in metres; geometry computes on a flat plane in the coordinate units |
| **SRID 4326 / WGS84** | The lat/long coordinate system used by GPS |
| **WKT** | Well-Known Text, for example `LINESTRING(lon lat, lon lat)` |
| **GIST index** | The index type PostgreSQL uses for spatial data |
| **`ST_DWithin` / `ST_LineLocatePoint` / `ST_MakeEnvelope`** | Within N metres / fraction along a line / build a bounding box |
| **Supabase** | Hosted PostgreSQL with PostGIS, auth and an auto-generated REST API |
| **RLS** | Row Level Security: per-row access rules in PostgreSQL |
| **REST API** | HTTP endpoints exchanging JSON |
| **CORS** | The browser rule that blocks cross-origin requests unless the server allows them |
| **Geocoding** | Turning a place name into coordinates |
| **OpenRouteService (ORS)** | An open-source routing and geocoding API built on OpenStreetMap data |
| **`share_factor` / `weight_factor`** | ORS alternative-route settings: maximum shared road share / maximum length ratio |
| **Debounce** | Waiting until input pauses before acting (400 ms map, 300 ms typing) |
| **AbortController** | Browser API to cancel an in-flight `fetch` |
| **Deep link** | A URL that opens a specific state (`?segment=...`) |
| **Spring Boot / JdbcTemplate / record** | Java web framework / plain-SQL helper / immutable data class |
| **Vite / React / Leaflet / Recharts** | Build tool / UI library / map library / chart library |
| **`dvh`** | Dynamic viewport height CSS unit |

---

## 20. Likely viva questions with model answers

**Q: What does your project do, in one sentence?**
It predicts how many people will be killed or seriously injured on every 500 m
of numbered road in Great Britain over the next two years, from police crash
records, and shows that on a map and in a route planner.

**Q: Why machine learning, when you could just count past crashes?**
That is the standard practice, and we compare against it. The model uses crash
history plus road context (speed limit, junctions, lighting, location) and
captures 50.4% of future KSI in the top 20% of segments vs 49.35% for crash
counting. The improvement is small, about one point, and we say so. Crash
history dominates, and the model refines it. The bigger contribution is the
pipeline (road-level segments, temporal validation) and the application.

**Q: How did you validate the model?**
Temporally and spatially. Features come only from 2019–2021 and the target is
2022–2023, so the model forecasts a period it never saw. Segments are split
70/30, and metrics come only from the held-out 30%. The metric is capture
rate: the share of future KSI found in the top 1/5/10/20% of ranked segments.

**Q: Why Poisson?**
The target is a count of casualties, mostly small with a long tail; Poisson
models counts and outputs an expected count, which is what the score means.

**Q: How do you get "distance along the road" without road maps?**
From the crashes themselves: split each road number into separate stretches
(gaps over 10 km), build a minimum spanning tree over each stretch's crash
points, find the tree's two ends with a double sweep, and use shortest-path
distance from one end as chainage. Then cut it into 500 m segments.

**Q: Why did you split road numbers into stretches?**
Road numbers are reused or misrecorded: "A503" crashes appear 543 km apart,
though the road is 10 km long. Without splitting, chainage came out 57× too
long.

**Q: What is target leakage, and how did you avoid it?**
A feature that contains the answer. STATS19 has nine other severity-derived
fields besides the target; we drop them all and assert none survive. We also
drop "police attended", which is a consequence of severity.

**Q: Why only 2022–2023 for the severity model?**
Police forces switched to injury-based reporting at different times, so the
"serious" share drifted from 14.3% to 22.5%. Training across that teaches the
model which reporting system was used. 2022–2023 are stable.

**Q: Your severity model has ROC-AUC 0.658. Is that good?**
It is weak, and it is the honest number: it uses only information available
before a crash. The 0.765 model uses post-crash details like casualty ages, so
it cannot predict anything. That is why the app never shows "predicted
severity".

**Q: What is SHAP and why "spread"?**
SHAP measures each feature's contribution to a prediction. Mean |SHAP| ranked a
98%-missing column first, because its "unknown" level shifted every prediction
equally without telling crashes apart. Spread, how much the prediction moves
between a feature's levels, measures discriminative effect. Speed limit ranks
first.

**Q: Why PostGIS?**
For metre-accurate spatial queries: "segments within 50 m of this route,
ordered along it" is one SQL statement with `ST_DWithin` and
`ST_LineLocatePoint`, backed by a GIST index. With only 45k rows, an in-memory
approach could work, and we acknowledge that.

**Q: Walk me through the route risk feature.**
Geocode both places, then ask OpenRouteService for up to three routes. For each
route, PostGIS finds evidenced segments within 50 m in travel order; we sum
their scores into expected KSI, drop near-duplicate routes, and label the
fastest and safest. Croydon → Camden: the safest route has about 30% less
expected KSI for about 9% more time.

**Q: Is "expected KSI" the risk of my trip?**
No. It is the expected serious casualties on that corridor over two years
across all traffic, and it grows with route length. It is useful for comparing
alternatives between the same two points.

**Q: Why are the tier cutoffs 0.94 / 1.57 / 3.09?**
They are the 50th, 80th and 95th percentiles of the segments users actually see
(≥ 6 crashes). Cutoffs from the full population made 23% of displayed segments
"Critical", which tells you nothing. The trade-off is that tiers are relative,
and the legend states it.

**Q: Why hide segments with fewer than 6 crashes?**
86% of segments have fewer than six, and their scores are noise. They can be
shown with a checkbox, dimmed and flagged as thinly evidenced.

**Q: How do you keep the API key safe?**
Only the backend talks to OpenRouteService; the key lives in a gitignored
`.env` and goes in a request header, never a URL, so it can't leak through
logs.

**Q: What would you improve?**
Score every segment out-of-fold (today 70% of served scores are in-sample);
normalise by traffic volume, since London dominates the top 500; use real road
geometry; normalise route risk per km; add component tests and deploy it.

**Q: What was the hardest bug?**
For example, the API key truncated by the shell `.env` loader (splitting on
every `=` dropped the key's trailing `=`, giving a confusing 403 while the
database worked), or ORS's 100 km limit on alternative routes, which made every
long trip show "routing unavailable" until we added a single-route fallback.

**Q: What are the main limitations?**
In-sample scores for training segments, no exposure normalisation, a small gain
over crash counting, injury crashes only, GB numbered roads only, approximate
chainage, and dependence on a rate-limited free routing API.

**Q: Why Great Britain and not India?**
The project started with an Indian framing, but no Indian dataset had
comparable coordinate precision and road numbering. STATS19 is open, detailed
and nationwide. The method transfers to any dataset with location, road id,
date and severity.

**Q: Who did what?**
The team roles are ML/Data lead, Backend lead, Frontend lead and
Integration/Docs lead. Names are not recorded in this context; ask the student.
