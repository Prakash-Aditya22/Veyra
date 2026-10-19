# Explainability of the production blackspot model

*Phase 2 (part 3, explainability), 2026-10-14. It explains the model that produced
`blackspot_score`: the v2 LightGBM, frozen spec `b9487674e4f1…`. Outputs are in
`ml/outputs/explainability/` and `data/v2/extensions/`. The production files are unchanged.*

> **Phase 3 corrections (2026-10-14).** No SHAP value or table changed. The text now states:
> - **Coverage:** TreeSHAP covers 281,353 targeted segments, not every segment.
> - **Replicates:** attribution stability used 8 refits.
> - **Group shares:** the denominator is stated.
> - **Ties:** the tie count is corrected.
> - **Baseline:** the "base" is a geometric-mean baseline, not the average forecast.
> - **Runtime:** it matches the run log.
>
> The Water Street sensitivity is re-derived in `single_event_sensitivity.md`.

**In one paragraph.**
- **What the model forecasts:** a casualty **burden** for 2026–27.
- **Across the whole network,** it mostly reads road length, road class, junctions and crashes on nearby roads.
- **For the segments that matter** (the top 5%, or any with recent crashes), the segment's own recent collisions become the first or second driver, with diminishing returns. Casualties elsewhere on the same road count most where the segment's own record is thin.
- **About 60% of the attribution is exposure-like** (things that grow with traffic), so the factors explain why a road carries many casualties, not why a journey on it is risky.
- **Attributions within the crash-history group are interchangeable** and should be read as a group.
- **None of this is causal.**

## 1. Which model is explained, and how we know

v2 never saved the fitted production model. `pipeline.py forecast` refits it in memory,
scores 2026–27 and discards it. Explaining "a similar model" would not be good enough, so
`ml/experiments/explain_blackspot.py` does the following:
1. It refits the frozen spec exactly as the forecast step does: LightGBM, Poisson
   objective, 800 trees / 31 leaves / min 1,000 rows per leaf, seed 42. The training pair
   is 2021–23 features → 2024–25 adjusted KSI, and the same 45 inference features are
   built from 2023–25.
2. It requires the refit's prediction for **every one of the 1,827,550 segments** to equal
   the stored `blackspot_score` (tolerance 1e-6). The script aborts otherwise.
3. Only then does it save the model as a new file, `ml/outputs/explainability/production_lgbm.txt`,
   with its feature list and the verification record.

The 45 features are 19 crash-history, 21 road and 5 network-context features. Segment
coordinates, AADF and every target or output column are excluded, and
`explain.assert_no_target_columns` guards this.

## 2. Method

- **TreeSHAP**, exact for tree ensembles (Lundberg et al. 2020), computed with LightGBM's
  built-in implementation (`pred_contrib`) for the 281,353 segments listed below (not all
  1.83 M). It is cross-checked
  against the `shap` library on 2,000 segments.
- With a Poisson objective the model is additive in **log expected KSI**:
  `log(forecast) = base + Σ φ_j` (additivity is checked for every segment). A contribution
  is reported as a multiplicative **factor** `exp(φ_j)`: "this feature multiplies the
  forecast by ×f relative to the average segment, given the other features".
- Explanations use the 2023–25 inference features, which are exactly what produced the
  2026–27 scores. No target and no post-cutoff year is involved.
- **Groups.** history (crash record on the segment), road (OS Open Roads attributes),
  context (network density, crashes on nearby roads and on the rest of the same stretch).
  Features are also tagged **exposure proxy** (scales with how much traffic the road
  carries: crash counts, length, density) or **risk character** (layout and crash
  circumstances: class, junctions, speed, darkness share, …).
- **Interactions.** Exact SHAP interaction values on 1,000 segments (600 random + 400 from
  the top 5%).
- **Stability of attributions.** Mean |SHAP| is recomputed on a fixed 5,000-segment sample for
  8 spatial-block bootstrap refits (`ranking_stability.md` §5). Highly correlated features (|Spearman| ≥ 0.8) are listed,
  because their individual attributions trade off arbitrarily while their **group** total
  is stable.

**Verification result.**
- The refit reproduces the stored `blackspot_score` for all 1,827,550 segments (max |difference| = **0.0**), and the top-1,000 set is identical.
- 295,013 segments share their forecast with at least one other segment (ties are common among segments with no crash history). Sorting the refit by forecast alone put 10,832 segments in a different position from production. With ties broken by `segment_id`, as production does, every rank matches (asserted in `ranking_stability.py`).
- TreeSHAP additivity error is ≤ 3.2 × 10⁻⁷ in log space, and agreement with the `shap` library is ≤ 1.1 × 10⁻⁷ (`shap_checks.json`).

**Which segments were explained.** TreeSHAP covers 281,353 segments:
- all 50,015 segments of the backend file (needed for the exports);
- a 200,000-segment uniform random sample (population-representative statistics);
- the whole top 5% (91,377);
- the local examples.

Explaining all 1.83 M segments would take about 70 minutes on the project laptop and changes nothing reported here. Population-wide figures are labelled as sample-based. **A segment outside these 281,353 has no explanation**; consumers must show "not available", never a blank or zero factor.

