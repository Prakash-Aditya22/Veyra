# Data quality: STATS19 2015–2025, OS Open Roads, DfT AADF

Generated evidence lives beside this file:
- `data_quality.json`: overlap checks, join consistency, coordinate checks, counts by year
- `data_quality_by_year.csv`: severity and reporting regime by year
- `data_quality_injury_based_by_force.csv`: CRASH/COPA adoption by police force, 2022–25
- `data_quality_unknown_codes_by_year.csv`: missing or unknown share per field and year
- `network_summary.json`, `snap_summary.json`, `snap_stats19_class_vs_os_class.csv`: network and crash assignment
- `../raw/manifest.json` (not in git): URL, byte count, SHA-256 and validation note for every download

Regenerate with `.venv/Scripts/python ml/pipeline.py data snap coverage`.

## 1. Sources and provenance

| Source | Files | Validation on download |
|---|---|---|
| DfT STATS19, per year | collision / casualty / vehicle 2021–2025 (15 files, ~255 MB) | byte count = Content-Length; last record has the header's field count (all 32–44 fields); SHA-256 recorded |
| DfT STATS19 casualty 1979–latest | 1 file, 989 MB, covers through 2025 | same; 24 fields, last record complete |
| v1 extract `stats19_recent.csv` | collision grain 2015–2023, built by `build_recent.py` in Aug 2025 | reused for 2015–2020 only; compared below |
| DfT data guide 2025 (xlsx) | code lists + official 2011→2024 code conversion | zip CRC |
| DfT road traffic AADF | `dft_traffic_counts_aadf.zip`, 2000–2025, 600,551 rows | zip CRC |
| OS Open Roads (2026-04 release, OGL v3) | GB shapefile, 52 tiles of 100 km, 606 MB | publisher MD5 matched; zip CRC |

The per-year collision files for 2021–2025 have **byte-identical headers** (44 fields), so 2024 and 2025 use the same schema as 2021–23.

## 2. Joins and grain

| Check | Result |
|---|---|
| v1 extract vs current DfT release, 2021–2023 | identical: same 311,349 collision IDs, 0 severity changes, 0 location changes |
| 1979–latest casualty file vs per-year casualty files, 2021–2025 | identical row counts every year |
| Casualty key uniqueness | `(collision_index, casualty_reference)` is **not** unique: collision `201604ED16270` reuses reference 2 for two different people (different vehicle, age, sex). Key is `(collision_index, vehicle_reference, casualty_reference)`, which is unique. |
| Casualties aggregated before join | yes; the join is asserted one-to-one (`validate="one_to_one"`) |
| Σ casualties per collision = `number_of_casualties` | **100.000%** of 1,251,830 collisions |
| Worst casualty severity = `collision_severity` | **100.000%** |
| Collisions without casualty rows / casualty rows without a collision | 0 / 0 |

## 3. Coordinates and CRS

- All geometry work is in British National Grid (EPSG:27700) metres. OS Open Roads ships in EPSG:27700 (checked from the `.prj`).
- 2021–2025 collisions carry DfT's published OSGR eastings/northings. For 2015–2020 the v1 extract kept only latitude/longitude, which are projected with `pyproj` (EPSG:4326→27700). Against published OSGR on a 50,000-row sample, the projection error has median **0.24 m**, p99 **2.5 m** and max 4.2 m, negligible against 500 m segments and a 50 m snap radius.
- 203 collisions (0.016%) have no usable coordinates; none fall outside the GB extent.

## 4. Severity and the reporting-regime change

Police forces moved from officer judgement to injury-based severity (CRASH/COPA) force by force. The casualty share recorded under injury-based reporting:

| Year | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Injury-based share | 5.9% | 35.1% | 36.8% | 36.4% | 43.7% | 46.5% | 51.7% | 54.6% | 55.8% | **79.1%** | **86.4%** |
| Reported KSI casualties | 23,811 | 25,602 | 26,409 | 27,058 | 27,125 | 21,562 | 24,921 | 27,531 | 27,654 | 27,642 | 29,296 |
| Adjusted KSI casualties | 32,176 | 31,119 | 30,184 | 30,643 | 29,747 | 23,217 | 26,397 | 28,926 | 28,973 | 28,876 | 29,918 |
| Adjusted ÷ reported | 1.351 | 1.216 | 1.143 | 1.132 | 1.097 | 1.077 | 1.059 | 1.051 | 1.048 | 1.045 | 1.021 |

Reported KSI *rises* 23% from 2015 to 2025 while DfT's adjusted series *falls* 7%. The reported rise is mostly a recording artefact. Large forces switched **inside** the forecast-validation window: the Metropolitan Police went from 0.2% to 99% injury-based in 2024, Thames Valley and Hampshire partly in 2025, Cleveland and Derbyshire in 2024–25. In 2025 these forces were still below 50% injury-based: Merseyside, North Yorkshire, Lincolnshire, Thames Valley, Hampshire, North Wales, Gwent and South Wales.

**Consequences for the design.**
1. **Primary target = DfT severity-adjusted KSI casualties.** A fatal casualty counts 1. Every other casualty counts DfT's modelled probability that injury-based reporting would have recorded it as serious (`casualty_adjusted_severity_serious`, exactly 0/1 for records already injury-based). This is the series DfT uses for comparisons over time. It keeps a London segment's 2024–25 target from jumping because the Met changed its recording system.
2. Reported KSI casualties and KSI collisions are run as **secondary targets** on the final holdout (sensitivity).
3. History features include adjusted KSI. They describe the past, so they cannot reveal the future target. The adjustment fields never describe the collision being predicted.
4. The severity classifier keeps only collisions whose casualties were all injury-based, so the label means the same thing in training (2022–23) and test (2024–25) years (`severity.py`).

