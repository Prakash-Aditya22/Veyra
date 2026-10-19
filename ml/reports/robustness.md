# Robustness: what holds, what is uncertain, what depends on reporting practice

All tables in sections 1–3 come from generated files: `summary_tables.md`
(from `ml/audit/summarise.py`), `robustness_extra.json` (from
`ml/audit/robustness.py`), `model_comparison*.csv` and
`rolling_origin_*.csv`. CIs are 95% spatial-block bootstrap intervals over
50 km BNG squares. Differences are **paired**: both models are resampled with
the same weights.

## 1. Over time: does the result hold from fold to fold?

Population `all` (1,827,550 scored segments; ~97.7% of national KSI).
Top-10% capture of the target-window adjusted KSI. Every row uses the same
protocol, with the model refitted per fold:

| Fold (cutoff → target) | LightGBM | NB2 GLM | Empirical Bayes | Crash counts | KSI-history count |
|---|---|---|---|---|---|
| Dev 2019 → 2020–21 | 70.6 | 69.9 | 67.2 | 61.8 | 46.4 |
| Dev 2020 → 2021–22 | 71.3 | 70.6 | 68.0 | 60.5 | 45.3 |
| Dev 2021 → 2022–23 | 71.3 | 70.7 | 68.1 | 59.1 | 43.6 |
| Post-hoc 2022 → 2023–24 | 71.0 | 70.2 | 67.6 | 58.4 | 42.3 |
| **Final holdout 2023 → 2024–25** | **70.8** [68.3, 73.3] | 69.9 [67.4, 72.4] | 67.4 [64.7, 70.0] | 58.8 [52.3, 64.7] | 41.8 [36.7, 46.8] |

The ordering LightGBM > GLMs > EB > crash counts > KSI-history counts holds in
all five folds, and the gaps barely move. Poisson deviance (LightGBM) is
0.125, 0.134, 0.141, 0.140 and 0.142 across the folds. A rising deviance
reflects more KSI per segment in later years (adjusted KSI recovering after
COVID), not decay.

**Calibration in total is the fragile part.** Σpredicted / Σobserved for
LightGBM is 1.15, 0.87, 0.77, 0.90 and **1.01**. Each model learns the
history→target ratio from its training pair, so a training target depressed
by COVID (2020–21) makes the 2021 fold under-forecast 2022–23 by 23%. A
recovering period does the reverse. The final holdout's training pair
(2022–23) is unaffected and calibrates to within 1%, and by road class within
0.97–1.03. The production forecast (trained on 2024–25) should calibrate
similarly, but **a national shock (pandemic, recession, policy change) would
shift every forecast's level without changing the ranking.**

## 2. Over space: unfamiliar places

Final holdout, each 50 km block group predicted by models refitted without it
(5 groups, 160 blocks). The EB prior is refitted without the group too.

| | LightGBM | NB2 GLM | EB | Crash counts |
|---|---|---|---|---|
| Top-10% capture, `all`: in-sample regions / **held-out regions** | 70.8 / **70.4** | 69.9 / 69.7 | 67.4 / 67.2 | 58.8 / 58.8 |
| Top-10% capture, `numbered`: in-sample / **held-out** | 41.6 / **41.8** | 40.9 / 40.8 | 36.7 / 36.4 | 39.3 / 39.3 |
| Poisson deviance, `all`: in-sample / held-out | 0.142 / 0.143 | 0.147 / 0.148 | 0.153 / 0.154 | n/a |

Generalisation to unseen regions costs ≤ 0.4 points. The coordinate
ablation tells the same story: adding segment coordinates gains +0.19 points
on average (per-fold 95% CIs lie within [+0.01, +0.40]). Location barely helps,
so the model is not a location lookup.

## 3. Against the baselines: where the advantage is, and is not

Final holdout, paired block-bootstrap differences (LightGBM − crash counts,
top-10% capture, points):

