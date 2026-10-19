# Phase 3 summary: ML quality audit, integration contract and research readiness

*2026-10-14.*
- **Production unchanged.** The production model, forecast, ranking method and every v1/v2 backend file are unchanged: 45/45 production artefacts and 78/78 protected artefacts (production plus Phase 2 research outputs) match the hashes recorded before this phase.
- **Holdout.** The 2024–25 holdout was not used as a new test.
- **No national refit.** No national model was refitted. The only new computation is `single_event_case.py`, which re-scores the top 1,000 with the saved model (about 3 minutes).
- **Git.** Nothing is committed.

Start here: [`data/v2/INTEGRATION_CONTRACT.md`](../../data/v2/INTEGRATION_CONTRACT.md) (backend) and
[`phase3_initial_audit.md`](phase3_initial_audit.md) (what was found).

## 1. What was audited

- **Reports:** the Phase 2 reports (historical windows, explainability, ranking stability, Phase 2 summary), checked against the generated tables (`historical_window_*.csv`, `global_importance.csv`, `ranking_stability_*`) and the generating code.
- **Score semantics:** the meaning of every backend-facing field, from `outputs.py`, `features.py`, `models.py`, `aadf.py` and `network.py`.
- **Output files:** the actual files in `data/v2/`: their types, empty values, ranges, ID format, rank order, CSV precision and GeoJSON geometry.
- **Consumers:** the frontend branch's data contract (`origin/frontend-v1`). There is no backend code in the repository.
- **Map:** the explained map against its source fields, in the browser.
- **Repository:** integrity, tests, processes and size.

## 2. Reporting ambiguities resolved

| Topic | Before | Now (from the tables) |
|---|---|---|
| Deviance gain of full-history predictors | "about 2.5%" | 0.5% / 1.8% / 2.5% on the 2019/2020/2021 dev folds (mean 1.6%); 2.4–2.6% exploratory |
| Top-10% gain | +0.54 / +0.80 / +1.09 | these are bootstrap means; the point differences are +0.55 / +0.80 / +1.06 |
| "More history helps" vs "more training periods don't" | read as one claim | two experiments. Predictor years help (choice 1). Stacking training pairs gave small, inconsistent changes: one significant gain (+0.22 at 2021) and one significant deviance loss (2022). Its effect on top of full-history predictors was **not tested** |
| Recency weighting | "marginally better" than equal weights | indistinguishable: no paired test; differences −0.12 to +0.23 points; h = 4 is the edge of the grid |
| COVID calibration fix 0.77 → 0.98 | attributed to the training target | needs **both** exclusions (target only 0.88, predictors only 0.86); one ratio direction throughout |
| Water Street | "does not depend on the incident" | top-1,000 membership does not require it; the forecast is **sensitive** to it (+22%) and the rank is unstable. It rises because the event lies beyond the model's learnt range (148 casualties vs a largest split of 62.5) and the model discounts severity spikes through interactions (`single_event_sensitivity.md`) |
| Drop-largest-collision ranks | median −1; 11.4% leave the top 1,000 | that was the **simultaneous** definition. One segment at a time: median +47 places, 16.3% leave, none leave the top 5% |
| Probe percentages 68% / 7% / 98% | unsaved interactive probe | reproducible 86.8% / 8.5% / 94.1% with stated inputs (63% reproduced) |
| Attribution shares | denominator unstated | Σ per-feature mean \|SHAP\| (9/64/27); `group_importance.csv` is a different quantity (14/58/28) |
| Attribution stability | "30" or "20" refits | 8 |
| TreeSHAP coverage | "every segment" | 281,353 targeted segments |
| Ties | "10,832 tied segments" | 295,013 share a forecast; 10,832 moved before the `segment_id` tie-break |
| SHAP base 0.0064 | "average segment" | geometric-mean model baseline; the mean forecast is 0.032 |
| Stability ranges | "refit range #1–#687" | 5th–95th percentile of 20 refits; screening-level, not a confidence interval |
| Runtime of the explainability script | ~8 min | ~25 min (log) |

Each corrected report carries a dated "Phase 3 corrections" note. The underlying tables are unchanged.

## 3. Results that remain unchanged

- **v2 production and holdout:** `blackspot_score` for all 1,827,550 segments, ranks, backend files, frozen spec, holdout metrics (+12.4 points top-10% vs counts nationally; 97.7% coverage), severity model.
- **Historical-window result tables, and the main finding:** predictors built from all years since 2015 beat the 3-year window in every fold, population, class and region (recommended for a pre-registered v3, not adopted).
- **SHAP values, explanation exports, stability tables and extension files from Phase 2.**

## 4. Meaning of each production score

