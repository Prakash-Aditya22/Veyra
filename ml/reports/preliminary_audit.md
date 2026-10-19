# Preliminary audit: v1 blackspot and severity pipeline

*Audit of commit `8f13aa4` on branch `ML` (working tree clean), 2026-10-13.
Numbers come from `ml/audit/audit_v1.py`, which writes
`ml/reports/audit_v1_evidence.json`. Run it with
`.venv/Scripts/python ml/audit/audit_v1.py`.*

## 0. Baseline state and reproduction

| Item | Finding |
|---|---|
| Branches | `ML` (this work), `main` (README only), `frontend-v1` (React UI). **No backend branch exists.** |
| Frontend consumption | `frontend-v1` renders a hand-written demo fixture (`frontend/src/data/blackspots.js`, Indian city coordinates). It does not read any ML output yet. The binding contract is the schema documented in `ml/README.md` / `handoff/README.md` (`road_segments_ranked.csv`, `road_segments_top500.json`, the `road_segment` SQL table). |
| v1 reproduction | Rerunning `ml/road_segments.py` in an isolated directory with today's pinned packages reproduces `data/road_segments_ranked.csv` **bit-for-bit**: 45,014 identical segment IDs, max \|Δscore\| = 0.0. It also reproduces the published held-out capture (8.02 / 23.02 / 34.93 / 50.40 %). |
| Raw data | `stats19_raw/`, which `build_recent.py` needs, is not in the repository, and the script does **not** download anything despite README/CLAUDE.md. Only the derived `stats19_recent.csv` (2015–2023, collision grain) was present. |

## 1. What v1 actually does

1. **Data.** `build_recent.py` reads three local "1979–latest" files, keeps 2015–2023, drops 10 severity-derived fields, aggregates vehicle and casualty rows to collision grain (correct grain, no fan-out) and writes `stats19_recent.csv`. **Casualty severity is dropped entirely**, so the extract cannot count KSI *casualties*. OSGR eastings/northings are also dropped.
2. **Segments.** `road_segments.py` keeps crashes on numbered roads (class M/A(M)/A/B/C with number > 0) in **2019–2023**. It keeps roads with ≥ 60 crashes, splits each road number into "stretches" (kNN graph, 10 km gap) and builds an MST over the crash points. Chainage is the geodesic distance from one end of the MST diameter, cut into 500 m bins. Segment ID = `road_run_km`.
3. **Target and features.** Features are 22 aggregates of 2019–2021 crashes per segment, including `run`, `km_from`, `lat`, `lon`, `lat_min…lon_max` and `n_years`. The target is the count of **KSI collisions** in 2022–2023.
4. **Model.** One LightGBM Poisson regressor, trained on a random 70% of segments, **then used to score all segments**. Severity models are LightGBM classifiers on a random 80/20 split of 2022–2023 collisions. SHAP is computed on the 236-feature "explanatory" classifier.
5. **Genuine out-of-sample results.** Only the 30% test-segment capture figures, and even those are subject to the spatial and eligibility leakage below. The 70% training-segment scores shipped in the ranking are in-sample.
6. **Consumed outputs.** `data/road_segments_ranked.csv`, `data/road_segments_top500.json`, `data/road_segments_meta.json`, `ml/models/severity_deployable_model.joblib`, `ml/shap/*`, `ml/demo/blackspot_map.html`.
7. **Archive.** It holds real negative results worth keeping. The cascade was superseded by threshold tuning. SVM and neural nets lost to GBMs. A 2×2 ablation showed framing vs features. A validation-strategy study showed random vs spatial vs temporal splits on 2009–10 data. The 0.379 vs 0.729 result shows that balancing before the split inflates scores. One archived idea is invalid: `blackspot_excess_risk.py` treats historical crash counts as "exposure" in a Poisson offset (see D13).

## 2. Confirmed defects

Severity: **Critical** means it invalidates a headline claim. **Major** means it materially biases results or misleads users. **Minor** is hygiene.

