# ML: road blackspot ranking for Great Britain (v2)

v2 replaces the v1 pipeline after an audit found that v1's headline results
leaked future information (`reports/preliminary_audit.md`). v1 files are
untouched (`data/road_segments_*`, `models/`, `shap/`, `demo/blackspot_map.html`,
`README_v1.md`). v2 writes beside them.

**What it produces**

| Deliverable | File(s) |
|---|---|
| Expected KSI casualties per ~500 m segment, 2026–27, for 1.83 M GB road segments | `../data/v2/road_segments_ranked_v2.csv` (top 50k + all well-observed), `ml/outputs/road_segments_v2_full.parquet` (all, regenerable) |
| Segment geometry (real OS Open Roads centrelines) | `../data/v2/road_segments_top5000_v2.geojson` |
| Excess-over-similar-roads (Empirical Bayes) and exposure-adjusted rate (M/A roads) | columns in the files above |
| Deployable severity model + SHAP | `outputs/severity_v2/` |
| Evidence | `reports/*.md`, `reports/*.csv` |
| Map demo (double-click) | `demo/blackspot_map_v2_r2.html` (configurable basemap; the original `demo/blackspot_map_v2.html` is kept unchanged, see "Demo maps: basemap") |

## Results (headline)

**Primary result: final holdout.** The model specification was frozen on
2015–2023 data (spec `b9487674e4f1`), then used once to forecast **2024–25**
from 2021–23 history. Score = expected DfT severity-adjusted KSI casualties
per segment over two years. Selected model: LightGBM (Poisson loss) on crash
history, OS road attributes and network context. Capture = share of the
population's 2024–25 KSI in its top-ranked segments. CIs are 50 km block
bootstrap.

| Population (share of national KSI) | Top 10% / 20% of segments: **model** | Crash counts | Empirical Bayes | Past KSI counts |
|---|---|---|---|---|
| All scored segments, 1.83 M (97.7%) | **70.8 / 85.8** | 58.8 / 63.4 | 67.4 / 83.1 | 41.8 / 48.2 |
| Numbered roads M/A/B (61.2%) | **41.6 / 57.7** | 39.3 / 53.4 | 36.7 / 53.9 | 31.1 / 47.3 |
| Segments with ≥ 1 crash in 2021–23 (56.9%) | **39.4 / 56.2** | 36.9 / 51.2 | 33.5 / 50.5 | 27.8 / 38.0 |

- Nationally the model captures **+12.4 points more** future KSI in its top 10% than ranking by past crash count [95% CI 8.1, 16.4]. Most of that comes from ranking road with **no** recent crash (91% of segments, which a count cannot separate).
- Where crash history exists, the gain is **+2.3 to +2.5 points** (numbered roads [1.4, 3.7]; segments with history [1.9, 3.6]). That is consistent across five time folds and every road class, but modest. **Crash history remains the dominant signal.**
- The result holds for **future periods** (five rolling origins, 2020–21 to 2024–25 targets) and for **unseen regions**: models refitted without a region lose ≤ 0.4 points.
- Ranking by past **KSI** count is the weakest method (it is noisier than all-crash counts). Its top 500 recorded only 50% of their past KSI in the next period (regression to the mean). The model's own top 500 delivered 91% of their forecast.
- Total calibration on the holdout: Σforecast / Σobserved = 1.01. In earlier folds COVID moved it between 0.77 and 1.15 without changing the ranking.
- **Traffic exposure (AADF)** exists for M/A roads only (42.8% of national KSI). It slightly improves count accuracy, does not change the top of the ranking, and changes the *interpretation*: the top-100 by burden and by KSI per vehicle-km share 4% of segments.
- **Severity model** (deployable: road, environment, time only): ROC-AUC **0.581** [0.572, 0.591] on untouched 2025 data. That is weak. v1's model scored 0.626 on 2025, not the 0.658 it reported.

Full evidence: `reports/final_audit.md` (PASS/FAIL per requirement),
`reports/robustness.md`, `reports/summary_tables.md`,
`reports/model_comparison.csv`, `reports/coverage_analysis.md`.

## Phase 2 research (no production change)

The production model and files above are unchanged. Summary and status table: `reports/phase2_summary.md`.

