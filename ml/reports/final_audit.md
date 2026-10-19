# Final audit: v2 blackspot ranking and severity model

*2026-10-14. Frozen spec `b9487674e4f1…` (LightGBM). Automated checks:
`ml/audit/final_audit.py` → `final_audit.json`. The table in §1 is generated
from that file; §2 lists what a script cannot check.*

## 1. Automated checks

| # | Status | Requirement | Evidence |
|---|---|---|---|
| C1 | **PASS** | Tests pass (incl. output-schema tests, none skipped) | 54 passed in 4.98s |
| C2 | **PASS** | Model selection used development folds only (no holdout years) | dev years 2015-2023; holdout target [2024, 2025] |
| C3 | **PASS** | Holdout run after the spec was frozen, and stamped with its hash | develop -> frozen spec -> holdout file order ok; hash b9487674e4f1 on all 188 rows: True |
| C4 | **PASS** | No future leakage: holdout features unchanged when every 2024-25 collision is deleted | 47 feature columns x 1,827,550 segments compared |
| C5 | **PASS** | No future leakage: frozen model's holdout predictions unchanged without 2024-25 data | max /diff/ = 0.00e+00 |
| C6 | **PASS** | Segment geometry built without crash data | segment_network(links: 'pd.DataFrame', verts: 'np.ndarray', voff: 'np.ndarray'); IDs unique: True |
| C7 | **PASS** | Eligibility independent of outcomes (same segment population in every fold) | segments per fold: [1827550] |
| C8 | **PASS** | Segment IDs reproduce across independent network rebuilds | {"saved_segments": 2698893, "rebuilt_segments": 2698893, "identical_ids": true, "max_abs_measure_diff_m": 0.0, "identical": true, "input_link_order": "shuffled (seed 123) before rebuilding"} |
| C9 | **PASS** | Temporal (rolling + final holdout) and spatial validation completed | studies present: ['holdout', 'holdout_exposure', 'holdout_spatial', 'holdout_target_is_ksi_collision', 'holdout_target_n_ksi_cas', 'posthoc'] |
| C10 | **PASS** | Every model and baseline evaluated on the identical population | 20 (study, fold, target, population) groups; max distinct row counts per group = 1 |
| C11 | **PASS** | Holdout metric of the selected model reproduces from scratch | stored 0.142461, recomputed 0.142461 |
| C12 | **PASS** | National coverage uses national denominators (buckets sum to 100%) | holdout: all 97.7%, numbered 61.2%, hist1 56.9%, class_M 3.1%, class_A 43.9%, class_B 14.2%, class_C 11.0%, class_U 24.1%, class_N 1.3%, exposure 42.8%, aadf_q1 3.9%, aadf_q2 8.6%, aadf_q3 11.7%, aadf_q4 10.9%, aadf_q5 7.7% |
| C13 | **PASS** | Exposure coverage stated explicitly | M/A segments with AADF: 131,531 segments, 47,021 km, 42.8% of national KSI |
| C14 | **PASS** | Severity model served as 'deployable' uses pre-outcome features only | 16 features; disallowed present: [] |
| C15 | **PASS** | Severity validated temporally (2025 untouched) and spatially | splits: ['spatial_blocks_2022_2025', 'test_2025', 'validation_2024'] |
| C16 | **PASS** | Output schema backward compatible (v1 file untouched; v2 = legacy columns first + additions) | v2 has 52 columns, first 19 = v1 columns: True |
| C17 | **PASS** | Documentation matches generated results (every README headline number re-derived) | 38/38 values found |
| C18 | **PASS** | Remaining limitations visible in the README | 10 numbered limitations in ml/README.md; also reports/robustness.md, coverage_analysis.md |

18 of 18 automated checks pass.

## 2. Warnings: known weaknesses and judgement calls

| # | Status | Item | Evidence / consequence |
|---|---|---|---|
| W1 | WARNING | **Mid-run feature fix before results.** The first `develop` run was stopped during LightGBM tuning, before any fold result existed. `junction_detail_historic` turned out blank for 59–87% of 2024–25 records, so the junction feature was redefined on fields coded consistently in every year, then `develop` was rerun from scratch. Only tuning-validation deviances (inside the 2019 training pair) had been seen. | `features.assigned_collisions`; `data_quality.md` §5 |
| W2 | WARNING | **Rate baselines** (`hist_*_per_km`) were added after the dev run started, so they appear in the holdout and post-hoc fold only. They are unfitted and play no part in selection. | `methodology.md` §6 |
| W3 | WARNING | **Identical-population check is numeric for the holdout, structural for the dev folds.** Dev metrics predate the `n_rows`/`target_sum` columns. Dev folds use the same `evaluate()` code path, which scores every model on one mask. | `experiment.evaluate` |
| W4 | WARNING | **Holdout bootstrap used 300 resamples**, not the 500 first planned. The change was made for runtime before the holdout ran; point estimates are unaffected. | `steps.step_holdout` |
| W5 | WARNING | **Severity served model ≠ validation winner.** On 2024 the validation AUC favoured core+coordinates+police force (0.621 vs 0.577). The served and SHAP-explained model is `core`, because force is administrative and coordinates are a location lookup. The override is recorded. | `outputs/severity_v2/feature_set_selection.json` |
| W6 | WARNING | **`single_event_flag` is post-hoc**, added after the A57 Water Street (Liverpool parade) segment was seen at rank 10. It is an output annotation and changes no score. | `outputs.assemble`; `robustness.md` §7 |
| W7 | WARNING | **Segments are not all ~500 m.** A/B/C/M roads have 92–97% of their length in 333–750 m pieces; unclassified streets are often shorter because the street is. Length is a covariate everywhere, and capture is also reported per km. | `network_summary.json` |
| W8 | WARNING | **2026 network applied to 2015–25 crashes.** < 0.5% of crashes fail to match; roads opened during the period have short histories. | `snap_summary.json` |
| W9 | WARNING | **Exposure match is a nearest-same-number-count-point heuristic**, not a link-geometry join. It is limited to M/A roads (42.8% of national KSI), and estimated AADF is included and flagged. | `aadf.py`; `coverage_analysis.md` §5 |
| W10 | WARNING | **Level calibration depends on the training pair.** Σforecast/Σobserved was 1.15 / 0.87 / 0.77 on COVID-affected dev folds and 1.01 on the holdout. Rankings are stable; totals are not guaranteed under a national shock. | `robustness.md` §1 |
| W11 | WARNING | **Severity label vs population trade-off.** Injury-based-only training excludes forces that switched in 2024–25 (e.g. Metropolitan Police). The model under-predicts their 2025 KSI share by ~2 points. Both variants are reported. | `robustness.md` §8 |
| W12 | WARNING | **Police C/U road coding disagrees with OS classification** for ~30% of C/U crashes. Totals are unaffected; class-level splits differ by scheme. | `snap_stats19_class_vs_os_class.csv` |
| W13 | WARNING | `pct_junction` keeps its v1 definition for compatibility (roundabouts count as non-junction under 2024 coding). The corrected value is `pct_junction_v2`. | `data/v2/road_segments_meta_v2.json` |