| # | Defect | Location | Severity |
|---|---|---|---|
| D1 | Road eligibility uses target-period crashes | `road_segments.py:62,70–71` | Critical |
| D2 | Segment geometry/chainage built from target-period crash coordinates | `road_segments.py:168–181` | Critical |
| D3 | Shipped scores are in-sample fits of the outcome shown beside them, and they forecast a period already observed | `road_segments.py:216–222,237–246` | Critical |
| D4 | Target is KSI *collisions*, documented as KSI *casualties* | `road_segments.py:66,206`; README | Major |
| D5 | Random split of neighbouring segments (spatial leakage); coordinates as features | `road_segments.py:216` | Major |
| D6 | Crash-count baseline comparison decided by arbitrary tie-breaking, one split, no uncertainty | `road_segments.py:230–235` | Major |
| D7 | 36.8% national coverage; C/unclassified roads absent; zero-history road excluded | `road_segments.py:64,71,186` | Major |
| D8 | Identifier and artefact features (`run`, `km_from`, crash bounding box) | `road_segments.py:187–199,213` | Major |
| D9 | MST chainage folds branches onto the main line; stitching is order-dependent | `road_segments.py:120–163` | Major |
| D10 | Severity thresholds tuned on in-sample predictions | `severity_final.py:111–114,136–147`; `severity_deployable.py:74–76` | Major |
| D11 | SHAP explains the non-deployable model; decode maps outdated; "unknown" levels not handled | `severity_final.py:46–65,166,185–222` | Major |
| D12 | Severity validated only by a random split inside 2022–2023 | `severity_final.py:86`; `severity_deployable.py:61` | Major |
| D13 | Archived "excess risk" treats crash counts as traffic exposure | `archive/scripts/blackspot_excess_risk.py` | Major (archive only) |
| D14 | Reproducibility and engineering (paths, downloads, folders, pins, warnings, tests) | all scripts | Minor–Major |
| D15 | Documentation claims that are false for the current code | `ml/README.md`, `CLAUDE.md`, `road_segments_meta.json` | Major |

### D1. Eligibility depends on the future

`df` is filtered to `BUILD + FUTURE` (2019–2023) **before** `counts = df.road_id.value_counts()` and the `MIN_CRASHES = 60` rule. **398 of the 1,027 eligible roads (39%)** reach 60 crashes only because 2022–23 crashes are counted. With 2019–2021 counts only, 629 roads qualify. So which roads appear in the evaluation population depends on the outcome being predicted. Roads that turned out to have many crashes in 2022–23 are selected in.

### D2. Segment geometry depends on the future

`chainage()` is run on every crash of the road in 2019–**2023**. MST shape, stretch membership (`run`), the chosen MST end (chainage origin) and therefore every 500 m boundary and every segment ID move when 2022–23 crash points are added. A forecast made at the end of 2021 could not have produced these segments.

### D3. In-sample scores shipped as forecasts

The model is fitted on `future_ksi` (the 2022–23 outcome) of the 70% training segments. It then predicts **every** segment, and those predictions are written as `blackspot_score` next to `future_ksi`.

| Population | n | Spearman(score, 2022–23 KSI) | Poisson deviance | top-20% capture |
|---|---|---|---|---|
| Training segments (in-sample) | 31,509 | 0.550 | 0.646 | **63.0%** |
| Test segments (held out) | 13,505 | 0.363 | 0.853 | **50.4%** |

**77% of the top-500 and of the top-100** shipped segments are training segments whose score was fitted to the 2022–23 outcome printed beside them. Example: rank 17, A653 km 6.5–7.0, has 16 past crashes and 3 past KSI, scores 6.70 and had 10 future KSI. The ranking also forecasts 2022–23, which is already observed. No model maps the latest available history to an unobserved period.

### D4. Wrong outcome unit

`is_ksi = Accident_Severity != "Minor"` is a collision flag, and `future_ksi` sums it, so the target counts **KSI collisions**. The README and CLAUDE.md say "expected killed-or-seriously-injured **casualties**". Nationally in 2022–23 there were 49,895 KSI collisions and 55,185 KSI casualties, a ratio of 1.106 with large variation by road type (multi-occupant crashes on fast roads). The v1 extract dropped casualty severity, so casualties could not have been counted.

### D5. Spatial leakage

`train_test_split` assigns adjacent 500 m bins of the same road at random. Neighbours share traffic, junctions and police reporting. Exact coordinates (`lat`, `lon`, bounding box) and `km_from` let the model look up its neighbours' outcomes. The 50.4% test capture is therefore an interpolation result, not a generalisation result.

### D6. Fragile baseline comparison

Held-out set, top 20% = 2,701 segments. The crash-count cut falls at `n_crashes = 4`, where **905 segments are tied**, and 43% of test segments have exactly one crash.

| Score | top 20% capture |
|---|---|
| v1 model | 50.40% |
| Crash count, v1-reported (`np.argsort` order) | 49.35% |
| Crash count, **expected under random tie-break** | 49.51% |
| Crash count, worst / best tie-break | **47.29% / 53.76%** |
| KSI count, worst / best tie-break | 32.2% / 56.4% |

