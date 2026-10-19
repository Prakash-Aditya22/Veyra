# ML → backend integration contract (v2)

| | |
|---|---|
| Contract version | **1.0** (2026-10-14) |
| Release | `score_version` **v2.0**, frozen model spec `b9487674e4f1…` |
| Forecast | **2026–2027**, from 2023–2025 history |
| Machine-readable copy | `integration_schema_v2.json` (generated from `ml/blackspot/contract.py`) |
| Release manifest | `release_manifest_v2.json` (files, roles, hashes, rows, periods, timestamps) |
| Validator | `.venv/Scripts/python ml/audit/validate_contract.py [directory]` |
| Test fixture | `ml/tests/fixtures/integration/` (13 real segments, same layout as this folder) |

This document defines what the ML side delivers to the Spring Boot / PostGIS backend. It
**describes the existing files; it changes none of them**. Where an existing file is ambiguous,
the ambiguity is documented here and resolved by an additive file, never by changing a
column. `README.md` in this folder remains the short guide; this is the reference.

## 0. The ten things the backend needs to know

1. **Load one file:** `road_segments_ranked_v2.csv`, one row per segment, primary key `segment_id`. With `road_segments_meta_v2.json` it is the whole required contract. Everything else is optional.
2. **`blackspot_score` is expected serious-or-fatal casualties (DfT severity-adjusted) on the segment over 2026 and 2027 combined.** It is a burden (a count), not a risk per vehicle, and not a 0–100 index.
3. **Order by `rank`.** The CSV rounds the score to 6 significant digits; 6,729 rows share a rounded value. Re-sorting by the CSV score does not reproduce the ranking.
4. **Ranks are national** (1 of 1,827,550). The file holds the top 50,000 plus every segment with ≥ 6 collisions, so ranks have gaps above 50,000.
5. **Treat the rank as a tier, not a position.** Neighbouring ranks are indistinguishable (§3.5). Show the stability range where available.
6. **Coordinates:** `lat`/`lon` and GeoJSON are WGS84 (EPSG:4326); GeoJSON positions are `[lon, lat]`. Lengths are metres measured in British National Grid.
7. **The per-vehicle rate `ksi_per_100m_vkm_eb` exists only where `exposure_available` is true** (motorway and A roads with a DfT count). Never fill it, and do not display it for segments shorter than 250 m.
8. **Optional extensions join on `segment_id`** and carry the same `rank`. The base file works without them.
9. **Explanations are model attributions, not causes**, and exist for 281,353 of 1.83 M segments (all 50,015 exported rows). Show "not available" otherwise.
10. **Production vs research:** only the files listed as required or optional in §1 are for loading. Everything under `ml/` is research, demo or legacy (`release_manifest_v2.json` → `not_for_loading`).

## 1. File inventory

### 1.1 Production, backend-facing (this folder)

| File | Format | Purpose | Required? | Replaces / extends | Regenerate | Consumer |
|---|---|---|---|---|---|---|
| `road_segments_ranked_v2.csv` | CSV, UTF-8, comma, header, 52 columns, 50,015 rows | segment scores, history, EB and exposure columns | **required** | extends v1 `data/road_segments_ranked.csv` (19 v1 columns first, same order). **New segment IDs** | `ml/pipeline.py forecast` | backend → PostGIS |
| `road_segments_meta_v2.json` | JSON object | version, spec hash, periods, column notes | **required** | extends v1 meta | `ml/pipeline.py forecast` | backend (store with the load) |
| `road_segments_top500_v2.json` | JSON array of 500 row objects, same fields as the CSV, **full precision** | static fallback before the database exists | optional | extends v1 top-500 JSON | `ml/pipeline.py forecast` | backend / frontend |
| `road_segments_top5000_v2.geojson` | GeoJSON FeatureCollection, 5,000 LineStrings | real road-centreline geometry for the top 5,000 | optional | new (v1 had points only) | `ml/pipeline.py forecast` | backend geometry table / map |
| `release_manifest_v2.json` | JSON | file roles, sha256, rows, periods, timestamps, inputs | optional (recommended) | new, Phase 3 | `ml/audit/release_manifest.py` | backend load job |
| `integration_schema_v2.json` | JSON | this contract's field list | optional | new, Phase 3 | `ml/audit/release_manifest.py` | backend validation / DDL |

### 1.2 Optional extensions (`extensions/`, additive, keyed by `segment_id`)

| File | Rows | Purpose | Regenerate |
|---|---|---|---|
| `segment_explanations_v2.csv` | 5 per segment, 250,075 (all 50,015 base rows) | top-5 TreeSHAP attributions of the production model | `ml/experiments/explain_blackspot.py` (~25 min) |
| `segment_explanations_top5000_v2.json` | 5,000 (the GeoJSON segments) | the same, with group factors, for the map | same |
| `segment_stability_v2.csv` | 50,015 | rank ranges across refits, top-k frequencies, window range | `ml/experiments/ranking_stability.py --boot 20 --seeds 5` (~35 min) |
| `segment_single_event_sensitivity_v2.csv` | 1,000 (production top 1,000) | forecast and rank without the segment's largest collision | `ml/experiments/single_event_case.py` (~3 min) |