| Population | Share of national KSI | LightGBM | Crash counts | Difference [95% CI] |
|---|---|---|---|---|
| `all` (every scored segment) | 97.7% | 70.8 | 58.8 | **+12.4 [8.1, 16.4]** |
| `numbered` (M/A/B) | 61.2% | 41.6 | 39.3 | **+2.3 [1.4, 3.7]** (top 20%: +4.3 [2.6, 6.0]) |
| `hist1` (≥ 1 collision in 2021–23) | 56.9% | 39.4 | 36.9 | **+2.5 [1.9, 3.6]** (top 20%: +5.0 [3.4, 6.4]) |

Within each road class (holdout, top-10% capture, LightGBM vs counts): A 42.5
vs 40.4, B 40.5 vs 37.8, M 29.6 vs 26.8, C 48.3 vs 41.0, unclassified 60.8 vs
42.4, not classified 45.1 vs 25.9.

**What this means.**
- The large national margin comes mostly from road that **had no recent collision**. 91% of segments tie at zero for a count, and the model ranks them using road class, junctions, length and neighbouring history. The ablation confirms this: LightGBM on history features alone reproduces the crash-count ranking almost exactly (60.5 vs 60.5 mean dev-fold capture). Removing road attributes costs 2.3 points, network context 1.5, and recent history 1.8.
- On road that **already has crash history**, the model's margin is about +2.5 points. It is consistent in sign across all five folds and every road class, but it is modest. **Crash history remains the dominant signal**, as in practice and in v1.
- **Crash counts beat KSI counts** as predictors of future KSI (58.8 vs 41.8). KSI are rarer, and their history is noisier. A KSI-history ranking, the intuitive "worst places" list, is the weakest method tested.
- **Empirical Bayes** (Hauer, NB2 SPF on road characteristics, shrinking KSI history) is better calibrated than raw counts and much better nationally (67.4). On A, B and M roads it falls *below* plain crash counts, because it shrinks KSI history rather than all-severity history. It remains the right tool for the excess-risk question, not the best ranker.
- **Rate baselines** (KSI or collisions per km) rank worse than raw counts. Short segments with one crash rise to the top.

## 4. Regression to the mean

Final holdout. Segments ranked by **raw 2021–23 adjusted KSI**, scaled to two
years, vs what they recorded in 2024–25:

| Top k by history | Future ÷ history |
|---|---|
| 100 | 0.60 |
| 500 | 0.50 |
| 1,000 | 0.46 |
| 5,000 | 0.38 |

Segments ranked by the **frozen model's 2024–25 forecast**, against what happened:

| Top k by model | Future ÷ forecast |
|---|---|
| 100 | 0.87 |
| 500 | 0.91 |
| 1,000 | 0.92 |
| 5,000 | 0.92 |

A "worst sites" list built from past KSI loses half its KSI in the next period
without any intervention. Any before/after evaluation of treatments on such a
list would credit schemes with this fall. The frozen model's forecasts for its
own top segments are much closer to what happened, because the forecast is
already shrunk.

## 5. Outcome definition and reporting practice

The production model was refitted on each outcome definition (2021–23 → 2024–25)
and its 2026–27 rankings compared with the primary ranking (adjusted KSI casualties):

| Target | Spearman vs primary | Top-100 overlap | Top-500 | Top-1,000 | Top-5,000 |
|---|---|---|---|---|---|
| Reported KSI casualties | 0.999 | 93% | 95.6% | 94.9% | 93.0% |
| KSI collisions | 0.998 | 85% | 92.0% | 92.6% | 89.0% |

On the final holdout every method's top-10% capture varies by at most 0.7 points across the
three outcome definitions (`summary_tables.md`). Rankings are therefore
**robust to the severity-adjustment choice and to casualty-vs-collision
counting**. Totals are not: reported KSI casualties in 2015 understate the
adjusted figure by 35%, and in 2025 by 2% (`data_quality.md` §4). Any
statement about trends must use the adjusted series.

## 6. Traffic exposure

M/A segments with a matched AADF in both windows: 131,531 segments, 47,021 km,
**42.8% of national KSI** (holdout). Adding log AADF (final holdout, paired):