| Question | Report | Rerun |
|---|---|---|
| Does more history help? (predictors from all years since 2015 beat 3 years by +0.5 to +1.1 points of top-10% capture on the dev folds; more training periods: no clear gain; COVID exclusion fixes calibration, not ranking) | `reports/historical_window_analysis.md` | `.venv/Scripts/python ml/experiments/historical_windows.py` (~3 h), then `summarise_windows.py` |
| What does the production model learn? (TreeSHAP of the verified production model; factors are attributions, not causes) | `reports/blackspot_model_explainability.md` | `.venv/Scripts/python ml/experiments/explain_blackspot.py` (~25 min) |
| How stable is the ranking? (stable as tiers, not positions; rank 100 ≈ rank 110) | `reports/ranking_stability.md` | `.venv/Scripts/python ml/experiments/ranking_stability.py --boot 20 --seeds 5` (~35 min) |
| Map with an explanation and stability panel | `demo/blackspot_map_v2_explained_r2.html` (original: `demo/blackspot_map_v2_explained.html`) | `.venv/Scripts/python ml/demo/make_v2_map_explained.py` |
| What would the ranking have been at earlier cutoffs? Retrospective backtests for 2020–21 … 2024–25, not untouched tests: the spec was chosen on targets to 2023, the 2024–25 holdout was already examined, and the 2026 network is used throughout. Research only; not in the release, contract or frontend | `reports/historical_rankings.md` (data: `outputs/history/`) | `.venv/Scripts/python ml/experiments/historical_rankings.py` (~15 min) |

Optional, additive backend files: `../data/v2/extensions/` (explanations, stability; keyed by `segment_id`).

## Phase 3: integration contract and reporting audit (no production change)

Summary and checklist: `reports/phase3_summary.md`. Audit findings: `reports/phase3_initial_audit.md`.

| What | Where | Command |
|---|---|---|
| ML → backend contract: every field's type, units and empty-value rule; score semantics; CRS; IDs; versioning | `../data/v2/INTEGRATION_CONTRACT.md` (+ `integration_schema_v2.json`, `release_manifest_v2.json`) | `.venv/Scripts/python ml/audit/release_manifest.py` |
| Validate a release (real or fixture) | `blackspot/contract.py` | `.venv/Scripts/python ml/audit/validate_contract.py [dir]` |
| 13-segment integration fixture (real records) | `tests/fixtures/integration/` | `.venv/Scripts/python ml/audit/make_integration_fixtures.py` |
| Why Water Street's forecast rises without the parade collision; one-at-a-time vs simultaneous ranks | `reports/single_event_sensitivity.md` | `.venv/Scripts/python ml/experiments/single_event_case.py` (~3 min, no fitting) |
| Contract tests | `tests/test_integration_contract.py` | `.venv/Scripts/python -m pytest ml/tests/test_integration_contract.py` |

The Phase 2 reports were corrected in place (each carries a dated "Phase 3 corrections" note); no
result table changed. Backend rule of thumb: load `road_segments_ranked_v2.csv`, key
`segment_id`, **order by `rank`** (the CSV score is rounded), and treat everything under `ml/` as
research.

## Phase 4: Great Britain frontend demo (no production change)

The React frontend (branch `frontend-v1`) now has a GB version that shows the real v2 forecast.
It lives on the local branch **`frontend-uk-demo`**, checked out as a separate git worktree at
`.worktrees/frontend-uk`, which `.git/info/exclude` hides from this tree. It is not committed and
not pushed.

Status and checklist: `reports/phase4_integration_status.md`. Audit of the old fixture:
`reports/phase4_frontend_audit.md`.

```bash
# 1. build the demo bundle from data/v2 (the national top 1,000 + 6 fixture reference cases, ~3 MB)
.venv/Scripts/python ml/demo/make_frontend_demo_data.py --out .worktrees/frontend-uk/frontend/public/data/demo-v2
# 2. check every value against the release
.venv/Scripts/python ml/audit/validate_frontend_demo.py .worktrees/frontend-uk/frontend/public/data/demo-v2
# 3. run the frontend (no backend needed)
cd .worktrees/frontend-uk/frontend && npm ci && npm run dev      # http://localhost:5173
npm test && npm run build
```