All four are optional. None replaces a base column. The first three were added in Phase 2, the
last in Phase 3.

### 1.3 Research only (do not load)

`ml/outputs/road_segments_v2_full.parquet` (all 1.83 M segments, gitignored, regenerable);
`ml/outputs/explainability/` (saved production model `production_lgbm.txt`, SHAP tables,
plots); `ml/reports/*` (evidence, including the historical-window and stability tables);
`ml/interim/*` (checkpoints). They support the reports and audits. They are not an interface
and can change without notice.

### 1.4 Demo only

`ml/demo/blackspot_map_v2.html` (the v2 map), `ml/demo/blackspot_map_v2_explained.html`
(reference implementation of §5 and §8; reads only the files in §1.1–1.2). They are standalone
pages, not APIs. `blackspot_map_v2_r2.html` and `blackspot_map_v2_explained_r2.html` embed the same data with a
configurable basemap that falls back to a neutral background. Use them for viewing. The originals hard-code
OpenStreetMap tiles, which are blocked when the page is opened from a file (`ml/README.md`, "Demo maps:
basemap").

### 1.5 Legacy (v1, superseded, unchanged)

`data/road_segments_ranked.csv`, `road_segments_top500.json`, `road_segments_meta.json` and
`blackspot_handoff.zip`. Their v1 `blackspot_score` was an in-sample fit of KSI **collisions** on
crash-derived segments. Neither the scores nor the IDs are comparable with v2 (§6.3).

## 2. Field-level data dictionary

Conventions for every table:
- **Empty** means an empty CSV cell, JSON `null`, or `""` for the two text fields `road_number` and `road_name` in the JSON file.
- **Booleans** are written `True` / `False` in CSV and `true` / `false` in JSON.
- **"History"** means the collisions of **2023–2025** (three years) snapped to the segment, unless stated otherwise.
- **"ID"** marks a stable identifier.
- **"Changes between versions"** says whether the value can differ in a future release for the same segment. Scores always can.

### 2.1 `road_segments_ranked_v2.csv` (and `road_segments_top500_v2.json`)

**v1-compatible columns (first, in this order):**

| Column | Type | Empty when | Units | Meaning and source | ID | Changes between versions |
|---|---|---|---|---|---|---|
| `rank` | int ≥ 1 | never | rank | national rank of `blackspot_score` among all 1,827,550 scored segments; ties broken by `segment_id` ascending (`outputs.assemble`) | no | yes |
| `segment_id` | text | never | — | `<label>-<12 hex>-<piece>` (§4.3); unique | **yes** | only with a new OS Open Roads release |
| `location` | text | never | — | display label "road (name) from–to km of stretch N" | no | rarely |
| `road_id` | text | never | — | road number (`A23`, `A1(M)`, `M6 TOLL`), or class letter `C`, `U`, `N` for unnumbered roads; equals the label part of `segment_id` | no | with the network |
| `km_from`, `km_to` | float | never | km | start/end along the junction-to-junction stretch, 3 decimals; not a milepost | no | with the network |
| `lat`, `lon` | float | never | degrees, WGS84 | segment midpoint, converted from BNG with pyproj; CSV keeps 6 significant digits (about 10 m); JSON full precision | no | with the network |
| `blackspot_score` | float > 0 | never | expected adjusted KSI casualties, **2026+2027 total** | the production forecast (§3) | no | **yes** |
| `n_crashes` | int ≥ 0 | never | collisions, history | injury collisions on the segment, all severities | no | yes |
| `n_ksi` | int ≥ 0 | never | collisions, history | collisions with `collision_severity` fatal or serious (reported) | no | yes |
| `n_fatal` | int ≥ 0 | never | collisions, history | fatal collisions | no | yes |
| `ksi_rate` | float 0–1 | `n_crashes = 0` | share | `n_ksi / n_crashes` | no | yes |
| `crashes_per_year` | float ≥ 0 | never | collisions / year | `n_crashes / 3` | no | yes |
| `speed_max` | float ∈ {20, 30, 40, 50, 60, 70} | `n_crashes = 0` | mph | highest STATS19 speed limit at the segment's collisions | no | yes |
| `pct_night` | float 0–1 | `n_crashes = 0` | share | collisions 22:00–05:59 | no | yes |
| `pct_junction` | float 0–1 | `n_crashes = 0` | share | **v1 definition**: `junction_detail != 0`. Missing/unknown codes count as junction; 2024-format roundabouts count as non-junction. Use `pct_junction_v2` | no | yes |
| `future_ksi`, `future_fatal` | float | **always** | — | the forecast period has not happened | no | — |

**v2 additions:**

| Column | Type | Empty when | Units | Meaning and source | ID | Changes between versions |
|---|---|---|---|---|---|---|
| `run` | int ≥ 0 | never | — | stretch ordinal within `road_id`, for drawing order only | no | with the network |
| `score_version` | text = `v2.0` | never | — | output version | no | yes |
| `score_model` | text = `lgbm` | never | — | model behind the score | no | yes |
| `score_definition` | text | never | — | plain-text definition of the score | no | yes |
| `forecast_period` | text = `2026-2027` | never | years | what the score forecasts | no | yes |
| `history_period` | text = `2023-2025` | never | years | what the history columns and model inputs cover | no | yes |
| `road_class` | text ∈ {M, A, B, C, U, N} | never | — | OS Open Roads class by majority length (U unclassified, N not classified) | no | with the network |
| `road_number` | text | unnumbered road | — | OS road number | no | with the network |
| `road_name` | text | unnamed road | — | OS road name | no | with the network |
| `form_of_way` | text | never | — | OS formOfWay by majority length (Single Carriageway, Collapsed Dual Carriageway, Dual Carriageway, Roundabout, Slip Road, Shared Use Carriageway, …) | no | with the network |
| `length_m` | float ≥ 0 | never | **metres** (BNG planar) | segment centreline length, 0.1 m | no | with the network |
| `os_first_link_id` | text (UUID) | never | — | OS Open Roads RoadLink identifier of the first link: geometry reference into OS data | reference | with the OS release |
| `piece` | int ≥ 0 | never | — | piece index within the stroke; the last part of `segment_id` | part of ID | with the network |
| `pct_junction_v2` | float 0–1 | `n_crashes = 0` | share | collisions at a junction (2024 codes 13, 16–19, or roundabout road type) | no | yes |
| `n_ksi_casualties` | int ≥ 0 | never | casualties, history | KSI casualties as reported | no | yes |
| `n_ksi_casualties_adjusted` | float ≥ 0 | never | adjusted casualties, history | KSI casualties on DfT's severity-adjusted scale (the target's scale) | no | yes |
| `eb_expected_ksi` | float ≥ 0 | never | expected adjusted KSI, 2026+2027 | **benchmark** Empirical Bayes forecast; not the production score | no | yes |
| `spf_expected_ksi_history` | float ≥ 0 | never | adjusted KSI, history | expected on similar roads (NB2 SPF on road attributes, no crashes, no traffic) | no | yes |
| `eb_ksi_history` | float ≥ 0 | never | adjusted KSI, history | EB estimate of the segment's own KSI | no | yes |
| `eb_excess_ksi_history` | float (can be < 0) | never | adjusted KSI, history | `eb_ksi_history − spf_expected_ksi_history`: worse (> 0) or better than similar roads | no | yes |
| `eb_weight` | float 0–1 | never | share | EB weight on the SPF prior, `1 / (1 + α·SPF)` | no | yes |
| `aadf` | float > 0 | `exposure_available = false` | vehicles / day | mean AADF (all motor vehicles) 2023–25 at the matched DfT count point | no | yes |
| `aadf_count_point` | integer stored as a float | `exposure_available = false` | — | DfT `count_point_id` used | reference | yes |
| `aadf_share_counted` | float 0–1 | `exposure_available = false` | share | share of the AADF years that DfT counted rather than estimated | no | yes |
| `exposure_available` | bool | never | — | a same-number DfT count point matched (motorway and A roads only) | no | yes |
| `vehicle_km_history` | float ≥ 0 | `exposure_available = false` | vehicle-km, history | `aadf × 365 × 3 × length_m / 1000` | no | yes |
| `ksi_per_100m_vkm_eb` | float ≥ 0 | `exposure_available = false` (never imputed) | adjusted KSI per 100 million vehicle-km, **history** | EB-smoothed per-vehicle **rate** for 2023–25. Not a forecast, not `blackspot_score` | no | yes |
| `eb_excess_ksi_exposure` | float (can be < 0) | `exposure_available = false` | adjusted KSI, history | EB KSI minus the exposure-SPF expectation | no | yes |
| `data_sufficiency` | text ∈ {sufficient, sparse, none} | never | — | ≥ 6 / 1–5 / 0 collisions in the history | no | yes |
| `max_single_collision_ksi` | float ≥ 0 | never (0 if no collision) | adjusted KSI | largest adjusted KSI from one collision on the segment | no | yes |
| `single_event_share` | float 0–1 | `n_ksi_casualties_adjusted = 0` | share | `max_single_collision_ksi / n_ksi_casualties_adjusted` | no | yes |
| `single_event_flag` | bool | never | — | one collision gave ≥ 5 adjusted KSI and ≥ 50% of the history KSI (mass-casualty event). Post-hoc annotation; changes no score. 104 nationally, 1 in the top 500 | no | yes |
| `spatial_block` | int | never | — | 50 km BNG square used for spatial validation: `floor(E/50000)·1000 + floor(N/50000)`. Not an administrative area | no | no |

