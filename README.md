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

## Getting Started

### Prerequisites

- Java 17+ and Maven
- Node.js 18+
- Python 3.10+
- PostgreSQL (with PostGIS extension)

### Setup

```bash
# Clone the repo
git clone <repo-url>
cd <repo-name>

# ML pipeline
cd ml
pip install -r requirements.txt
python preprocess.py

# Backend
cd ../backend
./mvnw spring-boot:run

# Frontend
cd ../frontend
npm install
npm start
```

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

TBD
