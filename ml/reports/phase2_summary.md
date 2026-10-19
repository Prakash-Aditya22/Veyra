# Phase 2 summary: historical windows, explainability, ranking stability

*2026-10-14.*
- **Production:** the v2 production model, forecast and backend files are unchanged. All 45 v1/v2 artefacts are byte-identical to the manifest recorded before this phase (`phase2_artifact_manifest.json`; `ml/audit/artifact_manifest.py verify`).
- **Holdout:** the 2024–25 holdout had already been examined in v2. It is used here only as an exploratory check, never to choose anything.
- **Git:** nothing is committed or pushed.

Detailed reports:
- `historical_window_analysis.md`
- `blackspot_model_explainability.md`
- `ranking_stability.md`
- `../../data/v2/extensions/README.md` (integration specification)

> **Phase 3 corrections (2026-10-14).** Wording in §1, §2, §3 and §6 was made precise
> against the generated tables (`phase3_initial_audit.md` §2). No result table and no
> production file changed. The single-collision test is re-derived in
> `single_event_sensitivity.md`.

## 1. Did longer historical training data improve results?

**Yes, modestly and consistently, through the years behind the predictors. Supplying more
training periods gave no clear benefit.** These are two different experiments
(`historical_window_analysis.md` §1.1).
- **Development folds:** building features from every year since 2015 instead of the last three improved top-10% capture by +0.55, +0.80 and +1.06 points (full-sample differences; bootstrap means +0.54 / +0.80 / +1.09; paired 50 km-block CIs all exclude zero). Poisson deviance fell by 0.5%, 1.8% and 2.5% (2.4–2.6% at the exploratory cutoffs).
- **Breadth:** the gain holds in every population, road class and region. It is largest on roads with no recent crash (+1.5 to +2.2 points), where the last three years are silent but older years are not.
- **Shorter windows** (2 years) were worse everywhere.
- **Stacking extra training pairs** (with 3-year predictors) changed top-10% capture by −0.01 to +0.22 points, significant only at the 2021 cutoff. Deviance improved at 2020–21 and worsened at 2022. It costs 1.7–3.7× the fitting time. Its effect on top of full-history predictors was not tested.
- **Exploratory cutoffs** (2022, 2023, already-seen targets) agree on the predictor-history result.

## 2. Did excluding 2020–2021 matter?

**Not for ranking, yes for the forecast level.**
- **Why it doesn't affect ranking:** major-road traffic fell 24% in 2020 and 14% in 2021, but KSI per unit of traffic stayed flat (298 → 306 → 307 per index point). COVID years still say *where* crashes happen, and excluding them from predictors leaves capture unchanged (CIs include zero).
- **Where it does matter:** excluding them from **both the predictors and the training target** fixes calibration when the latest target is COVID-depressed. At the 2021 cutoff, Σforecast/Σobserved went from 0.77 to 0.98, and in the top decile from 0.77 to 0.99. Excluding them from the training target alone reached 0.88, and from the predictors alone 0.86.
- **Effect on production:** none, because the production training target (2024–25) is post-COVID.

## 3. Was recency weighting beneficial on development data?

**Not demonstrably.** The pre-declared rule (choose the half-life on 2019–2020 only) picked
h = 4 years, the slowest decay tested. Against equal weights over the same years, it differed by
−0.12, +0.12 and +0.23 top-10% points on the three development folds. Its deviance was lower by
0.07–0.18% of the reference. No paired decay-vs-equal test was run, so the two are
indistinguishable on this evidence. Faster decay (h = 1, 2) was worse. Old crashes should be
discounted little, if at all.

## 4. What does the blackspot model appear to learn?

The model it explains was refitted with the frozen spec and verified to reproduce all
1.83 M stored scores exactly. It is now saved as `ml/outputs/explainability/production_lgbm.txt`.

- **Two regimes.** Across the whole network (91% of segments have no recent crash), the forecast is driven by road length, road class, junctions and crashes on nearby roads. For the top 5%, and wherever crashes occurred, the segment's own recent collision count is the first or second driver.
- **Diminishing returns.** The effect of own collisions is concave. Casualties elsewhere on the same stretch count most where the segment's own record is thin, so the model borrows strength along a road much as Empirical Bayes does.
- **Severity history is treated as noisy.** The model is close to monotone in collision count, but not in KSI history. A high KSI share or an isolated KSI spike is partly discounted, consistent with past KSI predicting future KSI worse than past collisions do.
- **Burden, not per-vehicle risk.** About 60% of attribution goes to exposure-like features (length, crash counts, network density): 58.5% in a 200,000-segment uniform sample and 65.1% in the top 5%. The denominator is the sum over all 45 features of mean |SHAP| in log expected KSI. The attributions are essentially unrelated to the per-vehicle rate (ρ ≈ 0.04–0.09).