## 3. What the model has learnt (global)

`global_importance.csv`, `group_importance.csv`, `plots/shap_summary_*.png`. Mean |SHAP| in log expected KSI:

| Rank | All segments (uniform sample) | Top 5% by forecast | Segments with ≥ 1 collision 2023–25 |
|---|---|---|---|
| 1 | Segment length 0.61 | Segment length 0.67 | **Collisions on this segment 0.73** |
| 2 | Collisions on nearby roads (3×3 km) 0.34 | **Collisions on this segment 0.65** | Segment length 0.58 |
| 3 | Road class: not classified 0.29 | Serious/fatal elsewhere on the same stretch 0.49 | All casualties on this segment 0.32 |
| 4 | Junctions on the segment 0.28 | Road class: A road 0.41 | Collisions on nearby roads 0.31 |
| 5 | Road class: unclassified 0.22 | Collisions on nearby roads 0.30 | Serious/fatal elsewhere on the same stretch 0.28 |
| 6 | Serious/fatal on nearby roads 0.20 | All casualties on this segment 0.30 | Road class: A road 0.27 |
| 7 | Collisions on this segment 0.14 | Junctions on the segment 0.26 | Junctions on the segment 0.26 |

Share of total |SHAP| by group. For each population: the sum over the group's features of mean
|SHAP| (log expected KSI), divided by the same sum over all 45 features. `group_importance.csv`
holds a different quantity, mean |sum of the group's SHAP values| per segment. That gives
14 / 58 / 28 for all segments, because opposite-signed contributions within a group cancel.

| Population | History (own crash record) | Road (OS attributes) | Context (network, neighbours) |
|---|---|---|---|
| All segments | 9% | 64% | 27% |
| Top 5% | 28% | 48% | 24% |
| With crash history | 35% | 43% | 21% |
| No crash 2023–25 | 6% | 67% | 28% |

**Reading.**
- For most of the network (91% of segments have no recent collision), the model ranks road by **what kind of road it is** (class, length, junctions) and **what happens around it** (crashes on nearby roads and elsewhere on the same stretch). This is the source of v2's large advantage over crash counts on the whole network (`robustness.md` §3).
- For the segments that matter most to a programme (top 5%, or any segment with recent crashes), the segment's **own recent collisions** become the first or second driver. That is consistent with "crash history dominates where it exists".
- **Exposure proxies dominate.** Features that scale with how much travel a road carries (length, crash counts, network density, neighbouring crashes) account for 59% of attribution population-wide (58.5%, uniform sample) and 65% in the top 5% (65.1%), with the same denominator as the group table. Road-character features account for the rest: class, junctions, speed of recent crashes, form of way. That is expected for a burden forecast (§6).

### Shapes (`plots/shap_dependence.png`)

- **Own collisions (2023–25):** increasing but strongly concave. The step from 0 to 1 collision raises the log-forecast by ~0.6, and from 10 to 30 by ~1.0. The model shrinks large counts much as Empirical Bayes would.
- **Segment length:** close to linear in log-length with slope below 1. Doubling length raises the forecast by less than double. The contribution turns negative below about 120 m, and the shortest pieces (< 20 m) are pulled down sharply.
- **Serious/fatal casualties elsewhere on the same stretch:** the jump from none to any is the largest step, and the effect is strongest where the segment's **own** history is thin (dark points sit higher). The model borrows information along the road when the segment itself is silent. The interaction table confirms this pair (own collisions × same-stretch casualties) among the strongest interactions.
- **Junctions on the segment:** the forecast rises up to about 5 junctions, then flattens.
- **Network density (3×3 km):** a hump. Moderately built-up areas raise the forecast, while the densest urban grids (≥ ~100 km of road in 9 km²) lower it per segment. Very dense grids are cut into many short, low-speed pieces.
- **Typical speed limit at recent collisions:** monotone. 60–70 mph roads sit about +0.2 to +0.3 above 20–30 mph roads, given the other features.

### Interactions (`top_interactions.csv`, exact SHAP interaction values, 1,000 segments)

Largest pairs:
1. length × junctions (0.11);
2. length × nearby collisions (0.11);
3. length × A road (0.09);
4. A road × same-stretch KSI (0.08);
5. own collisions × same-stretch KSI (0.08).

Length conditions most other effects. A long segment with junctions is not simply the sum of "long" and "has junctions".

## 4. Correlated features: read groups, not single features

`correlated_feature_pairs.csv` lists 23 pairs with |Spearman| ≥ 0.8. The history counts are
near-duplicates:
- collisions ≈ casualties ≈ years-with-a-crash ≈ collisions per km (ρ ≥ 0.998);
- KSI collisions ≈ reported KSI casualties (ρ = 1.0);
- adjusted KSI ≈ adjusted KSI per km (ρ = 0.9999);
- nearby-collisions ≈ nearby-KSI ≈ network density (0.89–0.96).