| Field | Meaning |
|---|---|
| `blackspot_score` | expected DfT severity-adjusted KSI **casualties** on the segment, **2026 + 2027 total**. Frozen LightGBM (Poisson), trained on 2021–23 features → 2024–25 target, applied to 2023–25. A burden (expected count), approximately calibrated in aggregate (holdout Σ ratio 1.01; deciles 0.83–1.07). Not per-vehicle, not severity, not 0–100, not causal |
| `rank` | national order of `blackspot_score`, ties by `segment_id`; stable as a tier, not as a position |
| `eb_expected_ksi` | Empirical Bayes benchmark forecast, same units; not the production score |
| `eb_excess_ksi_history` | 2023–25 KSI above similar roads (EB minus SPF); can be negative; a screening signal |
| `ksi_per_100m_vkm_eb` | 2023–25 per-vehicle **rate**, only where `exposure_available` (M/A roads with a DfT count); shown only for segments ≥ 250 m |
| explanation `factor` | `exp(TreeSHAP)` of the production model: a multiplicative attribution, not a cause |
| stability fields | spread of the rank across 20 spatial-block refits; estimation variability only |

## 5. ML outputs available for backend integration

| File (in `data/v2/`) | Role |
|---|---|
| `road_segments_ranked_v2.csv` (50,015 × 52), `road_segments_meta_v2.json` | **required** |
| `road_segments_top500_v2.json`, `road_segments_top5000_v2.geojson` | optional (fallback; line geometry for the top 5,000) |
| `extensions/segment_explanations_v2.csv`, `…_top5000_v2.json`, `segment_stability_v2.csv` | optional (Phase 2) |
| `extensions/segment_single_event_sensitivity_v2.csv` | optional (new, Phase 3) |
| `release_manifest_v2.json`, `integration_schema_v2.json` | optional, recommended (new, Phase 3) |
| `INTEGRATION_CONTRACT.md` | the contract (new, Phase 3) |

## 6. Required vs optional

Only the ranked CSV and the meta JSON are required. The validator accepts a release with only
those two files (tested). Every optional file joins on `segment_id` with the same `rank`, and its
absence must render as "not available". Everything under `ml/` is research, demo or legacy and is
listed in the manifest as `not_for_loading`.

## 7. Schema and identifier compatibility

- **No schema change.** No existing file, column, name, unit or order was changed. The 19 v1 columns remain first in v1 order.
- **Two clarifications instead of changes:** `rank_without_largest_collision` (simultaneous) and the rounded CSV score are documented rather than altered. One-at-a-time ranks were added in a new file.
- **`segment_id`:** `<label>-<12 hex>-<piece ≥ 2 digits>`, labels with `(`, `)` and spaces. Deterministic, stable for the OS Open Roads 2026-04 release; unrelated to v1 IDs.
- **Joins:** every extension ID exists in the base CSV with the same rank (validated on the real release and the fixture).
- **Future changes:** additive only within v2.x; breaking changes get new file names (`_v3`).

## 8. Test results

| Check | Result |
|---|---|
| Full suite `.venv/Scripts/python -m pytest ml/tests` | **125 passed, 0 skipped** (105 before + 20 contract tests) |
| `validate_contract.py` on `data/v2/` | all 8 files conform |
| `validate_contract.py` on the fixture | all 8 files conform |
| `artifact_manifest.py verify` / `verify phase3` | 45/45, 78/78 unchanged |
| README number check (`final_audit.doc_checks`) | 38/38 values found |
| `single_event_case.py` | reproduces the saved model's scores and the Phase-2 intervention exactly (max difference 0.0) |
| Explained map in the browser | the following panels checked; no console errors: Water Street, short segment with exposure, segment without exposure, missing explanation, missing stability, and a non-flagged segment sensitive to one collision |
| Background processes | none left running (preview server stopped) |
| Large files / raw data in Git | `ml/raw/`, `ml/interim/`, the national parquet and `*.zip` are ignored; untracked total 90.6 MB in 166 files, largest 27.8 MB |

The 20 contract tests cover the eight required checks: fields and types; ID joins; absent optional files; no fabricated rate; units and periods; rank and tie determinism; GeoJSON validity and `[lon, lat]`; and validation without the national pipeline (a subprocess confirms that LightGBM, pyproj and the feature code are never imported). They also check that the fixture is a verbatim subset, that the schema JSON and manifest hashes are in sync, that the map agrees with the release, and that the validator rejects four kinds of broken file.

## 9. Known limitations

- **Stability** rests on 20 bootstrap and 5 seed refits: frequencies in 5% steps, no confidence intervals. 200 refits would take about 5 h.
- **Explanations** cover 281,353 of 1.83 M segments (all exported rows).
- **The single-collision test** re-scores without refitting and leaves context unchanged. The model is non-monotone in severity history (and, for 5.9% of the top 1,000, in collision count). Monotone constraints are untested.
- **History windows:** no paired decay-vs-equal test; stacking with full-history predictors not run; 4- and 5-year windows rest on 1–2 folds.
- **Calibration** of the 2026–27 forecast cannot be checked until 2027 data are published (autumn 2028). Holdout calibration refers to the 2023-cutoff model.
- **Generation timestamp** is a file modification time; the meta JSON has none.
- **Geometry:** line geometry only for the top 5,000. Validity is checked with numpy (finite, ≥ 2 distinct points, inside GB, `[lon, lat]`), not a full OGC check (shapely is not installed, and was not installed). 3 features are closed loops.
- **`segment_id` validity** is tied to the 2026-04 OS Open Roads release.
- **The frontend branch** renders an unrelated fixture with a 0–100 score; mapping needs a team decision (contract §9).
- **The `phase3` integrity manifest** includes gitignored checkpoints, so it is a local check only.

