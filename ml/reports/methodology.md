# Methodology: v2 blackspot ranking and severity model

This describes what the v2 code (`ml/blackspot/`, entry point `ml/pipeline.py`)
does and why. Results are in `model_comparison.csv`, `rolling_origin_results.csv`,
`ablation_results.csv`, `robustness.md` and `final_audit.md`.

## 1. Questions and outputs

| Quantity | Definition | Where |
|---|---|---|
| **Expected future KSI burden** (`blackspot_score`) | expected DfT severity-adjusted killed-or-seriously-injured **casualties** on the segment over the next two years | primary ranking |
| Crash frequency | collisions per segment (any severity), history window | `n_crashes` |
| Historical KSI | reported KSI casualties, adjusted KSI casualties, KSI collisions, fatal collisions; history window | `n_ksi_casualties*`, `n_ksi`, `n_fatal` |
| Empirical Bayes estimate | EB-shrunk history KSI and its two-year forecast | `eb_ksi_history`, `eb_expected_ksi` |
| **Excess KSI** | EB estimate minus the SPF prediction for similar roads (potential for safety improvement) | `eb_excess_ksi_history` |
| **Exposure-adjusted rate** | EB KSI per 100 million vehicle-km, M/A roads with matched AADF only | `ksi_per_100m_vkm_eb`, `eb_excess_ksi_exposure` |

Expected burden is **not** a normalised risk. A busy urban A road ranks high
because many people use it. Rate and excess answer different questions
(engineering vs budget targeting). They are reported separately and never
mixed into one score.

KSI casualties (people) and KSI collisions (events) are kept distinct. In
2022–23 there were 55,185 reported KSI casualties in 49,895 KSI collisions.

## 2. Data

See `data_quality.md`. Collision-level table 2015–2025 (1,251,830 collisions).
Casualties are aggregated to collision grain before a one-to-one join. All
coordinates are in British National Grid. The primary target is DfT
severity-adjusted KSI because recording practice changed by force and year.

## 3. Road segments

`network.py`. OS Open Roads 2026-04 centrelines:

1. **Route key per link**: road number (M25, A23, A1(M), B1234), else `class:name`.
2. **Strokes**: links of one key are chained through every node where exactly two links of that key meet. Side roads (other keys) do not break a stroke. Branches, carriageway splits and roundabouts do. The same number in different places never shares a node, so it never merges. This replaces v1's 10 km gap heuristic.
3. **Cutting**: each stroke is cut into `round(L/500)` equal pieces (≥ 1).
4. **IDs**: `<number or class>-<first OS link id, 12 hex>-<piece>`. Strokes are walked from the end node with the smaller OS identifier, so IDs depend only on the network release (tested by row-shuffle invariance).
5. **Attributes from the network only**: class, form of way, length, junction nodes (degree ≥ 3, counted once per segment), primary/trunk flags, tunnel, roundabout/slip share.

**Eligibility** is the road class (M, A, B, C, Unclassified, Not Classified). It is never crash history, so every fold scores the same 1.83 M segments whether or not they ever had a crash.

## 4. Crash assignment

`snap.py`. Each collision goes to the one segment that minimises
`distance + penalty`, among segments within 50 m. The penalty is 0 for the
police-coded road number, 10 m for the second road's number, 25 m for the same
class with a different number, 35 m otherwise. C and unclassified roads match
on class. Ties go to the lower segment index. Assignment never reads severity
or year, so it is identical in every fold, and a crash on a boundary is
counted once.

## 5. Prospective protocol

`features.py`. A fold has a cutoff year *c*:

```
training pair:  features c-4..c-2  ->  target c-1..c     (target known at the cutoff)
test pair:      features c-2..c    ->  target c+1..c+2   (consulted only by evaluation code)
```

| Role | Cutoff | Train features → target | Test features → target |
|---|---|---|---|
| Development | 2019 | 2015–17 → 2018–19 | 2017–19 → 2020–21 |
| Development | 2020 | 2016–18 → 2019–20 | 2018–20 → 2021–22 |
| Development | 2021 | 2017–19 → 2020–21 | 2019–21 → 2022–23 |
| **Final holdout** | **2023** | 2019–21 → 2022–23 | 2021–23 → **2024–25** |
| Post-hoc | 2022 | 2018–20 → 2021–22 | 2020–22 → 2023–24 (overlaps holdout; reported after freezing) |
| Production | 2025 | 2021–23 → 2024–25 | 2023–25 → **2026–27 forecast** |

Guarantees, each enforced in code and tested in `ml/tests/test_leakage.py`:
- Features (counts, crash descriptors, neighbour history, AADF) use only the window's history years. Changing target-year crashes leaves features bit-identical.
- Segments and eligibility come from the network, not from outcomes.
- Imputation medians and scaling are fitted on training rows (`Design`). The EB scale factor *k* comes from the training pair. The test-window SPF uses test-window history counts only, never the target.
- LightGBM hyperparameters are tuned inside the **training pair** of the 2019 fold: 75% of 50 km blocks fit, 25% validate.
- Model choice uses only development folds. `develop` writes `ml/outputs/frozen_spec.json` with a SHA-256, and `holdout` refuses to run without it. Holdout results carry the spec hash.

**Spatial validation.** On the final holdout, 50 km BNG blocks are split into 5 groups. Each group's segments are predicted by models fitted with that group's segments removed (including the EB prior). This tests future periods *and* unfamiliar places together.

## 6. Models

`models.py`, `experiment.py`. All are fitted on the same rows and evaluated on the same rows.