| Model | Δ deviance [95% CI] | Δ top-10% capture [95% CI] | Δ top-20% capture [95% CI] |
|---|---|---|---|
| LightGBM | −0.0032 [−0.0042, −0.0022] | +0.08 [−0.35, +0.49] | +0.33 [−0.09, +0.90] |
| NB2 GLM | −0.0020 [−0.0028, −0.0012] | −0.01 [−0.29, +0.32] | +0.35 [+0.04, +0.70] |
| EB (SPF) | −0.0065 [−0.0083, −0.0051] | +0.18 [−0.10, +0.45] | +0.60 [+0.17, +1.09] |

Exposure makes count forecasts slightly but reliably more accurate. It does
**not** change which segments come out on top: crash history already carries
the traffic signal. The models beat crash counts in every AADF quintile:

| AADF quintile | Q1 (quietest) | Q2 | Q3 | Q4 | Q5 (busiest) |
|---|---|---|---|---|---|
| LightGBM | 30.0 | 32.5 | 40.3 | 47.8 | 38.3 |
| Crash counts | 28.9 | 30.5 | 39.3 | 46.4 | 35.9 |

**Where exposure matters is interpretation.** On M/A roads with AADF, the top 100
by expected burden and the top 100 by EB KSI per 100 M vehicle-km share only
**4%** of segments (top 500: 17%). Burden and excess-over-similar-roads agree
far more (58–63%). Burden picks busy roads with many crashes (median AADF
17,700). A raw rate ranking, even EB-shrunk, is dominated by very short pieces
(median 47 m, median one crash) where a tiny vehicle-km denominator inflates
the rate. Restricting to segments ≥ 250 m (90,492 segments) the overlap rises to 22% (top 100) and 37% (top 500). The rate's top 500 are then full-length segments (median 500 m, 9.5 crashes) on quieter roads (median AADF 7,900 vs 17,700). These are the "dangerous per vehicle but not busy" roads that a burden ranking demotes.

So exposure answers a different question ("is this road unusually dangerous
per vehicle?"). It needs a minimum segment length or exposure before it is
used for ranking. It is reported as a separate column and never blended into
`blackspot_score`.

## 7. Crash assignment and single events

- Of 2024–25 adjusted KSI, 59.6% sits on segments matched by road number, 29.8% by class (C/U roads, which have no number), 9.0% by near class, 0.65% by the second road's number, and **0.8% by fallback** (police road code contradicted by the nearest road). 0.13% is unassigned. The fallback share bounds how much the ranking can depend on the penalty rule.
- **Single mass-casualty events.** One collision can dominate a segment's history. The 26 May 2025 Liverpool parade incident (142 casualties, one vehicle, Water Street) puts the A57 Water Street segment at national rank 10 on burden. The frozen model was not altered. Outputs carry `single_event_flag` (one collision ≥ 5 KSI and ≥ 50% of the segment's history): 104 segments nationally, 1 in the top 500 and 9 in the top 5,000. The UI must label these segments rather than present them as road-design blackspots.

## 8. Severity model

Source: `severity_results.csv`, `severity_reliability_2025.csv`,
`outputs/severity_v2/`. Positive class = KSI collision. 2025 was not used for
any choice.

| Model | Labels | 2025 ROC-AUC [95% block CI] | PR-AUC (lift) | Brier skill | ECE |
|---|---|---|---|---|---|
| **v2 deployable (road, environment, time)**, served | injury-based only | **0.581** [0.572, 0.591] | 0.339 (1.26×) | 0.011 | 0.033 |
| + coordinates | injury-based only | 0.597 [0.584, 0.606] | 0.354 (1.31×) | 0.021 | 0.027 |
| + coordinates + police force | injury-based only | 0.606 [0.591, 0.613] | 0.361 (1.34×) | 0.023 | 0.033 |
| + number of vehicles (*not deployable*) | injury-based only | 0.613 [0.602, 0.621] | 0.364 (1.35×) | 0.029 | 0.023 |
| v2 deployable | all records | 0.601 [0.582, 0.613] | 0.348 (1.33×) | 0.018 | 0.039 |
| **v1 shipped "deployable" model** (24 features) | all records | **0.626** [0.605, 0.638] | 0.366 (1.40×) | 0.021 | 0.057 |
| v2 deployable, spatial blocks 2022–25 (OOF) | injury-based only | 0.603 | 0.357 (1.33×) | 0.028 | 0.011 |