## 5. Which features have interpretable associations?

Stable across 8 bootstrap refits and physically sensible. The coefficient of variation of mean
|SHAP| is ≤ 13%, except the rarer road-class indicators (C roads 16%, motorways 20%;
`ranking_stability_attributions.csv`):
- segment length (rank 1 in every refit);
- crashes on nearby roads;
- junctions on the segment (rising to about 5, then flat);
- road class;
- own recent collisions (always rank 7 in mean |SHAP| population-wide, top 2 for high-risk segments);
- typical speed limit at recent crashes (monotone rising, 20 → 70 mph);
- serious/fatal casualties elsewhere on the same stretch.

**Not interpretable individually:**
- members of the near-duplicate crash-history group (ρ ≥ 0.998), so read them as a group;
- KSI-count features (tiny, CV 29–53%);
- network density, which has a hump shape and is confounded with land use.

None of these are causes. The largest factor ("collisions here") is not an intervention target.

## 6. How stable are the high-priority rankings?

**Stable as tiers, unstable as positions.**
- **Tiers hold:** all production top-100 segments stay in the top 1,000 in ≥ 90% of 20 spatial-block bootstrap refits, and 86% of the top 10% stay in the top 10%.
- **Positions do not:**
  - two refits share only 64% of their top 100;
  - adjacent ranks keep their order in about 50% of refits;
  - it takes a gap of about 100 ranks before the order holds two times in three.
- **Sources of movement:** spatial resampling moves the list about twice as much as seed changes, and history-window choices move it about as much as resampling. All of this comes from 20 bootstrap and 5 seed refits; it is not a confidence interval.
- **Single collisions move positions, not tiers.** Each top-1,000 segment was re-scored with its largest 2023–25 collision removed, one segment at a time:
  - the median segment falls 47 places;
  - 16.3% leave the top 1,000, and none leave the top 5%.

  Phase 2 first reported a median change of −1 and 11.4% leaving the top 1,000. Those figures removed every segment's largest collision **simultaneously**, so the whole top end fell together.
