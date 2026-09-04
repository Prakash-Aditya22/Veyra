# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The ML half of a university group project: **road blackspot detection for Great
Britain**. This file covers the `ml/` pipeline, originally built and owned as
a separate concern from the backend (Spring Boot) and frontend (React/Leaflet)
work — the three have since merged into this one repo (see Layout below).
`ml/` produces the data and models the backend consumes, via `data/`.

Three deliverables: **blackspot scores per 500 m of road**, a **severity model**,
and **SHAP explanations**. The blackspot ranking is the primary product; the
severity model exists mainly as an input to it.

## Running things

No test suite, no build step. Four scripts, run in order from `ml/`:

```bash
python build_recent.py        # ml/stats19_raw/*.csv -> stats19_recent.csv (581MB), ~30 min
python road_segments.py       # chainage -> 500m segments -> blackspot scores, ~15 min
python severity_final.py      # severity models + SHAP -> models/, shap/, reports/, ~20 min
python severity_deployable.py # deployable-vs-explanatory severity comparison, ~10 min
```

`build_recent.py` does not download anything — it reads three pre-downloaded
DfT STATS19 CSVs (collision, vehicle, casualty) from `ml/stats19_raw/`, which
is gitignored and not shipped in this repo; fetch them manually from
`data.dft.gov.uk/road-accidents-safety-data/` before running it, or the script
fails with `FileNotFoundError`. None of the four steps need internet. Steps
2–4 all read `stats19_recent.csv`, so step 1 must have completed. Deps:
`pandas numpy scikit-learn lightgbm shap joblib scipy pyarrow`.

Long runs should go in the background — several exceed a 10-minute foreground
timeout.

## Data source and its traps

UK STATS19 from DfT (`data.dft.gov.uk/road-accidents-safety-data/`), three
linked tables joined on `collision_index`: collision, vehicle, casualty.
Everything is numerically coded, not text.

Four properties of this data have already caused bugs here. Preserve the
mitigations:

**Severity labels drift.** Reported "serious" rose 14.3% → 22.5% across
2015–2023 as forces adopted injury-based reporting (CRASH/COPA), and it never
settles. Training across that drift teaches the model which reporting regime a
force used. `severity_final.py` therefore uses **2022–2023 only**. Fatal is
stable throughout, so blackspot work can span more years.

**Ten fields leak the target,** not one. `collision_severity` is obvious, but
the `adjusted` and `enhanced` variants encode the same answer. See `LEAKY` in
`build_recent.py`; the merge `assert`s none survived.
`did_police_officer_attend_scene_of_accident` is also dropped — attendance is a
*response* to severity.

**Road numbers are not geographically unique.** Crashes tagged `A503` appear
from London to Scotland, 543 km apart, though the A503 is a 10 km London road.
`road_segments.py` splits each road number into geographic stretches
(`STRETCH_GAP_M`) before computing chainage. Without this, chainage on the A503
came out 57× too long.

**Large downloads truncate silently.** A collision-table download once stopped
at 1.4 GB of 1.5 GB and still parsed as valid CSV. Verify the last line has the
full field count before trusting a fresh download.

## How the blackspot score works

Not a formula — a Poisson regression's prediction, meaning **expected
killed-or-seriously-injured casualties on that 500 m over two years**.

Features come from 2019–2021 crashes; the target is that segment's KSI count in
**2022–2023**. Segments are split train/test, so scores are measured on road the
model never trained on, predicting a period it never saw.

**Chainage** (distance along the road) has no external geometry source — no
`osmnx`/`shapely` installed. It is derived from the crashes themselves: a
minimum spanning tree over a road's crash points, then geodesic distance from
one end. An MST is connected by construction, which a kNN graph is not (that
version fragmented the A23 into 52 runs, each restarting at km 0).

## Honest results — do not overstate these

| | |
|---|---|
| Blackspot, top 20% of segments | captures **50.4%** of future KSI |
| …but ranking by raw crash count | captures **49.35%** |
| Severity, deployable (24 feat.) | ROC-AUC **0.658** |
| Severity, explanatory (236 feat.) | ROC-AUC 0.765 |

**The model beats crash counting by ~1 point.** Crash history dominates, which
is why it is the standard blackspot criterion in practice. The model refines it.

**The explanatory severity model is not deployable** — it uses casualty ages,
first point of impact, whether a pedestrian was struck, none of which exist
before a crash. The deployable model is the honest one and is a weak predictor.
Do not present anything as "predicted severity."

**86% of segments rest on fewer than 6 crashes** and their scores are noisy.
Filter to `n_crashes >= 6` for anything user-facing.

## SHAP: rank by spread, not mean |SHAP|

`severity_final.py` ranks categorical features by **between-level spread** —
how much the prediction moves when the level changes. Mean |SHAP| ranked a
98%-missing column first, because one giant "unknown" level shifted every
prediction equally while distinguishing nothing. Don't revert to mean |SHAP|.

`police_force` scores highly on spread but is administrative — recording
differences between forces, not real risk. Exclude it from anything presented
as a cause.

## Layout

This repo also holds the teammates' backend and frontend — this file covers
the `ml/` pipeline only; see `backend/README.md` and `frontend/README.md` for
those.

```
backend/                       Spring Boot API — segments, route risk, geocoding
frontend/                      React 18 + Vite + Leaflet UI
data/                          road_segments_ranked.csv — 45,014 scored segments, consumed by backend
docs/                          specs and plans (docs/superpowers/)
ml/                             this pipeline
  build_recent.py road_segments.py severity_final.py severity_deployable.py
  clean_road_accident_data.py   pre-existing; cleans an older 2009-10 file, now unused
  models/ shap/ reports/        severity models, metrics, global + per-level SHAP
  demo/                         blackspot_map.html — standalone demo, no server needed
  reference/                    DfT casualty valuation tables (RAS4001)
  archive/                      superseded experiments — keep, they document what failed
  stats19_raw/                  three pre-downloaded DfT CSVs, gitignored, not shipped
  stats19_recent.csv            581MB, regenerable, not in git
```

`archive/` holds real negative results worth citing: a hierarchical cascade
superseded by threshold tuning, SVM and neural nets losing to gradient
boosting, a 2×2 feature ablation, and an evaluation-protocol experiment showing
the same model scoring 0.379 or 0.729 depending on whether balancing precedes
the train/test split.