DfT's adjustment is itself a model. Adjusted counts are estimates and are non-integer; the count models used (Poisson and NB2 likelihoods, LightGBM Poisson loss) accept real-valued targets.

## 5. Code-list changes and fields that are not comparable across years

The 1979–latest release re-coded history to the 2024 format, so `junction_detail`, `pedestrian_crossing` and `carriageway_hazards` use the same codes in every year. Three problems remain:

| Field | Problem | Handling |
|---|---|---|
| `junction_detail_historic` | blank (−1) for **59% of 2024 and 87% of 2025** records | not used. The junction flag uses 2024-format `junction_detail` ∈ {13,16,17,18,19} or `road_type` = 1 (roundabout), both coded consistently 2015–2025 |
| `junction_detail` = 0 | DfT's official conversion folds historic roundabout (1), mini-roundabout (2) and slip road (5) **into 0 "not at junction"** | roundabouts recovered via `road_type`; SHAP label states the merge |
| `junction_control` = −1 | the guide labels −1 "data missing", but in the data it occurs almost only where `junction_detail` = 0 "not at junction": 99.8% of −1 rows in 2015, 98.5% in 2023 (43,115 of 43,795), 97.0% in 2025. It covers 40–44% of records in every year | treated and labelled as "not at junction (coded −1)", not as unknown |
| `special_conditions_at_site` | "unknown" jumps from ~2% (2015–2022) to **61% (2024) and 87% (2025)** with the revised STATS19 specification | excluded from the severity model |
| `junction_detail` −1/99 | unknown rises from 2.3% (2023) to 6.9–8.0% (2024–25) | kept; small drift; flagged in SHAP |
| `pedestrian_crossing`, `carriageway_hazards` | unknown 3–7% in 2023–25 vs ≤3% before | kept; flagged |
| `local_authority_district` | −1 for every record since 2019 (field discontinued) | not used |

Unknown shares for each field and year are in `data_quality_unknown_codes_by_year.csv`.

## 6. Are 2024–2025 usable?

Yes, with the conditions above. Same schema; collision and casualty files complete and consistent; locations and road coding stable (crash-to-network assignment 99.88% in 2024 and 99.87% in 2025 vs 99.5–99.8% earlier). Severity is comparable **only on the adjusted scale**, or within injury-based records. As-reported KSI in 2024–25 is inflated relative to earlier years in the forces that switched. 2024–25 therefore serves as the **final, untouched holdout target** (cutoff 2023), and 2023–25 is the history window for the production forecast of 2026–27.

## 7. Road network (OS Open Roads 2026-04)

- 3,967,825 links read; 6,748 appear in two adjacent tiles with the same identifier and are de-duplicated; 3,961,077 kept.
- 2,283,855 junction-to-junction strokes; **2,698,893 segments**; 580,182 km.
- Scored classes: M, A, B, C ("Classified Unnumbered"), U (Unclassified), N (Not Classified): **1,827,550 segments, 435,261 km**. The OS "Unknown" class (871k segments, 145k km of private/service access roads) is kept for crash assignment, so crashes on it are not forced onto nearby public roads, but it is not scored.
- Segment length: A/B/C/M roads have 92–97% of their length in 333–750 m segments. Unclassified streets are often shorter between junctions (median segment 126 m across all classes). Length is a covariate in every model, and capture is also reported per share of network km.
- Dual carriageways are mostly drawn once ("Collapsed Dual Carriageway", 11,984 km). 1,121 km are drawn as two carriageways and segmented per carriageway.
- The network is a **2026 snapshot** applied to 2015–2025 crashes. Assignment rates by year (99.5% in 2016 to 99.9% in 2024) show the anachronism costs < 0.5% of crashes. Roads built after 2015 have artificially short histories.

## 8. Crash-to-segment assignment

- **99.72%** of 1,251,830 collisions are assigned within 50 m (3,267 with no centreline within 50 m; 203 without coordinates). Median distance 2.8 m, p90 10.0 m, p99 27.1 m.
- Match type: 57.3% exact road number, 1.1% the second road's number, 32.1% class match (C/U roads, which carry no number), 8.0% near class, **1.6% fallback** (nearest road ignoring a contradicting police road code).
- Police road class vs OS class (row = STATS19 code): M → M 98.4%; A → A 98.1%; B → B 96.6%; C → C 69.3% (U 27.5%); U → U 70.4% (C 18.5%, private/service 5.8%). The C/U boundary differs between police coding and OS classification. This is a known STATS19 limitation and affects class-level reporting, not totals.

## 9. AADF (traffic exposure)

- Major roads (M, A): each link between major junctions has a counted or DfT-estimated AADF every year (~17,900 count points/year). Minor roads (B, C, U): only ~4,400 sample count points per year nationally, so **exposure is attached to M/A segments only**.
- Match rule: same road number, within max(1 km, ½ link length + 0.5 km) of the segment midpoint. AADF is averaged over the history window only.
- Coverage on the 2021 development fold: 132,024 M/A segments (47,249 km) have AADF in both windows. They carry **43.8% of national adjusted KSI** in 2022–23. Holdout coverage is in `coverage_analysis.md`.
- Estimated (not counted) AADF values are kept and their counted share is reported per segment (`aadf_share_counted`).