**Findings.**
1. **Severity is weakly predictable from pre-crash conditions.** On an untouched future year the honest deployable model ranks a random KSI collision above a random slight one 58% of the time. Its Brier skill over the base rate is 1%. v1 reported 0.658 from a random split inside 2022–23. Its own model scores **0.626** on 2025, and that edge comes from number of vehicles (a crash fact), coordinates and police force. The ablation shows each adding ~0.01–0.03 AUC.
2. **Thresholds.** Chosen on block-grouped out-of-fold training predictions (0.18–0.21). At the 2025 base rate of 27% they give KSI recall 0.66–0.83 at precision 0.29–0.32. v1's in-sample-tuned threshold (0.29) gives recall 0.31 at precision 0.39 on 2025. Neither is a useful classifier. They are reported because the brief asks for per-class performance.
3. **Calibration shifts with the population, not the period.** The KSI share among injury-based records was 27.7% in training (2022–23), 25.3% in 2024 and 27.0% in 2025. Mean predictions were 0.236 (2024) and 0.252 (2025), about 2 points low. The reliability table shows predictions too spread: low bins observed 0.14–0.22 vs predicted 0.08–0.16, high bins observed below predicted. Block-grouped OOF predictions within 2022–25 calibrate well (ECE 0.011). So the 2025 miscalibration comes from *who* is in the test set: forces that adopted injury-based reporting in 2024–25, London above all, enter the test population without having been in training. It does not come from a change in the recorded KSI share or a modelling bug.
4. **Label-consistency trade-off.** Restricting to injury-based records keeps the label definition fixed, but it removes the forces that switched during the test years (Metropolitan Police in 2024; Cheshire, Cleveland, Derbyshire and others in 2024–25) from *training* while they appear in *test*. The all-records variant has the opposite problem (label shift). The two give 0.581 and 0.601. Neither is clearly better, and both are reported.
5. **Geography and administration.** Coordinates (+0.015) and police force (+0.009 on top) raise 2025 AUC. They are not used in the served model, because their contribution cannot be explained as road or environment risk and force differences reflect recording practice (`outputs/severity_v2/feature_set_selection.json`). The 2024 validation choice would have favoured them, and this override is recorded there.

**SHAP (served model, 2025 test rows; `outputs/severity_v2/shap_*.csv`).** Ranked by between-level spread:

| Rank | All levels | Known levels only |
|---|---|---|
| 1 | trunk_road_flag 0.153 | speed_limit 0.122 |
| 2 | speed_limit 0.122 | road_type 0.122 |
| 3 | road_type 0.122 | second_road_class 0.107 |
| 4 | pedestrian_crossing 0.120 | hour 0.092 |
| 5 | second_road_class 0.107 | light_conditions 0.078 |

"Unknown" levels distort the ranking exactly as the brief warned.
`trunk_road_flag` ranks first only because its "data missing" level (6% of
rows) carries mean SHAP +0.58; without it the flag drops to 0.028. Weather
(0.066 → 0.019) and pedestrian crossing (0.120 → 0.065) behave the same way.
The known-levels ranking is the one to present.

The directions are physically plausible, and they are associations, not causes:
- 60/70/50 mph limits push toward KSI (+0.24/+0.21/+0.17), 30/20 mph away;
- darkness without lighting +0.17 > unlit +0.13 > lit +0.12 > daylight −0.04;
- rural +0.04 vs urban −0.04;
- 00:00–05:00 +0.18 to +0.30 vs the 08:00 peak −0.20;
- Sunday and Saturday above weekdays.

`junction_detail = 0` is labelled "includes roundabouts, mini-roundabouts and
slip roads" (official 2024 conversion). `junction_control = −1` is labelled
"not at junction", which is how the data use it.

The severity model is **not** an input to the blackspot score. It is not
claimed to improve the ranking, because that was not tested under the
prospective protocol.