Invariants checked by the validator: `n_fatal ≤ n_ksi ≤ n_crashes`; `km_from ≤ km_to`;
`data_sufficiency` agrees with `n_crashes`; the five history descriptors are empty exactly when
`n_crashes = 0`; every exposure column is empty exactly when `exposure_available` is false, and
exposure occurs only on M/A roads; `single_event_flag` implies its definition; the
`segment_id` label equals `road_id` and its suffix equals `piece`; scores do not increase with rank.

### 2.2 GeoJSON feature properties (`road_segments_top5000_v2.geojson`)

| Property | Type | Empty when | Meaning |
|---|---|---|---|
| `rank` | int | never | as the CSV |
| `segment_id` | text | never | join key to the CSV (**ID**) |
| `road_id` | text | never | as the CSV |
| `location` | text | never | as the CSV |
| `blackspot_score` | float | never | as the CSV, rounded to 4 decimals |
| `eb_excess_ksi_history` | float | never in this file | as the CSV, rounded to 4 decimals |
| `n_crashes` | int | never | as the CSV |
| `data_sufficiency` | text | never | as the CSV |
| `single_event_flag` | bool | never | as the CSV |

The GeoJSON carries no version or period. Take them from the CSV or `release_manifest_v2.json`
and never from the geometry file.

