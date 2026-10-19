# Phase 3 initial audit: what is verified, what is ambiguous, what is missing

*2026-10-14. Read-only inspection before any Phase-3 edit. Every finding below was checked
against the generating code or a generated table, not taken from a report. Git: branch `ML`,
HEAD `8f13aa4`, nothing committed since; 9 tracked files modified and the v2/Phase-2 work
untracked, as Phase 2 left it.*

## 1. Verified accomplishments (re-checked now)

| Claim | Check run in this audit | Result |
|---|---|---|
| v1/v2 production files unchanged since before Phase 2 | `artifact_manifest.py verify` | 45/45 identical |
| Phase-2 research outputs protected for Phase 3 | new `artifact_manifest.py record phase3` (78 files: the 45 + extension files, saved model, result tables, checkpoints) | recorded before any edit |
| Saved production model = the model behind `blackspot_score` | `single_event_case.py` re-predicts the top 1,000 from rebuilt 2023–25 features | max difference 0.0 (Phase 2 had checked all 1,827,550) |
| `rank` = sort by `blackspot_score` desc, then `segment_id` asc | full parquet, 1,827,550 rows | identical |
| Score = expected DfT-adjusted KSI casualties, 2026+2027 **total** | `features.Fold`, `TARGET_YEARS = 2`, `window_sums` sums the target years | confirmed |
| 91% of segments have no 2023–25 collision | parquet `n_crashes == 0` | 91.12% |
| Exposure columns populated only where `exposure_available` | parquet | 132,899 rate values, 0 outside `exposure_available`; M and A roads only |
| Group-share table in the explainability report (9/64/27 etc.) | recomputed from `global_importance.csv` | matches, as sum of per-feature mean \|SHAP\| (see §2.C3) |
| Window-study numbers in tables | recomputed from `historical_window_results.csv` / `_bootstrap.csv` | match, with the qualifications in §2.A |
| Explanation and stability exports cover exactly the 50,015 backend rows | set comparison | identical sets; map JSON = the 5,000 GeoJSON IDs |
| GeoJSON geometries | all 5,000 features | `LineString`, 2–69 points, ≥ 2 distinct points, finite, inside the GB box, `[lon, lat]` order |

## 2. Reporting ambiguities found

### A. Historical windows (`historical_window_analysis.md`, `phase2_summary.md`)

| # | Statement | What the tables show | Resolution |
|---|---|---|---|
| A1 | "about 2.5% lower Poisson deviance" | full history vs reference: −0.46%, −1.84%, −2.51% at the 2019/2020/2021 dev cutoffs (mean −1.6%); −2.4% and −2.6% at the exploratory 2022/2023 cutoffs | report the range; 2.5% is the largest dev fold, not the typical one |
| A2 | "+0.54, +0.80, +1.09 points" | these are **bootstrap means** of the paired difference; the full-sample point differences are +0.55, +0.80, +1.06 | label which is which |
| A3 | "Stacking extra training pairs gave no measurable gain" | top-10%: +0.03 [−0.14, 0.15] (2020), **+0.22 [0.05, 0.44]** (2021); deviance −0.3% and −0.8% (CIs exclude zero) at 2020–21 but **+0.3% worse** at 2022 (CI excludes zero) | "small and inconsistent", not "none"; the 2020–21 gains coincide with diluting a COVID-depressed target. Stacking was tested only with 3-year predictors, so its benefit **on top of** full-history predictors is untested |
| A4 | "Recency weighting was only marginally better than equal weighting" | no paired decay-vs-equal test exists; point differences in top-10% capture −0.12, +0.12, +0.23 across dev folds; h = 4 was the slowest decay tested (a boundary of the grid) | "indistinguishable on this evidence" |
| A5 | "gain grows with more years (+0.5 → +0.8 → +1.1 at 5, 6, 7 years)" | the number of years is confounded with the fold (and its COVID-affected target) | suggestive only |
| A6 | Summary: excluding 2020–21 from the **training target** moved calibration 0.77 → 0.98 | target-only exclusion gives 0.88; predictor-only 0.86; **both** exclusions 0.98 | attribute 0.98 to both exclusions |
| A7 | "0.98 overall … 1.007 in the top decile" | 0.98 is Σpred/Σobs, 1.007 is Σobs/Σpred (same decile = 0.993 as Σpred/Σobs) | one direction throughout (Σpred/Σobs) |

### B. Water Street and the single-collision test (`ranking_stability.md` §4, summary §6)

| # | Issue | Evidence |
|---|---|---|
| B1 | `rank_without_largest_collision` (stability CSV) and the summary statistics (median −1, 11.4% leave the top 1,000) re-rank with **every** top-1,000 segment's largest collision removed **simultaneously**. Read one segment at a time, the same test gives median **+47** places and **16.3%** leaving the top 1,000 | `single_event_case.py` |
| B2 | "does not depend on that incident for its rank" overstates. The forecast is sensitive to the event (+22% when it is removed); top-1,000 membership does not require it | §2 of `single_event_sensitivity.md` |
| B3 | Three probe figures (68% / 7% / 98%) came from an unsaved interactive probe and cannot be reproduced | re-run as code: 86.8% / 8.5% / 94.1% under explicitly stated inputs; the 63% figure reproduces |
| B4 | "refit range #1–#687" is the 5th–95th percentile across 20 refits, not a min–max range | `segment_stability_v2.csv` (`rank_p05`, `rank_p95`) |