Within such a group, how credit is split between members is arbitrary: refitting on resampled
data moves credit between them. The **group total** is what is stable. The individual-versus-group
stability across 8 bootstrap refits is measured in `ranking_stability.md` §5. The UI therefore
shows group factors (history / road / context) beside the top individual factors, and the
individual labels should be read as "the crash-record group, mainly via …".

## 5. Local explanations (`local/local_explanations.json`, `local/waterfall_*.png`)

Forecast = base × product of all 45 factors. The base, 0.0064, is exp of the model's mean
log-forecast over its training rows: a geometric-mean "typical segment", not the average
forecast. The arithmetic mean of `blackspot_score` is 0.032, because the distribution is very
skewed.

| Case | Segment | Rank | Forecast 2026–27 | Largest factors |
|---|---|---|---|---|
| High | B5339 Hanover Street (Liverpool) | 1 | 9.30 | 32 collisions here ×13.4; 36 casualties ×2.4; length ×2.0; nearby KSI ×2.0; 13 junctions ×1.7 |
| High | A24 Tooting High Street | 100 | 3.89 | 32 collisions ×10.6; 50 KSI elsewhere on the stretch ×2.1; casualties ×2.0; A road ×1.7 |
| High | A6200 Derby Road | 1,000 | 1.72 | 11 collisions ×4.9; casualties ×1.9; length ×1.7; nearby KSI ×1.7; A road ×1.7 |
| Medium | A6 Preston Road | 10,000 | 0.56 | 4 collisions ×2.9; 10 KSI elsewhere on the stretch ×2.0; length ×1.8; A road ×1.7 |
| Medium | unclassified, median of segments with history | 108,462 | 0.13 | 2 collisions ×2.6; nearby collisions ×1.6; 7 junctions ×1.5 |
| Low | Cleevecroft Avenue, median of segments without history | 992,681 | 0.004 | everything slightly below average (×0.8–1.2) |
| Low | Broomhill Court (bottom 1%) | 1,809,275 | 0.001 | very short piece ×0.4; quiet surroundings ×0.6 |
| **Flagged** | **A57 Water Street (Liverpool)** | 10 | 6.43 | 7 collisions ×3.7; 16 junctions ×2.5; **148 casualties ×2.2**; nearby KSI ×2.1 |

The Water Street case shows how a single mass-casualty incident enters the model: through
"all casualties here" (148, of which 142 came from the May 2025 parade incident). Its rank
also rests on dense junctions and busy surroundings. Removing that collision does **not** lower
the forecast: it rises to 7.82. The casualty count (148) is far beyond anything the model
learnt from (its largest split on that feature is 62.5), and the model treats the spike as
partly noise. `single_event_sensitivity.md` decomposes this.

## 6. Burden is not per-vehicle risk

`burden_vs_exposure.json`, using M/A segments with a matched DfT traffic count in the uniform
sample (n = 14,587):

| Spearman correlation | ρ |
|---|---|
| log AADF vs log forecast (burden) | 0.09 |
| log AADF vs EB KSI per 100 M vehicle-km | **−0.60** |
| EB rate vs summed exposure-proxy attributions (segments ≥ 250 m) | 0.04 |
| EB rate vs summed road-character attributions (≥ 250 m) | 0.09 |

- **The attributions explain burden, not per-vehicle risk.** What the model credits for a high forecast is essentially unrelated to the per-vehicle rate.
- **The rate falls steeply with traffic.** That is a known property of the rate (fixed costs per site, and busy roads are engineered to higher standards). It is also why a "per-vehicle" ranking surfaces quieter roads (`robustness.md` §6).
- **Burden barely tracks AADF within M/A roads**, because segment length and road type vary more than traffic does among these roads.

So a factor like "collisions on this segment ×13" means **this road carries a lot of
casualties**, not "this road is dangerous to drive on". The UI keeps the two in separate
boxes (`data/v2/extensions/README.md`).

## 7. Safeguards and limitations

- **Attributions, not causes.** A factor says how the model's forecast relates to a feature, given the others. It does not say what would happen if the feature were changed. In particular, "collisions here" is the largest factor for top segments, but crashes cannot be "removed" as an intervention. Speed-limit and junction effects are associations learnt from where crashes happened, and they are confounded with traffic and land use.
- **Correlated groups.** Individual credit within the history group, or between nearby-crashes and network density, is unstable (§4). Read groups.
- **Log scale.** Factors multiply. A ×2 factor on a segment with a tiny base is still a tiny forecast.
- **Sample.** Global statistics use a 200k uniform sample plus the full top 5%. The standard error of a mean |SHAP| at this n is far below the differences discussed.
- **Exports.** `data/v2/extensions/segment_explanations_v2.csv` (50,015 × 5 rows) and `segment_explanations_top5000_v2.json` carry the raw input value and a human-readable `display_value` (metres, yes/no, %, mph). They contain no target or post-cutoff information (`test_explainability.py`).

## 8. Reproduce

```bash
.venv/Scripts/python ml/experiments/explain_blackspot.py      # ~25 min (log: refit 223 s, TreeSHAP 725 s, interactions 320 s)
.venv/Scripts/python -m pytest ml/tests/test_explainability.py
```