- **The flagged Water Street segment** (May 2025 parade incident; rank 10) stays in the top 1,000 in all 20 refits, and its high-priority status does not require the incident: removing it raises the forecast from 6.43 to 7.82 expected KSI casualties in 2026–27 (rank 10 → 2). Its forecast is nevertheless **sensitive** to the event (+22%), and its exact rank is unstable (5th–95th percentile across refits #1–#687, top-100 in 60% of refits). The model treats the extreme casualty count as partly noise, and the casualty count lies beyond every value it learnt from (`single_event_sensitivity.md`).

## 7. How could this improve the GIS interface?

`ml/demo/blackspot_map_v2_explained.html` is a separate file; the existing v2 map is untouched. It adds a segment panel with:
- forecast and national rank;
- refit rank range, top-1,000 frequency and window range, with a stability badge;
- recorded history;
- the top 5 model factors with human-readable values (metres, yes/no, mph) and a "not causes" note;
- the per-vehicle rate in a **separate** box, shown only when a DfT traffic count exists and the segment is ≥ 250 m, with an explanation otherwise;
- warnings for low history, single-event concentration and sensitivity to one collision. In Phase 3 the map was reworded: the rank is shown with its refit range, "sensitive to" is separated from "depends on", and the one-at-a-time rank is used.

It also adds a map colouring by rank stability. For the backend, `data/v2/extensions/` adds
two segment-keyed CSVs and a JSON with suggested non-breaking endpoints. No existing API or
file changes.

## 8. Limitations and remaining work

- **Folds.** Three development folds, two with COVID-affected targets, is the most the 2015 data start allows. 4- and 5-year windows rest on 1–2 folds.
- **Hyperparameters.** Window strategies reuse the frozen v2 settings, tuned for 3-year windows.
- **Untouched test.** The recommended full-history rule needs confirmation on an untouched period (2026–27 outcomes, published autumn 2028). It is **not** adopted in production.
- **Stability replicates.** 20 bootstrap + 5 seed refits (~60–200 s each on this laptop). 200 refits would take about 5 hours. The frequencies resolve in 5% steps.
- **Stability scope.** Stability measures estimation variability, not predictive uncertainty for future casualties.
- **TreeSHAP coverage.** It was computed for 281,353 targeted segments (all exported rows, a 200k uniform sample, the full top 5%), not all 1.83 M segments. Population figures are sample-based.
- **Monotonicity.** The model is non-monotone in severity history. Monotone constraints should be evaluated in a future version under a pre-declared protocol.
- **Backend.** The backend integration is a specification; the teammates' API is not changed.

## Status

| Deliverable | Status | Evidence |
|---|---|---|
| Phase 1: inspection of the actual implementation | **PASS** | facts verified from code; production model found unsaved and reconstructed exactly |
| Production model, forecast and schema preserved | **PASS** | 45/45 artefacts unchanged; `test_production_artefacts_unchanged` |
| Historical windows A/B/C/D, separate predictor vs training-pair choices | **PASS** | `ml/blackspot/windows.py`; 12 strategies × 5 cutoffs |
| Leakage-free window construction | **PASS** | `test_windows.py` (36 tests); the reference reproduces v2 bit for bit |
| Paired spatial-block uncertainty, populations, classes, regions, calibration | **PASS** | `historical_window_bootstrap.csv`, `_tables.md`, `_calibration.csv` |
| COVID mobility and reporting documented | **PASS** | `historical_window_context.csv` (traffic index, adjusted vs reported KSI) |
| 4- and 5-year windows on all dev folds | **WARNING** | infeasible before 2020/2021 (data start 2015); compared on available folds only |
| `historical_window_analysis.md` + `historical_window_results.csv` | **PASS** | written |
| Production model unchanged; recommendation recorded | **PASS** | full-history rule recommended for v3, not adopted |
| Explanations use the true production model and features | **PASS** | refit reproduces all scores (max diff 0.0); `test_explained_model_is_the_production_model` |
| Global importance, summary plots, dependence, interactions, local explanations | **PASS** | `ml/outputs/explainability/` |
| Correlated features and attribution instability | **PASS** | `correlated_feature_pairs.csv`, `ranking_stability_attributions.csv` |
| Burden vs exposure-adjusted risk distinguished | **PASS** | `burden_vs_exposure.json`; separate UI boxes |
| Segment-level explanation exports (no target leakage) | **PASS** | `data/v2/extensions/segment_explanations_*`; `test_explanation_exports_*` |
| TreeSHAP for every one of the 1.83 M segments | **WARNING** | 281k targeted segments; full coverage ~70 min and not needed for any output |
| `blackspot_model_explainability.md` | **PASS** | written |
| Spatial-block bootstrap + seed ensemble of the ranking | **PASS** | 20 + 5 refits; `ranking_stability_topk.csv` |
| Replicate count adequate for tail probabilities | **WARNING** | 20 bootstrap refits; 200 estimated at ~5 h |
| Window-choice sensitivity, single-observation dependence, extreme incidents | **PASS** | `ranking_stability_windows.json`, `_drop_largest_collision.csv` |
| Stability exported separately from the production CSV | **PASS** | `data/v2/extensions/segment_stability_v2.csv` |
| `ranking_stability.md` | **PASS** | written |
| GIS panel (forecast, history, rank stability, factors, warnings, separate rate) | **PASS** | `ml/demo/blackspot_map_v2_explained.html`, checked in the browser |
| Backend/API integration | **NOT IMPLEMENTED** | specification and example output only (`data/v2/extensions/README.md`); another team's API |
| Phase 2 tests | **PASS** | 105 passed, 0 skipped (`.venv/Scripts/python -m pytest ml/tests`) |
| Experiments reproducible from documented commands | **PASS** | commands in each report. The windows run executed end to end once. Stability refits ran once and the analysis was re-run from saved refits after two bug fixes. Explainability ran end to end twice (a first run was stopped and redesigned) |
| Single uninterrupted end-to-end run of the stability script after its fixes | **WARNING** | not repeated, to save ~35 min of laptop time; its refits were checked deterministic (8/8 identical) |
| Nothing committed or pushed | **PASS** | `git status`: changes left for review |