## 10. Remaining ML-side work

1. Decide how the ~90 MB of generated files are published before pushing to GitHub: commit as is (all files are under GitHub's 50 MB warning), use Git LFS, or attach the large CSVs to a release. This is the owner's decision.
2. At the next forecast run, add the generation timestamp and training period to the meta JSON as **additive** keys. The release manifest covers them meanwhile.
3. Pre-register v3:
   - full-history predictors;
   - stacking only together with full history;
   - monotone constraints on the severity-history features;
   - more stability refits if tail frequencies are needed.
4. Line geometry for all 50,015 exported rows, or a geometry endpoint, if the backend asks. This would be additive.
5. Score the 2026–27 forecast against outcomes when DfT publishes them.
6. If the frontend needs `lastIncident` or an hourly profile, add them as a v2.x extension.

## 11. Remaining backend work (teammate)

1. **Schema and load.** Choose the schema (suggested DDL in contract §7). Load the ranked CSV and meta, store the release manifest, and refuse files whose sha256 differs.
2. **Geometry.** Build the geometry table from the GeoJSON in EPSG:4326, with midpoints for the remaining rows.
3. **Endpoints.** Order by `rank`, and return explicit "not available" for missing optional data, never zeros.
4. **Contract tests.** Use `ml/tests/fixtures/integration/` in the backend's own tests; the expected values are in its README.
5. **Frontend mapping.** With the frontend owner, decide how the 0–100 `score` maps to v2: a rank percentile or stability tiers, never a rescaled burden.
6. **UI rules.** Apply contract §8: burden and rate in separate boxes, rank with its range, labels for single events and low history.

## 12. Recommendation

**The ML handoff is ready for integration**, as a documented and tested contract, on three
conditions the backend must honour:
1. order by `rank`;
2. never display a per-vehicle rate where the contract says it is unavailable;
3. present ranks as tiers or ranges, not exact positions.

The required files are unchanged from the v2 release that passed the final audit, and every
optional file validates against them. Two things are not ready and should not be presented as
ready: precise rank positions (they are not stable), and any 0–100 "danger score" in the current
frontend (no ML output supports it).

## Checklist

| Item | Status | Evidence |
|---|---|---|
| Phase 1 read-only audit | **PASS** | `phase3_initial_audit.md` |
| Window claims verified against tables and corrected | **PASS** | `historical_window_analysis.md` §1.1, corrections note |
| Four window choices separated, with baseline and metric | **PASS** | same, §1.1 |
| Paired decay-vs-equal-weights test | **WARNING** | not run; claim reduced to "indistinguishable" |
| Stacking combined with full-history predictors | **NOT IMPLEMENTED** | not run; documented as untested |
| Water Street intervention, units, features, rank direction explained | **PASS** | `single_event_sensitivity.md`; reproduces Phase 2 exactly |
| Sensitivity vs dependence stated precisely | **PASS** | same, §3 |
| One-at-a-time vs simultaneous ranks | **PASS** | new extension file; reports corrected |
| Attribution denominators and replicate counts | **PASS** | explainability report corrected |
| Stability limitation (20 refits) reported without invented CIs | **WARNING** | screening-level by design; no CIs computed |
| Counts, percentages, units, periods re-derived | **PASS** | §2; `phase3_initial_audit.md` |
| `data/v2/INTEGRATION_CONTRACT.md`: inventory, dictionary, semantics, spatial, extensions, versioning | **PASS** | 52 CSV fields + GeoJSON + 4 extensions |
| Machine-readable schema and release manifest | **PASS** | generated; tests check they are in sync |
| Generation timestamp | **WARNING** | file modification time; meta has none |
| Geometry validity | **WARNING** | numpy checks pass; full OGC validity not tested (shapely absent) |
| Integration fixture (real records, 6+ required cases) | **PASS** | 13 segments, 12 cases |
| Contract tests (8 required checks) | **PASS** | 20 tests |
| Explained map: production model, not causal, unavailable ≠ zero, burden vs rate, no false precision | **PASS** | browser check; map test |
| Original v2 map intact | **PASS** | hash unchanged |
| Production outputs and Phase 2 outputs unchanged | **PASS** | 45/45, 78/78 |
| Full test suite | **PASS** | 125 passed, 0 skipped |
| No processes left running; no raw data for Git | **PASS** | checked |
| Repository size for GitHub publication | **WARNING** | 90.6 MB untracked; owner to decide on LFS or release assets |
| Backend implementation | **NOT IMPLEMENTED** | teammate's; contract and fixture provided |
| Frontend mapping of the 0–100 score | **NOT IMPLEMENTED** | needs a team decision (contract §9) |
| Nothing committed, pushed or re-authored | **PASS** | HEAD `8f13aa4`; author config untouched |
