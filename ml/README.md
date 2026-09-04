# ML — Blackspot Detection

Everything the backend and frontend need, plus a working demo.

**Run from this directory.** All scripts use paths relative to `ml/`.

```bash
pip install -r requirements.txt
python build_recent.py         # ml/stats19_raw/*.csv -> stats19_recent.csv (581MB, gitignored), ~30 min
python road_segments.py        # 500m road segments + blackspot scores
python severity_final.py       # severity models + SHAP
python severity_deployable.py  # deployable vs explanatory severity
```

`build_recent.py` does not download anything — it reads three pre-downloaded
DfT STATS19 CSVs (collision, vehicle, casualty) from `stats19_raw/`, which is
gitignored and not shipped in this repo. Fetch them manually from
`data.dft.gov.uk/road-accidents-safety-data/` first, or the script fails with
`FileNotFoundError`. None of the four scripts need internet. Outputs the
backend consumes are committed to `../data/`.

**Data:** UK STATS19 (DfT), Open Government Licence v3.0.
1,049,378 collisions, 2015–2023. Segments built from 2019–2021 crashes,
validated against 2022–2023 crashes the model never saw.

```
ml/demo/blackspot_map.html       ← open this first, it explains the whole thing
data/road_segments_ranked.csv    45,014 segments — load into PostGIS
data/road_segments_top500.json   serve directly while the DB is set up
ml/models/                       severity models + metrics
ml/shap/                         global + 11 per-level SHAP tables
ml/reports/                      full console output — numbers not in the CSVs
ml/reference/                    DfT casualty valuation tables (RAS4001)
ml/*.py                          the pipeline, reproducible from scratch
ml/archive/                      superseded experiments (keep for the report)
```

---

## Start here — `ml/demo/blackspot_map.html`

Double-click it. No install, no server. Real OpenStreetMap tiles, pick any of
60 roads, every 500 m coloured by risk, click a block for its numbers.

---

## How a segment is scored

The score is a model output, and it means one specific thing:

> **Expected killed-or-seriously-injured casualties on that 500 m over 2 years.**

A block scoring 2.4 is predicted to produce roughly two to three KSI
casualties in two years.

**18 inputs**, all from 2019–2021 crashes on that segment:

| Group | Features |
|---|---|
| Crash history | `n_crashes`, `n_ksi`, `n_fatal`, `crashes_per_year`, `ksi_rate`, `n_years` |
| Road | `speed_max`, `speed_mean`, `mode_road_type`, `mode_junction_detail`, `pct_junction` |
| Context | `mode_urban_or_rural_area`, `mode_light_conditions`, `pct_night` |
| Crash shape | `n_veh_mean`, `n_cas_mean` |
| Location | `lat`, `lon` |

**Target:** KSI count on that segment in 2022–2023.
**Model:** LightGBM, Poisson objective — the target is a count whose variance
grows with its mean, so squared error would treat a 0-vs-2 miss the same as
20-vs-22.

**Colour bands** come from the real score distribution (median 0.25, p90 0.83,
p99 2.04), so black means top ~1% of British road, not merely "worst on this
road":

```
< 0.45   low        light orange
< 0.85   moderate   orange
< 1.45   high       red
< 2.20   severe     dark red
  2.20+  critical   black
```

---

## Does it work?

Held-out segments, predicting 2022–23 KSI:

| Targeted | Share of future KSI captured |
|---|---|
| Top 1% | 8.0% |
| Top 5% | 23.0% |
| Top 10% | 34.9% |
| **Top 20%** | **50.4%** |

Survey a fifth of segments, cover half of future serious casualties.

**Say this in the report:** ranking by raw past crash count alone captures
49.35%. The model adds about one point. Crash history dominates — which is
exactly why it is the standard blackspot criterion in practice. The model
refines it rather than replacing it. Claiming otherwise invites an examiner
to check.

---

## `data/road_segments_ranked.csv`

45,014 rows, one per 500 m of road that carried at least one crash in
2019–2021. (The chainage produced 55,056 possible 500 m bins across 1,027
roads; the 10,042 with no crashes in the build window are not scored.)

| Column | Meaning |
|---|---|
| `rank` | 1 = highest risk, pre-sorted |
| `segment_id` | primary key, e.g. `A23_run3_km0.5` |
| `location` | human-readable, e.g. `A23 km 0.5-1.0 (seg 3)` |
| `road_id` | `A23`, `M25`, `B1234` … |
| `km_from`, `km_to` | distance along that stretch |
| `lat`, `lon` | centroid — **use for the map pin** |
| `blackspot_score` | **rank by this** |
| `n_crashes`, `n_ksi`, `n_fatal` | 2019–2021 counts |
| `ksi_rate` | `n_ksi / n_crashes` |
| `speed_max`, `pct_night`, `pct_junction` | segment character |
| `future_ksi`, `future_fatal` | actual 2022–23 outcome — **validation only** |

```sql
CREATE TABLE road_segment (
  segment_id      TEXT PRIMARY KEY,
  road_id         TEXT NOT NULL,
  run             INTEGER NOT NULL,
  location        TEXT NOT NULL,
  km_from         DOUBLE PRECISION,
  geom            GEOGRAPHY(POINT,4326) NOT NULL,
  blackspot_score DOUBLE PRECISION NOT NULL,
  rank            INTEGER NOT NULL,
  n_crashes INTEGER, n_ksi INTEGER, n_fatal INTEGER,
  ksi_rate DOUBLE PRECISION, speed_max DOUBLE PRECISION, pct_night DOUBLE PRECISION
);
CREATE INDEX idx_seg_geom  ON road_segment USING GIST (geom);
CREATE INDEX idx_seg_score ON road_segment (blackspot_score DESC);
CREATE INDEX idx_seg_road  ON road_segment (road_id, run, km_from);
```