| Model | Description |
|---|---|
| `hist_collisions`, `hist_adj_ksi`, `hist_ksi_cas`, `hist_ksi_collisions` | Historical-count baselines. They rank by the raw 3-year count; the count forecast for deviance is the count × (Σ train target / Σ train history) |
| `hist_adj_ksi_per_km`, `hist_collisions_per_km` | Historical-rate baselines (per km of road). Added after the development run had started, so they appear in holdout and post-hoc results only; baselines are not fitted and play no part in selection |
| `poisson_glm` | Log-link Poisson regression on history (log1p counts, crash descriptors), road and context features; L-BFGS, small ridge |
| `nb_glm` | Same design, NB2 likelihood, dispersion α by maximum likelihood (gradient checked against finite differences; recovers known α on simulated data) |
| `eb` | **Empirical Bayes (Hauer 1997; HSM 2010 Part B).** SPF = NB2 regression of the history-window count on *road characteristics only* (class, form of way, log length, junctions, junction density, primary/trunk, network density). EB = w·μ + (1−w)·x with w = 1/(1+αμ). Forecast = EB × k, with k estimated on the training pair. Excess = EB − μ. An exposure variant adds log AADF to the SPF on M/A roads. |
| `lgbm` | LightGBM, Poisson loss, history + road + context features (no coordinates) |

Overdispersion: the Cameron–Trivedi auxiliary regression on Poisson fits is
reported per fold. NB2 is retained only if α is clearly positive (it is).

**Outcome.** Applying the rule to the three development folds selected **LightGBM**. Its mean deviance was 0.1331 vs NB2 0.1365 (paired gap 12 SE), Poisson 0.1366 and EB 0.1424. The rule, numbers and hash are in `ml/outputs/frozen_spec.json` (`b9487674e4f1…`), written 00:14 on 2026-10-14, before the holdout ran.

**Model selection rule (pre-declared).** Take the model with the lowest
mean development-fold Poisson deviance on the full scored population. Replace
it with the *simplest* model (eb < nb_glm < poisson_glm < lgbm) whose
**paired** block-bootstrap deviance difference from the best is within one
standard error.

**Output annotation, not a model change.** One mass-casualty collision can dominate a segment's history. The May 2025 Liverpool parade incident (142 casualties, one vehicle) puts A57 Water Street at rank 10. `single_event_flag` marks segments where one collision supplied ≥ 5 KSI and ≥ 50% of the history KSI, so the UI can label them. It was added after the forecast was inspected, does not alter any score, and is documented as post-hoc.

## 7. Exposure

`aadf.py`. DfT AADF: major-road links every year (counted or estimated),
minor roads only at sample points. AADF is attached to M/A segments through a
same-number count point within max(1 km, ½ link + 0.5 km) and averaged over the
history window. Exposure models are compared with and without AADF on the
**same** M/A-with-AADF population. History crash counts are never used as
exposure (see `archive/README.md` for the v1 experiment that did).

## 8. Evaluation

`evaluation.py`.
- **Count accuracy**: mean Poisson deviance, deviance explained vs a constant, MAE, RMSE, Σpred/Σobs, and decile calibration (`calibration_holdout.csv`).
- **Ranking**: share of the population's future KSI in the top 1/5/10/20% of segments and in the top 1/5/10% of network **km**. Ties are handled at their **expected value under random tie-breaking**: the tied block at the cut counts pro rata. Row order never matters (tested).
- **Denominators**: every capture figure names its population (`all` = 1.83 M scored segments, `numbered` = M/A/B, `hist1` = segments with ≥ 1 collision in the history window, `class_*`, `exposure` = M/A with AADF). `coverage_by_population.csv` gives each population's share of the **national** KSI total, which includes unassigned crashes and crashes on unscored private/service roads.
- **Uncertainty**: spatial-block bootstrap (50 km BNG squares, 160 clusters with scored road; 200 resamples on dev folds, 300 on the holdout). Every model is resampled with the same weights, so pairwise differences are paired. Segments are never treated as independent.

## 9. Severity model (separate task)

`severity.py`. See `severity_results.csv` and section 4 of `robustness.md`.
- Label: KSI collision. Primary sample: collisions whose casualties were all injury-based (consistent label across 2022–25); "all records" reported for comparison.
- Deployable features: road type, speed limit, junction detail/control, road classes, urban/rural, light, weather, surface, carriageway hazards, pedestrian crossing, trunk flag, hour, weekday, month. Native categorical handling. `special_conditions_at_site` is excluded (2024 coding change). Coordinates, police force and number of vehicles are tested as labelled variants.
- Temporal: train 2022–23, choose the feature set on 2024, final test 2025. Spatial: block-grouped OOF on 2022–25. The threshold maximises F1 on block-grouped **out-of-fold** training predictions.
- Reported: ROC-AUC with block-bootstrap CI, PR-AUC and lift, Brier and Brier skill, log loss, ECE, reliability table, per-class precision/recall/F1, fatal AP.
- SHAP: TreeExplainer on the deployable model itself, 2025 test rows. Per-level tables use official 2024-format labels. Unknown/missing levels are flagged and the spread is recomputed without them. `police_force` is marked administrative. Values are model attributions (associations), not causal effects.
- The severity model is **not** an input to `blackspot_score`. That integration was not tested under the prospective protocol, so it is not claimed.

## 10. Reproducibility

- Environment: `.venv` with exact pins (`ml/requirements.txt`, full freeze in `ml/requirements-lock.txt`), Python 3.11.9.
- Seeds: 42 throughout (LightGBM, bootstrap, block grouping).
- Raw inputs: `ml/blackspot/download.py` with completeness checks; `ml/raw/manifest.json` records SHA-256.
- Every step writes atomically (temp file + rename) and creates its own output directories.
- Tests: `.venv/Scripts/python -m pytest ml/tests`.