### 2.3 Extension fields

`segment_explanations_v2.csv`:

| Column | Type | Empty when | Units | Meaning |
|---|---|---|---|---|
| `segment_id` | text | never | — | join key (**ID**) |
| `rank` | int | never | rank | production rank (equals the CSV) |
| `contrib_rank` | int 1–5 | never | — | 1 = largest absolute attribution |
| `feature` | text | never | — | model input name (one of 45) |
| `label` | text | never | — | plain-English label |
| `group` | text ∈ {history, road, context} | never | — | origin of the information |
| `feature_value` | float | the input is missing | raw input | e.g. `log_length` is log metres; shares 0–1 |
| `display_value` | text | `feature_value` is empty | — | human-readable value: metres, yes/no, %, mph |
| `shap_log` | float | never | log expected KSI | TreeSHAP attribution of the production model |
| `factor` | float > 0 | never | multiplicative | `exp(shap_log)`; the forecast equals the baseline × all 45 factors; the file keeps 5 |

`segment_explanations_top5000_v2.json`: `{model, explains, how_to_read, segments: {segment_id:
{rank, forecast, base, groups: {history, road, context}, top: [{f, label, value, display,
factor}]}}}`. `base` (0.0064) is exp of the model's mean log-forecast over its training rows,
a geometric-mean **baseline**, not the average forecast (the mean `blackspot_score` is 0.032).
Label it "model baseline", never "average segment". `groups` are the products of the factors of each group.

`segment_stability_v2.csv` (all ranks are national, 1 = highest):

| Column | Type | Empty when | Meaning |
|---|---|---|---|
| `segment_id` | text | never | join key (**ID**) |
| `rank` | int | never | production rank |
| `rank_median`, `rank_p05`, `rank_p95`, `rank_iqr` | float | never | median, 5th and 95th percentiles (interpolated) and IQR of the rank across **20** spatial-block bootstrap refits of the frozen model |
| `freq_top100`, `freq_top1000`, `freq_top5pct`, `freq_top10pct`, `freq_top20pct` | float 0–1 | never | share of the 20 refits placing the segment in that tier (5% steps; top 5% = 91,377) |
| `seed_rank_p05`, `seed_rank_p95` | float | never | rank range across 5 seed-only refits |
| `stability_class` | text | never | `robust top-1000` (≥ 90% of refits in the top 1,000), `borderline top-1000` (50–90%), `robust top-5%` (otherwise ≥ 90% in the top 5%), `variable` |
| `window_rank_min`, `window_rank_max` | int | never | best and worst rank across the 12 historical-window rankings |
| `rank_without_largest_collision` | float | rank > 1,000 | **simultaneous** definition: the rank when every top-1,000 segment loses its own largest 2023–25 collision at once. Do not use it for wording about a single segment |

`segment_single_event_sensitivity_v2.csv` (production top 1,000):

| Column | Type | Meaning |
|---|---|---|
| `segment_id` | text | join key (**ID**) |
| `rank` | int 1–1,000 | production rank |
| `forecast` | float | `blackspot_score`, 4 decimals (expected adjusted KSI, 2026+2027) |
| `forecast_without_largest_collision` | float | the production model's forecast with the segment's largest 2023–25 collision (by adjusted KSI) removed from its own history. Road and context are unchanged; no refit. **Can exceed `forecast`** (21% of segments; the model is not monotone in severity history) |
| `rank_without_largest_collision_one_at_a_time` | int | national rank if only this segment changed. **Use this for "without this collision" wording** |
| `rank_without_largest_collision_simultaneous` | int | equals `rank_without_largest_collision` in the stability file |
| `largest_collision_adj_ksi` | float | adjusted KSI of the removed collision |
| `single_event_flag` | bool | copied from the CSV |

None of the extension fields is null except where stated.

## 3. Score semantics

Verified from `ml/blackspot/features.py`, `models.py`, `outputs.py` and `ml/outputs/frozen_spec.json`.

### 3.1 What `blackspot_score` is