The model's margin (+0.9 points) is smaller than the tie-breaking range of the baseline (6.5 points). A road-clustered bootstrap of the difference gives +0.85 points, 95% CI [+0.05, +1.73]. That is barely positive, and it is computed under the leaky design (D1–D5), which favours the model.

### D7. Coverage

National 2022–23 KSI collisions (GB): 49,895.

| Population | Share of national KSI collisions |
|---|---|
| Numbered roads (M, A(M), A, B, numbered C) | 61.2% |
| v1-eligible roads (≥ 60 crashes, D1) | 45.6% |
| **Scored segments** (≥ 1 crash in 2019–21) | **36.8%** |
| v1 held-out test segments | 10.9% |
| C + unclassified roads (not represented) | 38.8% |

The 10,042 chainage bins with no 2019–21 crash are not scored at all, so the evaluation population is conditioned on history. It omits road that had no crash before but did after, exactly the cases a history-only ranking misses.

### D8. Feature validity

- `run` is the label `connected_components` assigns to a stretch (0–50). Its order is arbitrary, it changes when data change, and it carries no road property.
- `km_from` is distance from whichever MST end the double sweep picked, so the direction is arbitrary. With `run` and `lat/lon` it works as a location key.
- `lat_min/lat_max/lon_min/lon_max` describe the spread of crash points, not the road.
- `lat`, `lon` are the centroid of crashes, not of the road. They may be legitimate regional signal, but that needs a spatially blocked ablation (done in v2).

### D9. Chainage geometry

The MST spans branches: slip roads, both carriageways of a dual carriageway, spurs and junction arms that carry the same number. Points on a branch receive a chainage equal to their tree distance from the origin, so physically separate places can share a 500 m bin. For roads with > 4,000 crashes, kNN components are stitched in label order (`c-1` to `c`), not to their nearest component. Chainage is acknowledged to be inferred from crash points, not surveyed. That is acceptable as an approximation, but it cannot be stable.

### D10. In-sample threshold tuning

The comment says "threshold chosen on training data only". In fact `tr_oof = m_ksi.predict_proba(X.iloc[tr])` gives **in-sample** probabilities of a 600-tree, 127-leaf model, which are over-confident. The three-class multipliers are tuned the same way. The deployable script repeats this. These are not out-of-fold predictions.

### D11. SHAP and decoding

- SHAP (`global_shap_importance.csv`, `per_level/*`, `subcategory_ranking.csv`) explains **`m_ksi`, the 236-feature explanatory model**. Its top global feature is `k_casualty_type_9` (a car occupant was a casualty), a post-crash fact. The README nevertheless offers these tables as the "why is this dangerous" panel next to the *deployable* model.
- `junction_detail` in this extract uses the **2024-format** DfT code list (0, 13, 16, 17, 18, 19, 99). The decode map uses the historic list, so **every junction level except 0 shows as a raw number** (13, 16, 17, 18, 19) in the shipped tables. DfT's official 2011→2024 conversion (data guide 2025, sheet `2011_to_2024_conversion`) maps historic 1 (roundabout), 2 (mini-roundabout) and 5 (slip road) **into 0 "Not at or within 20 metres of junction"**. The label on 0 is therefore DfT's own, but the level contains 21,000+ roundabout, mini-roundabout and slip-road crashes in 2022–23. Reading it as "away from junctions" is wrong (roundabouts are now identified via `road_type = 1`). The same semantics affect v1's `pct_junction` (`junction_detail != 0`), which counts roundabouts as non-junction.
- `junction_control`: `-1` (17,689 rows in the SHAP sample; "not at a junction" under the revised coding) is shown as "-1". `9` (unknown) has mean SHAP −0.23 and alone sets most of that feature's range.
- `local_authority_district` is −1 for every 2022–23 row: a constant column in the deployable feature list.
- `police_force`, `latitude`, `longitude` and `first_road_number` are in the deployable model with no test of whether they help or merely encode recording practice.

### D12. Severity validation

Train and test are random rows from the same two years, with the same roads and forces on both sides. There is no temporal holdout (e.g. predict 2024–25) and no spatial holdout, and no calibration measure (Brier, reliability).

### D13. Archived "excess risk"

`archive/scripts/blackspot_excess_risk.py` uses `log(n_crashes)` as the Poisson offset and calls it exposure. Historical crash counts are an outcome, not exposure. Dividing by them targets "KSI per crash" (a severity ratio) and puts regression-to-the-mean noise in the denominator. It must not be cited as an exposure-adjusted result.

### D14. Reproducibility and engineering

