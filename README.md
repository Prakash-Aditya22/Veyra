# Accident Blackspot Detection & Visualization System

A web app that identifies and visualizes accident-prone road stretches ("blackspots") using machine learning on historical accident data, helping commuters plan safer routes and giving authorities data to prioritize road-safety interventions.

## Problem Statement

Road accidents cluster around specific locations due to factors like poor visibility, sharp turns, missing signage, weather, or traffic density. There's no easy way for commuters or authorities to see where these blackspots are. This project analyzes historical accident data to detect and rank dangerous road stretches, then displays them on an interactive map.

## Features

- Interactive map of accident blackspots (markers/heatmap)
- Ranked list of dangerous roads with a computed risk score
- Filter by time period, severity, and road type
- Stats dashboard (accidents by month, time of day, severity)
- Search/zoom to a specific road or area

## Tech Stack

- **Backend:** Java, Spring Boot (REST API)
- **ML/Data:** Python (pandas, scikit-learn, geopy) — offline pipeline for clustering and risk scoring
- **Database:** PostgreSQL + PostGIS
- **Frontend:** React, Leaflet.js (OpenStreetMap)
- **Charts:** Chart.js / Recharts

## Architecture

```
Accident Dataset (CSV)
        |
        v
Python: cleaning, EDA, DBSCAN clustering, severity model
        |
        v
Processed blackspot + risk data --> PostgreSQL/PostGIS
                                            |
                                            v
                              Spring Boot REST API
                                            |
                                            v
                        React + Leaflet frontend
```

## Project Structure

```
/ml            - Python scripts/notebooks for data cleaning, clustering, model training
/backend       - Spring Boot application (REST API)
/frontend      - React application
/data          - Raw and processed accident datasets
README.md
```

## Running the full stack

Explorer and the Route screen read the live backend API against the real,
scored segment data. Rankings and Statistics still read a static fixture
(`frontend/src/data/blackspots.js`) — wiring them to the API is Phase 2 and
hasn't happened yet.

### Prerequisites

- Java 21+ (a JDK 22 install works fine; the build targets 21)
- Node.js 20+
- A Supabase project (Postgres + PostGIS)
- An OpenRouteService API key — free at https://openrouteservice.org/dev/#/signup.
  **The free tier is 200 directions requests/day, not 2,000** — easy to burn
  through the morning of a demo, so use it deliberately.
- Python 3.10+ only if you intend to regenerate `data/road_segments_ranked.csv`
  yourself — see [`ml/README.md`](ml/README.md). The committed CSV is enough
  to run everything below.

`JAVA_HOME` isn't set by default on Windows dev machines, and Maven's
wrapper refuses to start without it:

```bash
export JAVA_HOME="/c/Program Files/Java/jdk-22"      # Git Bash
```
```powershell
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-22'      # PowerShell
```

### Configure

`backend/.env` is required and gitignored — copy `backend/.env.example` to
`backend/.env` and fill in `DATABASE_URL` and `ORS_API_KEY`. Spring Boot does
not read `.env` files natively, and there are two ways of loading it that
look right and silently corrupt a value: `. ./.env` (the `&` in
`DATABASE_URL` gets parsed as the background-job operator) and any loader
that sets `IFS='='` (truncates a base64-shaped `ORS_API_KEY` at its trailing
`=`). [`backend/README.md`](backend/README.md#configure) has the loader that
actually works — treat it as the one source of truth for this step rather
than duplicating it here.

### Run, in order

1. **Schema** — paste `backend/src/main/resources/schema.sql` into the
   Supabase SQL editor and run it once. It opens with `DROP TABLE IF EXISTS`,
   so re-running it wipes the table.
2. **Load the data**, from `backend/`:

   ```bash
   ./mvnw spring-boot:run -Dspring-boot.run.arguments=--load-data
   ```

   Reads `../data/road_segments_ranked.csv` (45,014 rows) and truncates the
   table before inserting, so re-running it after a data refresh is safe.
3. **Backend**, from `backend/`:

   ```bash
   ./mvnw spring-boot:run
   ```

   Serves on `http://localhost:8081` — not Spring Boot's default 8080;
   Oracle's TNS Listener permanently owns 8080 on the development machine.
4. **Frontend**, from `frontend/`:

   ```bash
   npm install && npm run dev
   ```

   Vite dev server on `http://localhost:5173`.

## Team

| Name | Role |
|---|---|
| TBD | ML/Data Lead |
| TBD | Backend Lead |
| TBD | Frontend Lead |
| TBD | Integration/Docs Lead |

## Roadmap

See project plan / issues for the phased development timeline.

## License