| Question | Answer |
|---|---|
| Quantity | **expected killed-or-seriously-injured casualties** on the segment. Casualties, not collisions; one collision can produce several |
| Severity scale | DfT **severity-adjusted** KSI: fatal casualties count 1, serious casualties count by DfT's adjustment probability. This removes the CRASH/COPA reporting drift (6% of casualties injury-based in 2015, 86% in 2025) |
| Horizon | **2026 and 2027 combined** (two-year total, not per year). Divide by 2 for a yearly figure |
| Inputs | collisions from **2023–2025** on the segment and nearby, plus OS road attributes. No traffic counts, no coordinates |
| Training | LightGBM with a Poisson objective, fitted on features from 2021–23 against the 2024–25 target (production cutoff 2025). The specification was frozen on development folds with cutoffs 2019–21, then tested once on the 2024–25 holdout |
| Frequency or rate | a **frequency** (expected count per segment per two years). It grows with segment length and traffic. It is **not** per vehicle-km; that is `ksi_per_100m_vkm_eb`, where available |
| Calibrated or ranking-only | an **expected count**, approximately calibrated in aggregate. On the 2024–25 holdout, Σforecast/Σobserved = 1.01, and observed/predicted by decile was 0.83–1.07 (0.97 in the top decile; `ml/reports/calibration_holdout.csv`). For a single segment, the actual count will scatter widely around the forecast (Poisson noise). Calibration of the 2026–27 forecast cannot be checked until DfT publishes 2027 data (autumn 2028), and national shocks move the level (COVID moved it between 0.77 and 1.15) |
| National total | Σ `blackspot_score` over all 1,827,550 segments = 57,991 expected adjusted KSI for 2026+2027. The scored network carries 97.7% of national adjusted KSI; private and service roads are not scored |

### 3.2 What it is not

- **Not per-vehicle risk.** Busy urban A roads dominate the top because many people use them. "Where is each journey most dangerous?" needs `ksi_per_100m_vkm_eb`, which exists only on M/A roads with a DfT count. "Worse than similar roads?" needs `eb_excess_ksi_history`. Show these in separate boxes.
- **Not a severity prediction**, and not a 0–100 score. It must not be rescaled into "danger" (§9).
- **Not causal.** Neither the score nor its explanations say what an intervention would achieve.

### 3.3 Comparability across versions

- **Within v2.0:** scores and ranks are comparable across segments.
- **v1 → v2:** not comparable. v1 was an in-sample fit of KSI collisions on crash-derived segments with different IDs.
- **v2 → a future release:** the unit (expected adjusted KSI casualties over two years) is comparable **if** the horizon and severity scale are unchanged. Ranks and levels will move with new data, a new training pair and possibly a new OS network. Compare by `segment_id` only when `release_manifest_v2.json` → `network.segmentation` names the same OS release. Never compare `rank` across releases as if it were a score.

### 3.4 Ranking and tie-breaking

`rank` is computed on the full-precision forecast of all 1,827,550 segments: sort by
`blackspot_score` descending, then `segment_id` ascending (byte order of the ASCII text),
then number 1, 2, 3, …. This was checked to reproduce every rank in the national table.
295,013 segments share their full-precision forecast with another, mostly segments with no crash
history, so the tie-break matters.

The **exported CSV rounds** the score (`%.6g`). Ranks must therefore be taken from `rank`. The JSON top-500
file keeps full precision. Recommended SQL: `ORDER BY rank`. If ties must be re-derived, use
`ORDER BY blackspot_score DESC, segment_id COLLATE "C" ASC` on full-precision values only.
The `"C"` collation gives byte order; a locale collation such as `en_US` can order
punctuation differently.

### 3.5 Precision of the rank

From `ml/reports/ranking_stability.md` (20 spatial-block bootstrap refits; screening-level
evidence, not a confidence interval):
- the top-1,000 **tier** is stable: all 100 production top-100 segments stay in the top 1,000 in ≥ 90% of refits;
- exact **positions** are not: adjacent ranks keep their order in about half of the refits;
- a gap of about 100 ranks is needed before the order holds two times in three.

Display the rank with `rank_p05`–`rank_p95` or the `stability_class`. Never use the rank alone
to prioritise segment #100 over #110.

## 4. Spatial conventions

### 4.1 Coordinate reference systems

| Field | CRS | Units | Notes |
|---|---|---|---|
| `lat`, `lon` (CSV, JSON) | WGS84, EPSG:4326 | degrees | segment midpoint, transformed from BNG with pyproj (`always_xy`) |
| GeoJSON geometry | WGS84, EPSG:4326 (RFC 7946 default; the file has no `crs` member) | degrees, 6 decimals | positions are **`[longitude, latitude]`** |
| `length_m`, `km_from`, `km_to` | measured in British National Grid, EPSG:27700 | metres / km | planar lengths. Do not recompute them from WGS84 degrees |
| `spatial_block` | derived from BNG easting/northing | 50 km squares | an integer code, not a geometry |