- `build_recent.py` reads `stats19_raw/` but **downloads nothing**. Docs say it downloads. It has no truncation check (the CLAUDE.md warning was not implemented) and no hashes or provenance.
- All scripts use paths relative to the current directory, while docs disagree: README says run from `ml/`, CLAUDE.md says the repo root. Outputs land in the CWD and were moved by hand into `data/`, `ml/models/` and `ml/shap/`.
- `severity_deployable.py` writes to `severity_outputs/` but only `severity_final.py` creates it.
- `warnings.filterwarnings("ignore")` is applied globally in every script.
- `requirements.txt` uses `>=` pins only. There are no tests and no `main` guards (importing a script runs it).
- `road_segments_meta.json` says "kNN-graph geodesic chainage", but the code uses an MST.

### D15. Documentation that no longer matches the code

- "Segments built from 2019–2021 crashes" is false. They are built from 2019–2023 (D1, D2).
- "Validated against 2022–2023 crashes the model never saw" is true only for the 30% test segments, and those segments' neighbours were trained on (D5).
- "Keep the severity model … as an input to `blackspot_score`, where SHAP ranked it #7 and #10" is false. The current segment model has no severity input; that was an archived model.
- "Expected KSI casualties" is false; v1 counts KSI collisions (D4).

## 3. Baseline performance (v1 protocol, reproduced)

Protocol: features from 2019–2021, target = KSI collisions 2022–2023, random 70/30 split of segments, test n = 13,505. Capture denominator = KSI collisions on test segments, which is 10.9% of the national total.

| Score | top 1% | top 5% | top 10% | top 20% |
|---|---|---|---|---|
| v1 LightGBM | 8.02 | 23.02 | 34.93 | 50.40 |
| Crash count (expected tie-break) | 7.42 | 22.99 | 34.45 | 49.51 |
| KSI count (expected tie-break) | 6.68 | 18.45 | 26.93 | 38.34 |

## 4. What to preserve

- **Collision-grain aggregation in `build_recent.py`.** It is correct (verified in v2: casualty count equals `number_of_casualties` for 100% of collisions). The leakage drop list and the assert also stay.
- The **2022–23-only severity window** and its reasoning. It is confirmed by the severity-share trend and by DfT's adjustment.
- **SHAP ranked by between-level spread** rather than mean |SHAP|, and **police force excluded as a cause**.
- The **deployable vs explanatory distinction** and its honest framing.
- **Poisson-type losses** for counts, and stating the crash-count baseline next to every model.
- **The archive.** The negative results are real (D13 is reclassified, not deleted).
- All v1 artefacts (`data/road_segments_*`, `ml/models`, `ml/shap`, the demo map, `handoff/`, the zip) stay untouched. v2 writes versioned files beside them.

## 5. Prioritised implementation plan

1. **Data layer.** Download the official DfT files with completeness checks and a provenance manifest. Rebuild a canonical collision table for 2015–2025 with casualty-level outcomes aggregated before the join: reported and DfT-adjusted KSI casualties, plus KSI collisions. Use BNG coordinates throughout.
2. **Segmentation independent of outcomes.** Cut OS Open Roads centrelines into ~500 m pieces along junction-to-junction road strokes, with deterministic IDs and coverage of all road classes. Snap crashes to the nearest compatible centreline within 50 m, one segment per crash.
3. **Prospective protocol.** Use rolling origins with a 3-year history and a 2-year target: development folds with cutoffs 2019, 2020 and 2021, and a frozen **final holdout with cutoff 2023 → target 2024–25**. Features, AADF and eligibility come from history years only. The model is trained on the previous history→target pair and applied to the latest history.
4. **Spatial validation.** Hold out blocks of 50 km × 50 km on the final fold, with a cluster (block) bootstrap for every CI.
5. **Models.** Compare historical-count baselines (tie-aware), Poisson GLM, NB2 GLM (SPF), Empirical Bayes (Hauer) with the SPF prior, and LightGBM, all on the same population. Ablate coordinates, road attributes, history and exposure.
6. **Exposure.** Attach AADF to M/A segments with a same-road-number match, an exposure SPF with a vehicle-km offset, a rate per 100 M vehicle-km, and EB excess KSI. Report coverage explicitly.
7. **Severity.** Temporal holdout (train 2022–23, test 2024 for tuning, 2025 final) plus a spatial holdout, OOF thresholds, calibration, deployable-only SHAP, revised-code decode maps, and an unknown-level audit.
8. **Outputs.** v2 files with every legacy column, plus forecast period, version, coverage flags, EB/excess estimates and AADF where valid. v1 files are kept as they are.
9. **Engineering.** Pinned `.venv`, anchored paths, `main` guards, logging, atomic writes, and a pytest suite for aggregation, leakage, geometry and metrics.