- **The demo is a top-ranked subset, not the national map.** Every screen says how many of the 1,827,550 scored segments are loaded.
- **Scores:** the forecast is shown with its units (expected KSI casualties, 2026–27 combined), ranks are shown with their refit range, and tiers are rank bands. There is no 0–100 score.
- **Missing data:** missing rates, explanations and stability read "Not available" with the reason.
- **Backend:** the backend is not connected. Proposed endpoints and the decisions needed are in `frontend/BACKEND_INTEGRATION.md` on the frontend branch.
- **ML-side test:** `tests/test_frontend_demo.py` builds the bundle in a temporary folder and checks that the validator catches tampering.
- **Phase 5 (product polish):** the frontend is branded **Veyra, Great Britain Road Safety Intelligence**. Rank groups are labelled with exact ranks (1–100, 101–1,000, 1,001–18,275, 18,276–1,827,550; top-1% cutoff = floor(N/100)) and validated on both sides. The pass also added accessibility improvements and a separate tile-provider configuration. See `reports/phase5_product_readiness.md`.

## Demo maps: basemap

**Pages:**
- `demo/blackspot_map_v2_r2.html` and `demo/blackspot_map_v2_explained_r2.html` replace the original standalone maps for viewing.
- They embed byte-identical data: the same segments, IDs, ranks, forecasts and explanations. `tests/test_demo_maps.py` checks this.
- The originals are kept unchanged as backups. `blackspot_map_v2.html` is a protected artefact. `--legacy` on either generator rebuilds them byte for byte.

**Why the originals break (observed 2026-10-17, Chrome 155):**
- They hard-code OpenStreetMap's volunteer tile servers (`tile.openstreetmap.org`).
- Opened by double-click (`file://`), Chrome sends no Referer. Every tile came back as OSM's "403 Access blocked: App is not following the tile usage policy" image.
- Served over http, the same browser on the same machine sent a Referer and got real tiles.
- OSM sends the block image with HTTP 200, so Leaflet draws it as a normal tile.

**What the r2 pages do instead:**
- **Default:** OpenFreeMap (vector tiles via MapLibre GL). It needs no key, permits commercial use and works from `file://`.
- **Switching, without touching code or regenerating:**
  - add `?basemap=openfreemap-positron|carto-positron|osm|none` to the page address;
  - or copy `demo/basemap.config.example.js` to `demo/basemap.config.js` (gitignored) and set `provider`, your own `cartoKey`, or a `custom` provider with its attribution;
  - keys are never embedded in the HTML. The generators' `--basemap` and `--tile-*` options only change the build default.
- **No blocked requests:** a provider is never requested when the page knows the request breaks its terms (CARTO without a key, OSM from `file://`).
- **Tile checks:** raster tiles are accepted only as 2xx responses with an image type. OSM's "Access blocked" tile arrives as HTTP 200, so it is also recognised by its yellow and black edge stripe and rejected.
- **Fallback:** if the basemap fails, it is removed. The page shows a neutral background and a message, and keeps the road segments, styling, controls, legend and data attribution.
- **Provider terms:** each provider's terms, as checked on 2026-10-17, are in `demo/basemap.py`.

```bash
.venv/Scripts/python ml/demo/make_v2_map.py                     # -> demo/blackspot_map_v2_r2.html
.venv/Scripts/python ml/demo/make_v2_map_explained.py           # -> demo/blackspot_map_v2_explained_r2.html
copy ml\demo\basemap.config.example.js ml\demo\basemap.config.js    # then set provider / cartoKey / custom
```

## Run it