### C. Explainability and stability reports

| # | Issue | Correct statement |
|---|---|---|
| C1 | "TreeSHAP … computed for every segment" | 281,353 targeted segments |
| C2 | attribution stability "30 refits" (§2) and "20 refits" (§4) | 8 bootstrap refits (`ranking_stability_summary.json`: `attribution_replicates: 8`) |
| C3 | group shares have no stated denominator; `group_importance.csv` holds a **different** quantity | report table = Σ over the group's features of mean \|SHAP\| ÷ Σ over all 45 (9/64/27 for all segments). `group_importance.csv` = mean \|sum of the group's SHAP\| (14/58/28), smaller where signs cancel |
| C4 | "10,832 segments have tied predictions" | 295,013 segments share their score with another segment; 10,832 is how many changed position before the `segment_id` tie-break was applied |
| C5 | base 0.0064 called the "average segment" (report, map, extensions README) | it is exp(mean log-forecast over the training rows), a geometric-mean baseline. The arithmetic mean forecast is 0.032 |
| C6 | "~8 min" runtime for `explain_blackspot.py` | the log shows refit 223 s + TreeSHAP 725 s + interactions 320 s, about 23 min |
| C7 | report headers say "Phase 3" / "Phase 4" (Phase 2's internal numbering) | collide with this Phase 3; relabel as Phase 2 parts |
| C8 | stability: "ten Phase-2 window strategies" | 12 rankings: the reference plus 11 alternatives, 2 of which coincide with production at the 2025 cutoff |

## 3. Integration gaps

| # | Gap | Consequence |
|---|---|---|
| G1 | **No ML-to-backend contract document.** The facts are spread over `data/v2/README.md`, the meta JSON, `extensions/README.md` and code. Units, nullability and periods are not stated per field | write `data/v2/INTEGRATION_CONTRACT.md` |
| G2 | **The CSV score is rounded** (`float_format="%.6g"`): 6,729 of 50,015 rows share a rounded score with another row, and re-sorting the CSV by `blackspot_score` then `segment_id` does **not** reproduce `rank` | the backend must order by `rank`, never re-rank from the CSV |
| G3 | The meta JSON has no generation timestamp and no training period, and the GeoJSON carries no version or period | additive release manifest (not a schema change) |
| G4 | `ksi_per_100m_vkm_eb` is a **2023–25 history-period** rate, not a forecast; the per-field documentation does not say so | document |
| G5 | The frontend branch (`origin/frontend-v1`) renders a hand-written fixture with a 0–100 "danger score", incident splits and coordinates in India. Nothing in it matches the GB ML outputs | document the mapping, which needs a teammate decision; no change to their code |
| G6 | There is no backend code in the repository; the suggested SQL stores only a midpoint `GEOGRAPHY(POINT)` | contract gives geometry and key conventions; DDL stays a suggestion |
| G7 | No small fixture exists, so validating anything requires the 22 MB and 28 MB files | build `ml/tests/fixtures/integration/` |
| G8 | Two rank-without-collision definitions (B1) with one column name | keep the existing column, document it exactly, add both definitions in a new optional file |

## 4. Reproducibility problems

- Ad-hoc probe numbers (B3) had no script. Now `ml/experiments/single_event_case.py`.
- The stability script was not run end to end in one pass after its two fixes (reported in Phase 2; unchanged).
- Some interim checkpoints are gitignored, so the `phase3` manifest is a local check; a fresh clone verifies only the committed subset.
- Runtime claims (C6) disagree with the logs.

## 5. Proposed minimal changes

1. Correct the reports (A–C) in place, with a dated "Phase 3 corrections" note in each; no result tables change.
2. New report `single_event_sensitivity.md` from the new script (no model fitting).
3. `data/v2/INTEGRATION_CONTRACT.md`, plus a machine-readable schema and a release manifest, both new files. No existing file or column changes.
4. `ml/blackspot/contract.py` validator, `ml/audit/validate_contract.py`, a small fixture set and tests.
5. Explained map: separate the rank from its range, correct the baseline label, state partial explanation coverage, precise single-event wording. The original v2 map stays untouched.
6. Links in `ml/README.md` and `CLAUDE.md`; `phase3_summary.md`.

## 6. Must remain untouched

The 45 files in `phase2_artifact_manifest.json` (v1 and v2 backend files, v1 models/SHAP, v1 and v2
maps, frozen spec, forecast info, national parquet, severity v2 outputs, v2 result CSVs,
`final_audit.json`, `headline.json`, `blackspot_handoff.zip`) and the 33 Phase-2 research outputs
added in `phase3_artifact_manifest.json` (extension CSV/JSON files, the saved production model
and its explainability tables, window and stability result tables, `ml/interim/windows/*`,
`ml/interim/stability_preds.npz`). The teammates' frontend branch is not touched; there is no
backend code in this repository.