Store geometry as `geometry(LineString, 4326)` (or `geography`). For metric work in PostGIS,
transform to EPSG:27700 (`ST_Transform(geom, 27700)`), never measure in degrees. Do not
relabel a CRS: the files are 4326, and assigning 27700 without transforming would be wrong.

### 4.2 Geometry

- **Coverage.** Only the top 5,000 have line geometry (GeoJSON). Every row has a midpoint (`lat`, `lon`). For the other 45,015 rows, draw a point or nothing; never invent a line. Full geometry for any segment can be regenerated on the ML side from OS Open Roads (`network.load_segments`), on request.
- **Validity.** Every GeoJSON feature is a `LineString` with 2–69 positions, at least 2 distinct, all finite and inside Great Britain (validator). Lines are in stroke order and are not guaranteed to be simple: 3 of the 5,000 are closed loops (roundabouts, first position = last). Use `ST_IsValid` for `LineString` validity, not `ST_IsSimple`.
- **Absent or invalid geometry.** If a feature fails validation, keep the CSV row and drop only the geometry. Report it to the ML side. The current file has none.

### 4.3 Segment identifiers

`segment_id = <label>-<link>-<piece>`:
- `<label>` is the road number or class letter, as `road_id`; it can contain `(`, `)` and spaces (`A1(M)`, `M6 TOLL`);
- `<link>` is the first 12 hexadecimal characters (upper case, hyphens removed) of the OS Open Roads identifier of the stroke's first link, as in `os_first_link_id`;
- `<piece>` is the 0-based piece index, zero-padded to at least 2 digits (`-00`, `-103`).

Parse from the right: the last `-` separates `piece`, the one before it `link`. IDs are
deterministic and unique. All 2.7 M IDs rebuilt identically from shuffled input
(`ml/reports/network_determinism.json`). They are **stable for one OS Open Roads release** (2026-04)
and this segmentation code. A new OS release can split, merge or re-identify segments, so the
backend must treat the release as part of the key's validity. v1 IDs (`A23_run3_km0.5`) are
unrelated.

### 4.4 Short segments

Segments are about 500 m on M/A/B/C roads: each junction-to-junction stretch is cut into
round(L / 500) equal pieces, giving 333–750 m. Strokes shorter than 250 m stay as one short
segment, so many unclassified streets are short because the street is. Nationally, 1,120,398
segments are < 250 m and 269 are < 1 m. **None of the < 1 m segments is in the exported file**
(best rank 306,038), but 19 exported rows are < 20 m. Length is a model input, so short segments
get low forecasts. For per-vehicle rates the denominator is tiny, hence the 250 m display rule.

## 5. Optional extension contract

All extensions are keyed by `segment_id`. Every ID must exist in `road_segments_ranked_v2.csv`
with the same `rank` (validator). The base CSV is complete without them. A backend that
ignores `extensions/` loses nothing it currently uses.

| Need | Field(s) | Coverage | Rule |
|---|---|---|---|
| **SHAP explanation** | `segment_explanations_v2.csv`, `segment_explanations_top5000_v2.json` | all 50,015 exported rows (CSV); top 5,000 (JSON). 281,353 segments nationally have TreeSHAP | outside coverage, show "explanation not available", never zero factors. Label as "the model associates …", not "caused by". Factors explain the **production** model (verified to reproduce every stored score) |
| **Rank stability** | `segment_stability_v2.csv` | all 50,015 rows | show `rank_p05`–`rank_p95` and/or `stability_class`. Based on 20 refits: estimation variability only, not a confidence interval for future casualties |
| **Single-event warning** | base `single_event_flag`, `single_event_share`, `max_single_collision_ksi`; extension `segment_single_event_sensitivity_v2.csv` | flag: all rows; sensitivity: top 1,000 | always show the flag. For "without this collision" wording use `rank_without_largest_collision_one_at_a_time`. If `forecast_without_largest_collision ≥ forecast`, say the rank **does not require** the event, not that it is **independent** of it |
| **Exposure-adjusted rate** | base `ksi_per_100m_vkm_eb`, `aadf`, `exposure_available` | 132,899 M/A segments nationally; 30,179 exported rows | show only when `exposure_available` and `length_m ≥ 250` (`contract.per_vehicle_rate_for_display`). Otherwise "not available" with the reason. Never zero, never a proxy. Label it as a 2023–25 rate, in a separate box from the burden |
| **Data-quality / coverage warnings** | base `data_sufficiency`; global notes below | all rows | grey out or label `sparse` / `none`. The global notes go in a footer |

Global data notes for a footer or "about" page:
- scores cover 97.7% of national adjusted KSI; private and service roads are not scored, and 0.13% of KSI cannot be placed;
- the 2026 road network is applied to 2015–25 crashes, and < 0.5% of crashes fail to match;
- severity is DfT-adjusted because police reporting changed (CRASH/COPA);
- 2024–25 junction and special-conditions codes changed, so the v1 `pct_junction` is affected;
- exposure exists for M/A roads only (42.8% of national KSI).

## 6. Versioning and compatibility