From the repository root (paths are anchored on the code, so the working
directory does not matter):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r ml/requirements.txt          # exact pins; bin/ on Linux/macOS
.venv/Scripts/python ml/blackspot/download.py stats19 aadf os_open_roads guide   # ~1.6 GB, validated, once
.venv/Scripts/python ml/pipeline.py data        # canonical collisions 2015-2025         ~1 min
.venv/Scripts/python ml/pipeline.py network     # OS Open Roads -> 2.7 M segments          ~13 min
.venv/Scripts/python ml/pipeline.py snap        # collisions -> segments                   ~1 min
.venv/Scripts/python ml/pipeline.py coverage    # national KSI coverage                    ~1 min
.venv/Scripts/python ml/pipeline.py develop     # dev folds 2019-21, tuning, ablations; FREEZES the spec   ~2 h
.venv/Scripts/python ml/pipeline.py holdout     # final holdout 2024-25 (refuses without frozen spec) ~1 h
.venv/Scripts/python ml/pipeline.py forecast    # 2026-27 forecast + backend files        ~10 min
.venv/Scripts/python ml/pipeline.py severity    # deployable severity model               ~5 min
.venv/Scripts/python ml/demo/make_v2_map.py
.venv/Scripts/python ml/audit/robustness.py
.venv/Scripts/python ml/audit/network_determinism.py
.venv/Scripts/python ml/audit/final_audit.py
.venv/Scripts/python -m pytest ml/tests
```

`stats19_recent.csv` (the v1 extract, 2015–2023) must be at the repository root.
v2 reuses it for 2015–2020 and verifies it against the current DfT release for
2021–23 (identical).

## Layout

```
ml/pipeline.py                 entry point (steps above)
ml/blackspot/
  config.py                    paths, periods, constants
  download.py                  validated downloads + raw/manifest.json (URL, bytes, SHA-256)
  stats19.py                   schema normalisation, casualty -> collision aggregation, BNG
  codes.py                     official DfT 2024-format code labels
  network.py                   OS Open Roads -> strokes -> ~500 m segments (no crash input)
  snap.py                      collision -> one segment (distance + road-coding penalty)
  features.py                  folds, history-only features, targets
  models.py                    Poisson / NB2 GLM, Empirical Bayes, LightGBM
  aadf.py                      DfT AADF exposure for M/A roads
  experiment.py                fold runner, same-population evaluation, block bootstrap
  evaluation.py                tie-aware capture, deviance, calibration, weighted bootstrap
  coverage.py                  national KSI coverage buckets
  severity.py                  deployable severity model, OOF thresholds, SHAP
  outputs.py                   forecast + backend files (v1 columns preserved)
  contract.py                  ML -> backend contract: field specs, validators (Phase 3)
  steps.py                     the pipeline steps
ml/tests/                      pytest: aggregation, leakage, geometry, snapping, metrics, schema
ml/audit/                      v1 audit, robustness, network determinism, final audit
ml/reports/                    every report and evidence table
ml/raw/, ml/interim/           downloads and intermediates (gitignored, regenerable)
ml/archive/                    superseded experiments, reclassified in archive/README.md
```

## Read before using the numbers

1. **Burden, not risk.** `blackspot_score` is expected casualties. Busy urban A roads dominate the top. Use `eb_excess_ksi_history` (worse than similar roads) or `ksi_per_100m_vkm_eb` (M/A only) for "dangerous per vehicle". For rates, ignore segments shorter than ~250 m: their denominators are tiny.
2. **Crash history dominates.** Where it exists, the model refines a crash-count ranking by ~2–5 points of capture. It does not replace it.
3. **Coverage is 97.7% of national KSI**, not 100%. Private/service access roads (2.2%) are not scored and 0.13% of KSI cannot be placed on a road. Capture figures are within the named population, never national performance unless the population is `all`.
4. **Segments are ~500 m on M/A/B/C roads** (92–97% of their length in 333–750 m pieces). Many unclassified streets are shorter because the street is. Length is in every model.
5. **2026 network, 2015–25 crashes.** Roads built during the period have short histories. < 0.5% of crashes fail to match the network.
6. **Severity adjustment is DfT's model.** The primary target is DfT-adjusted KSI. Rankings barely change with reported KSI or KSI collisions (top-500 overlap 92–96%), but totals and trends must use the adjusted series.
7. **Single events.** 104 segments' histories are dominated by one mass-casualty collision (e.g. the May 2025 Liverpool parade incident). They are flagged (`single_event_flag`) and are not road-design blackspots.
8. **Level shocks.** A pandemic-scale change shifts every forecast's level (COVID moved calibration ±25%) while leaving the ranking intact.
9. **Severity model is weak** and is not an input to the blackspot score. Never present "predicted severity". SHAP values are associations, and `police_force` is administrative.
10. **Exposure only on M/A roads**, via the nearest same-number DfT count point. Estimated (not counted) AADF is used where DfT provides it.