⚠️ **Do not serve `future_ksi` / `future_fatal`.** They are the actual
2022–23 outcome, included to prove the model works. Serving them is showing
the answer.

⚠️ **`run` matters for drawing a road.** A road number can cover several
geographically separate stretches (crashes tagged `A503` appear 543 km apart,
though the A503 is a 10 km London road). To draw one continuous line:

```sql
SELECT lat, lon, blackspot_score FROM road_segment
WHERE road_id = 'A23' AND run = 2 ORDER BY km_from;
```

`run` is currently embedded in `segment_id` — parse it out, or ask and I will
add it as its own column.

Suggested endpoints:
```
GET /segments?minScore=&road=&bbox=&limit=
GET /segments/{segment_id}
GET /roads/{road_id}/runs/{run}/segments     ordered polyline for the map
GET /stats/summary
```

---

## Severity models — read before putting this in the UI

`ml/models/severity_deployable_model.joblib` is **the one to use in the service.**

| | Deployable (24 feat.) | Explanatory (236 feat.) |
|---|---|---|
| ROC-AUC | **0.658** | 0.765 |
| PR-AUC | 0.362 (1.53× no-skill) | 0.510 (2.15×) |
| F1 | 0.394 | 0.495 |

The explanatory model only scores better because it uses information recorded
*after* the crash — casualty ages, first point of impact, whether a pedestrian
was struck. A live service has none of that. The deployable model is the
honest one, and at ROC-AUC 0.658 it is a **weak predictor**.

**Do not label anything "predicted severity."** Two better options, both
already in the data:

1. Show the segment's *historical* severity mix — `n_ksi`, `ksi_rate`.
   Factual, no model, more useful to a user than a weak prediction.
2. Keep the severity model where it genuinely contributes: as an input to
   `blackspot_score`, where SHAP ranked it #7 and #10.

Three-class model: macro-F1 0.475, Fatal average precision 0.184 against a
0.0149 base rate — **12.4× better than chance**. Quote the AP lift for Fatal,
not the F1 (0.139), which looks like failure but is just what a 1.5% class
does to a threshold metric.

---

## SHAP — the "why is this dangerous" panel

`ml/shap/subcategory_ranking.csv` ranks factors by **between-level spread** — how
much the prediction moves when the level changes — not by mean |SHAP|, which
rewards a feature that shifts every prediction equally while distinguishing
nothing.

`ml/shap/per_level/*.csv` gives every level of every categorical with `n`,
`mean_shap`, `std_shap` and a `low_sample` flag.

Solid enough to show a user:

```
speed_limit       50/60/70 mph  +0.183     30 mph  -0.063    20 mph  -0.079
light_conditions  Dark, no lighting +0.124  →  Dark, unlit +0.083
                  →  Dark, lit +0.051       →  Daylight  -0.027
urban_or_rural    Rural +0.068               Urban  -0.031
```

Positive pushes toward serious. Speed limit is monotonic; lighting is
perfectly ordered, worst unlit. Both match physical intuition, which is why
they are safe to present.

⚠️ `police_force` ranks second by spread but is administrative — it reflects
recording differences between forces, not real risk. **Do not show it as a cause.**

---

## Known limitations

State these in the report; an examiner will look for them.

1. **Chainage is derived from crash positions, not a surveyed centreline.**
   "A23 km 0.5" is distance from one end of that stretch, not an official
   milepost. Within ~1% on clean roads (A3: 93.5 km measured vs 92 actual).
2. **Road numbers are not geographically unique in this data** — see the
   `run` note above. Median 1 stretch per road, worst case 42.
3. **No exposure normalisation.** Segments rank by expected casualties, not
   casualties per vehicle-km, so busy roads outrank quiet dangerous ones.
   DfT publishes AADT counts if you want to fix this.
4. **Injury collisions only.** STATS19 never records damage-only crashes.
5. **Severity labels drifted** 14.3% → 22.5% "serious" across 2015–2023 as
   forces adopted injury-based reporting. Severity models use 2022–23 only.
6. **COVID:** 2020–21 traffic fell ~22%. Locations valid, counts dip.
7. **86% of all segments rest on fewer than 6 crashes** and their scores are
   noisy. The map demo filters to ≥6; the UI should too, or grey them out.

---

## Reproducing

`stats19_recent.csv` (581 MB) is not included — `build_recent.py`
regenerates it from the raw DfT CSVs in `stats19_raw/` in about 30 minutes
(fetch those from `data.dft.gov.uk/road-accidents-safety-data/` first; they
are not shipped in this repo either).

**Not included, and why:** `severity_3class_model.joblib` (24 MB). Its
metrics are in `ml/models/severity_metrics.json`, and `severity_final.py`
regenerates it. The deployable and KSI models — the two you would actually
serve — are both here.

`ml/archive/` holds superseded experiments: the hierarchical cascade, the
SVM/neural-net comparison, the 2×2 ablation, the evaluation-protocol
experiment. Not needed to run anything — kept because "what we tried and why
we rejected it" is worth marks.