### 6.1 Identifying a release

| Item | Where |
|---|---|
| Artefact version | `score_version` (every row; meta) and `release_manifest_v2.json` → `release` |
| Model | `score_model`; meta `model`, `frozen_spec_sha256`; manifest `model` |
| Training period | manifest `model.production_fold`: train features 2021–2023, train target 2024–2025 |
| Forecast horizon | `forecast_period` (rows), meta `forecast_years`, manifest `score.horizon_years` = 2 |
| History period | `history_period` (rows), meta `history_years` |
| Generation time | manifest `outputs_generated_utc`. The v2 forecast step records no timestamp, so this is the file modification time of the CSV, labelled as such. `manifest_created_utc` is when the manifest was written |
| Integrity | manifest `files[].sha256`, `rows`, `bytes` |
| Network release | manifest `network.segmentation` (OS Open Roads 2026-04) and `inputs.os_open_roads.sha256` |

**Production vs research.** The manifest lists exactly the production files (`role`: required
or optional). Anything else, including everything under `ml/`, is research, demo or legacy
(`not_for_loading`). The load job should refuse a file whose sha256 does not match the manifest.

### 6.2 Compatibility rules (from contract 1.0)

- **Within v2.x:** only additive changes, meaning new columns appended at the end and new optional files. Existing names, types, units and meanings do not change. Consumers must ignore unknown columns.
- **Any breaking change** (a renamed column, a changed unit or horizon, a new severity scale) gets a new `score_version` major number and **new file names** (`*_v3.*`). The v2 files are kept until the backend migrates.
- **A new OS Open Roads release** changes `segment_id` validity. It is announced in the manifest; it is not silently reused.

### 6.3 Migration notes (v1 consumers)

| v1 assumption | v2 reality | Migration |
|---|---|---|
| `segment_id` like `A23_run3_km0.5` | new network IDs | reload; no mapping exists, because segments differ |
| `blackspot_score` = KSI collisions | expected adjusted KSI **casualties**, 2026–27 | relabel in the UI |
| `future_ksi` filled (2022–23 outcomes) | empty | hide |
| `n_ksi`, `n_fatal` = collisions | unchanged meaning (collisions); casualties are in `n_ksi_casualties*` | none |
| `pct_junction` | same v1 definition, affected by 2024 coding | prefer `pct_junction_v2` |

### 6.4 Known gaps documented instead of changed

| Gap | Resolution in this contract |
|---|---|
| meta JSON has no generation timestamp or training period | `release_manifest_v2.json` (additive) |
| GeoJSON has no version or period | read them from the CSV or manifest |
| `rank_without_largest_collision` uses the simultaneous definition | documented here; one-at-a-time in a new optional file |
| CSV score precision | order by `rank` |
| no geometry beyond the top 5,000 | midpoints for the rest; ML can regenerate lines on request |

## 7. Suggested PostGIS tables (a suggestion; the schema belongs to the backend)

```sql
CREATE TABLE ml_release (
  release TEXT PRIMARY KEY,                 -- 'v2.0'
  frozen_spec_sha256 TEXT NOT NULL, forecast_period TEXT NOT NULL, history_period TEXT NOT NULL,
  outputs_generated_utc TIMESTAMPTZ, manifest JSONB NOT NULL);

CREATE TABLE road_segment_v2 (
  segment_id TEXT PRIMARY KEY, release TEXT NOT NULL REFERENCES ml_release,
  rank INTEGER NOT NULL UNIQUE, blackspot_score DOUBLE PRECISION NOT NULL CHECK (blackspot_score >= 0),
  location TEXT, road_id TEXT NOT NULL, road_class CHAR(1) NOT NULL, road_number TEXT, road_name TEXT,
  length_m DOUBLE PRECISION NOT NULL, n_crashes INTEGER NOT NULL, n_ksi INTEGER NOT NULL, n_fatal INTEGER NOT NULL,
  n_ksi_casualties_adjusted DOUBLE PRECISION NOT NULL, eb_excess_ksi_history DOUBLE PRECISION NOT NULL,
  exposure_available BOOLEAN NOT NULL, aadf DOUBLE PRECISION, ksi_per_100m_vkm_eb DOUBLE PRECISION,
  data_sufficiency TEXT NOT NULL CHECK (data_sufficiency IN ('sufficient','sparse','none')),
  single_event_flag BOOLEAN NOT NULL,
  midpoint geometry(Point, 4326) NOT NULL,          -- ST_SetSRID(ST_MakePoint(lon, lat), 4326)
  geom geometry(LineString, 4326),                   -- from the GeoJSON; NULL outside the top 5,000
  CHECK (exposure_available OR (aadf IS NULL AND ksi_per_100m_vkm_eb IS NULL)));
CREATE INDEX ON road_segment_v2 USING GIST (midpoint);
CREATE INDEX ON road_segment_v2 USING GIST (geom);

CREATE TABLE segment_explanation_v2 (segment_id TEXT REFERENCES road_segment_v2, contrib_rank SMALLINT,
  feature TEXT, label TEXT, "group" TEXT, feature_value DOUBLE PRECISION, display_value TEXT,
  shap_log DOUBLE PRECISION, factor DOUBLE PRECISION, PRIMARY KEY (segment_id, contrib_rank));
CREATE TABLE segment_stability_v2 (segment_id TEXT PRIMARY KEY REFERENCES road_segment_v2,
  rank_p05 DOUBLE PRECISION, rank_p95 DOUBLE PRECISION, freq_top1000 DOUBLE PRECISION,
  stability_class TEXT, window_rank_min INTEGER, window_rank_max INTEGER);   -- plus the other columns as needed
```