No requirement is marked FAIL.

## 3. The questions the project must answer

**1. Which road segments have the largest expected future KSI burden?**
`data/v2/road_segments_ranked_v2.csv` and `road_segments_top5000_v2.geojson`:
expected severity-adjusted KSI casualties per segment for **2026–27**, for all
1,827,550 scored segments (top 50,015 exported plus every segment with ≥ 6
crashes). The top of the list is busy central-urban A roads (Tower Bridge Road,
Old Street, Oxford Street, Whitehall, Piccadilly …). 104 segments whose history
is dominated by a single mass-casualty collision are flagged.

**2. Does the model improve on historical-count and statistically justified baselines?**
Yes, measured on the same rows with paired spatial-block CIs, on a holdout
never used for any choice:
- vs crash counts: **+12.4** points of top-10% capture nationally [8.1, 16.4]; **+2.3** [1.4, 3.7] on M/A/B roads; **+2.5** [1.9, 3.6] on segments with crash history;
- vs NB2 GLM: +0.9 [0.6, 1.2];
- vs Empirical Bayes: +3.4 [3.0, 3.8].

The national margin comes mostly from ranking road without recent crashes.
Where history exists, crash counts remain a strong baseline and the
improvement is modest but consistent.

**3. Does it generalise to future periods and unfamiliar areas?**
Five rolling origins (targets 2020–21 to 2024–25) give top-10% capture
70.6–71.3% with the same ordering of methods. Models refitted without a 50 km
region group lose ≤ 0.4 points on it. The model's top 500 delivered 91% of
their forecast KSI; a raw-history top 500 delivered 50%.

**4. How much of the national burden does it cover?**
**97.7%** of national 2024–25 adjusted KSI lies on scored segments (v1: 36.8% of
KSI collisions). The rest sits on private/service access roads (2.2%) or
cannot be placed (0.13%). Every capture figure names its population and that
population's national share.

**5. How does traffic exposure change the interpretation?**
It hardly changes *prediction*: AADF improves deviance slightly and top-10%
capture not at all (CIs include 0). It changes *interpretation* strongly. Top-100
by burden and by KSI per vehicle-km overlap only 4% (22% for segments ≥ 250 m).
Burden favours busy urban roads; rate favours quieter roads where each vehicle
faces more risk. Exposure is only defensible on M/A roads (42.8% of KSI).

**6. Which findings are robust, uncertain or reporting-sensitive?**
- *Robust*: the method ordering; LightGBM > counts on every road class, fold and region; ranking insensitive to outcome definition (top-500 overlap 92–96%); location features add ~0.2 points.
- *Uncertain*: the size of the margin over counts on well-observed roads (CI 1.4–3.7 points); level calibration under shocks; the weak severity model (AUC 0.58).
- *Reporting-sensitive*: totals and trends (reported KSI understates 2015 by 35%, 2025 by 2%), hence the adjusted primary target; police C/U road coding; the severity label, where force-level CRASH adoption shifts both the label and the population.

**7. Can another researcher reproduce it?**
Pinned environment, validated downloads with SHA-256 manifest, anchored
paths, seeds, atomic writes, documented commands (`ml/README.md`). Checked
reproductions:
- v1 outputs reproduce bit-for-bit;
- all 2.7 M segment IDs rebuild identically from a shuffled input;
- the holdout metric and predictions re-derive exactly;
- 54 tests pass.

The full run takes about 4 h on a 12-core / 16 GB laptop.

**8. Can the existing application consume the outputs?**
Yes. The v1 files are untouched. `data/v2/road_segments_ranked_v2.csv` begins
with all 19 v1 columns in v1 order and appends 33 more. Changed meanings
(new segment IDs, empty `future_*`, casualties vs collisions) are listed in
`road_segments_meta_v2.json` and `data/v2/README.md`. The frontend branch
currently renders a fixture, so nothing breaks.