Loading notes:
- read empty cells as NULL;
- `True`/`False` are booleans;
- `aadf_count_point` is an integer written as a float (`123456.0`);
- keep `blackspot_score` as double precision;
- load the extension tables only after the base table.

## 8. API and UI rules (consolidated)

1. **Score label.** Show the score as "expected serious or fatal casualties, 2026–27 (two-year total)", not as "risk", "danger" or "predicted severity".
2. **Rank.** Show it with its range (`#rank_p05–#rank_p95`) or its `stability_class`; never as the only basis for comparing two segments.
3. **Rate box.** Keep burden and per-vehicle rate in separate boxes. Show the rate only under the §5 rule, labelled "2023–25". Otherwise say "not available" with the reason.
4. **Low history.** Grey out or label `data_sufficiency != "sufficient"`.
5. **Single events.** Label `single_event_flag` segments ("one mass-casualty collision dominates the history; not a road-design finding").
6. **Explanations.** Present them as associations of the production model, with "not available" outside coverage. Present no factor as a fix.
7. **Excess.** Present `eb_excess_ksi_history` as "above/below similar roads (2023–25)", a screening signal.

Suggested non-breaking endpoints (shapes in `extensions/README.md`):
`GET /segments?bbox=&limit=` (base fields), `GET /segments/{id}`,
`GET /segments/{id}/explanation`, `GET /segments/{id}/stability`. Return `404`, or an
explicit `"available": false`, for missing optional data; never return zeros.

## 9. The frontend

> **Phase 4 (2026-10-14).** A GB demo of the frontend now reads a verified subset of this release
> through a local data adapter. It is on branch `frontend-uk-demo`, uncommitted, in the local
> worktree `.worktrees/frontend-uk`; see `ml/reports/phase4_integration_status.md`.
> - **Score:** the 0–100 score is removed. Tiers are bands of `rank` (Top 100, Top 1,000, Top 1%, Below top 1%), and `blackspot_score` is shown with its units.
> - **Not produced:** fields this pipeline does not produce (landmarks, hourly profiles, last-incident dates) are not shown.
> - **Backend checklist:** what the frontend needs from the backend is listed in `frontend/BACKEND_INTEGRATION.md` on that branch.
>
> The table below is kept as the record of the original fixture.

The `frontend-v1` branch renders a hand-written fixture (`frontend/src/data/blackspots.js`) with
a 0–100 `score`, risk tiers, incident splits and an hourly profile, for locations outside GB.
None of it comes from this pipeline. Mapping it to the v2 outputs needs a team decision. ML's
position:

| Fixture field | v2 source | Note |
|---|---|---|
| `id` | `segment_id` | |
| `name` | `location` | |
| `lat`, `lng` | `lat`, `lon` | |
| `score` (0–100) | **no equivalent** | do not rescale `blackspot_score` into a danger index. If a 0–100 display is unavoidable, use a **national percentile of `rank`**, labelled as such, or the stability tiers |
| `incidents`, `fatal`, `serious`, `slight` | `n_crashes`, `n_fatal`, `n_ksi − n_fatal`, `n_crashes − n_ksi` | collisions by collision severity, 2023–25 |
| `roadClass`, `roadType` | `road_class` / `road_id`, `form_of_way` | |
| `speedLimit` (km/h) | `speed_max` is **mph** and only the maximum at recorded collisions | not a posted limit for the segment |
| `factors` | top factors from `segment_explanations_v2.csv` | model attributions, not "contributing factors" in the STATS19 sense |
| `lastIncident`, `hourlyProfile`, `landmarks` | not produced | ML can add them as a v2.x extension if needed |

## 10. Validation and tests

```bash
.venv/Scripts/python ml/audit/validate_contract.py                                  # the real data/v2 files (~3 s)
.venv/Scripts/python ml/audit/validate_contract.py ml/tests/fixtures/integration    # the fixture
.venv/Scripts/python -m pytest ml/tests/test_integration_contract.py
.venv/Scripts/python ml/audit/release_manifest.py                                   # rewrite manifest + schema
```
The fixture (`ml/tests/fixtures/integration/README.md`) has 13 real segments, chosen to cover:
- high- and low-ranked segments;
- no and sparse history;
- the single-event segment;
- missing and present exposure, and a short segment with exposure;
- a full-precision tie;
- explanation coverage with and without the map JSON.

A backend test can load the fixture and expect the same results.
