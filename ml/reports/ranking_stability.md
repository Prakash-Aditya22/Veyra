# Ranking stability and uncertainty (2026–27 forecast)

*Phase 2 (part 4, ranking stability), 2026-10-14. The production forecast and files are unchanged.
Stability measures are exported separately in `data/v2/extensions/segment_stability_v2.csv`.*

> **Phase 3 corrections (2026-10-14).** No stability table changed.
> - **§4, rank definition:** it now says that `rank_without_largest_collision` removes every top-1,000 segment's largest collision **simultaneously**, and adds the one-at-a-time figures from `single_event_sensitivity.md`.
> - **§4, probes:** three probe percentages came from an unsaved interactive probe. They are replaced by reproducible values with explicit inputs.
> - **Water Street:** its wording now separates sensitivity from dependence.
> - **Rank ranges:** they are labelled as 5th–95th percentiles of 20 refits.

**Short answer.** The ranking is stable as **tiers** but not as **positions**:
- all production top-100 segments stay in the national top 1,000 in at least 90% of spatially resampled refits;
- 86% of the top 10% stay in the top 10%;
- but two refits share only about two-thirds of their top 100, and the order of neighbouring ranks is a coin toss.

Rank 100 is not meaningfully riskier than rank 110: it takes a gap of roughly 100 ranks
before the order holds in two refits out of three. Historical-window choices move the list
about as much as resampling does. Removing a segment's largest collision moves its position
(median 47 places) but rarely its tier (none leave the top 5%). The flagged Water Street segment
is the least stable of the top 20. Its high-priority status does not require the parade incident,
but its forecast is sensitive to it.

## 1. What is measured, and what is not

The production ranking orders 1,827,550 segments by one model's forecast. Rank 100 is
not meaningfully riskier than rank 110 unless the ordering survives reasonable changes to
the data the model learnt from. `ml/experiments/ranking_stability.py` refits the frozen
v2 LightGBM (same hyperparameters, same 45 features, training pair 2021–23 → 2024–25) and
re-forecasts 2026–27 from the same 2023–25 inference features:

| Perturbation | What changes | Replicates |
|---|---|---|
| **Spatial-block bootstrap** | training rows reweighted by resampling the 160 × 50 km BNG blocks with replacement. Whole regions drop out or repeat, which respects spatial dependence | 20 |
| **Seed-only** | LightGBM `random_state` only: row and feature subsampling inside the booster | 5 |
| **Historical window** | the 2026–27 rankings from the Phase-2 window strategies (`historical_window_analysis.md`): the reference plus 11 alternatives, 2 of which coincide with production at the 2025 cutoff | 12 rankings |
| **Single observation** | for the production top 1,000, the production model re-scores each segment with its own largest 2023–25 collision removed (neighbour context unchanged) | 1,000 segments |

**What this is not.** The rank spread is *estimation* variability: how much the ranking
depends on which places and which random choices trained the model. It is **not** a
calibrated predictive interval for future casualties, which would also include outcome
(Poisson/NB) noise and model misspecification and would be much wider. It is reported as
"the rank range across refits", never as a confidence interval.

Ranks are national (1 = highest of 1,827,550). Ties are broken by `segment_id`, exactly as
in the production file; the script asserts it reproduces the production ranks. All
per-segment outputs are keyed by `segment_id` and cover exactly the 50,015 rows of
`road_segments_ranked_v2.csv`. The production CSV is not modified; stability lives in
`data/v2/extensions/segment_stability_v2.csv`.

**Compute actually used.**
- 20 bootstrap + 5 seed refits, each a full 800-tree fit on 1.83 M rows: median 60 s, up to 200 s when the laptop was under memory pressure (`ml/interim/stability_run1_refits.log`).
- 200 bootstrap refits would take about 5 hours on the project laptop. With 20, membership frequencies come in 5% steps, enough to separate robust from borderline segments but not to estimate tail probabilities precisely.
- Attribution stability uses 8 of the bootstrap refits. Each was re-run with identical resampling weights and **reproduced its saved predictions exactly** (max difference 0.0), which also confirms the refits are deterministic.

## 2. How much does the ranking move?

`ranking_stability_topk.csv`, `ranking_stability_summary.json`.

| Tier | Bootstrap: mean overlap between refits | Bootstrap: mean overlap with production | Seed-only: overlap between refits | Production members kept in ≥ 90% of bootstrap refits |
|---|---|---|---|---|
| Top 100 | 64% | 73% | 85% | 28% |
| Top 500 | 80% | 84% | 90% | 63% |
| Top 1,000 | 82% | 85% | 92% | 67% |
| Top 1% (18,275) | 86% | 89% | 93% | 73% |
| Top 5% (91,377) | 89% | 92% | 96% | 79% |
| Top 10% | 93% | 95% | 98% | 86% |
| Top 20% | 95% | 96% | 98% | 91% |

- **The exact top-100 list is not stable.** Two bootstrap refits share about two-thirds of their top 100. Only 28% of the production top 100 are in the top 100 in ≥ 90% of refits.
- **The broad tiers are stable.** 86% of the production top 10% stay in the top 10% in ≥ 90% of refits, and **all 100 production top-100 segments stay in the top 1,000 in at least 90% of refits** (`stability_class` = robust top-1000).
- **Neighbouring ranks are indistinguishable.** For production ranks r and r + 1 within the top 1,000, the order is kept in 50% of bootstrap refits (a coin toss). For r and r + 10 it is 53%, and only at r and r + 100 does it reach 68%. Rank 100 vs rank 110 carries essentially no information. A gap of ~100 ranks is needed before the order holds two times in three.
- **Spatial resampling moves the ranking about twice as much as seed changes** (top-100 overlap 64% vs 85%). Most of the instability comes from *which places* the model learnt from, not from the algorithm's randomness. Forecasts themselves stay highly correlated between refits (log-forecast correlation 0.990 bootstrap, 0.999 seed): small, uniform shifts reorder a crowded top end.

Per-segment intervals (`data/v2/extensions/segment_stability_v2.csv`):

| Production tier | Median width of the 5th–95th percentile rank range | Stability classes |
|---|---|---|
| Top 100 | 170 ranks | 100 robust top-1,000 |
| Top 1,000 | 489 ranks | 668 robust top-1,000; 234 borderline; 98 robust top-5% |
| Top 5,000 | 2,292 ranks | 671 robust top-1,000; 292 borderline; 4,037 robust top-5% |

## 3. Sensitivity to the historical window (Phase 2 strategies, 2026–27 forecasts)

`ranking_stability_windows.json`. The window runner's reference strategy reproduces the
production forecast **exactly** (max difference 0.0), so these rankings are directly comparable.

| Strategy | Top 100 | Top 1,000 | Top 5% | Top 10% | Spearman (log forecast) |
|---|---|---|---|---|---|
| All years since 2015 | 73% | 78% | 80% | 86% | 0.975 |
| Decay, half-life 4 | 74% | 80% | 83% | 87% | 0.978 |
| Last 5 years | 78% | 82% | 87% | 90% | 0.991 |
| Last 2 years | 77% | 83% | 88% | 92% | 0.993 |
| COVID years skipped in predictors | 85% | 87% | 94% | 96% | 0.998 |
| Training pairs stacked | 71% | 87% | 93% | 95% | 0.994 |

The window choice moves the top 100 about as much as spatial resampling does (overlap
71–85%). The full-history rule that Phase 2 found more accurate is also the one that changes
the list most (top-1,000 overlap 78%). For the 2025 cutoff, a "non-COVID training target"
coincides with the production pair, so that strategy is identical to production.

## 4. Do rankings rest on single observations?

`ranking_stability_drop_largest_collision.csv`; one-at-a-time ranks in
`data/v2/extensions/segment_single_event_sensitivity_v2.csv` (`single_event_case.py`). For each
production top-1,000 segment, the saved production model re-scores it with its single largest
2023–25 collision (by adjusted KSI) removed from its **own** history features. Road features and
nearby-road context are left unchanged, and nothing is refitted. Forecasts are expected adjusted
KSI casualties over 2026–27; rank 1 is the highest priority.

Two rank definitions answer different questions:

| Definition | Question | Median rank change | Leave the top 1,000 | Leave the top 5% |
|---|---|---|---|---|
| **one at a time**: only this segment changes, all others keep their production forecast | "how much does this one collision matter for this segment?" | **+47** (falls 47 places) | **16.3%** | 0 |
| **simultaneous**: every top-1,000 segment loses its largest collision at once (`rank_without_largest_collision` in `segment_stability_v2.csv`) | "how robust is the top-1,000 list as a whole?" | −1 | 11.4% | 0 |

Phase 2 reported only the simultaneous figures, as if they were per segment. Because 78.5% of
the top 1,000 fall together in that version, relative positions barely change. One at a time,
19 of the top 100 leave the top 100, and the largest fall is to #3,638.
- **The forecast is not always lower afterwards.** It falls for 78.5% of segments but **rises for 21.2%**. The model is not monotone in severity history. Removing one collision changes several correlated history features at once, and the model treats a high KSI share or an isolated KSI spike as partly noise. Probes of the saved model on the top 1,000 change one input and hold everything else fixed, so they are not realistic states:
  - **adding 5 adjusted KSI casualties** (count and per-km value) raises 86.8% of forecasts but lowers 8.5%;
  - **lowering the KSI share by 0.1** raises 63.0% and lowers 25.9%;
  - **one fewer collision** (count and per-km value) lowers or leaves 94.1% and raises 5.9%.

  Phase 2 quoted 68%, 7% and 98% from an unsaved interactive probe whose exact inputs were not recorded. The values above come from `single_event_case.py` and replace them. The 63% figure reproduces.

  So the model is mostly, but not entirely, monotone in collision count, and tolerant of noise in severity history. That is consistent with Phase 1's finding that past KSI predicts future KSI worse than past collisions do. It is a known property of unconstrained boosting and should be tested with monotone constraints in a future version (under a pre-declared protocol).
- **The single-event case.** A57 Water Street (rank 10, single-event flag). The 142-casualty parade collision is not what keeps it in the high-priority group: without it the model forecasts 7.82 instead of 6.43 expected KSI casualties for 2026–27, and the rank goes from 10 to 2 under both definitions. That does **not** make the segment independent of the event:
  - **the forecast is sensitive to it** (+22%);
  - **the response is non-monotone:** reducing only the casualty count lowers the forecast (5.88), while removing the whole collision raises it;
  - **the event is outside the model's range:** the casualty count (148) is beyond the largest value the model ever splits on (62.5).

  Its high rank rests on 6 other collisions, 16 junctions and a busy city-centre context (decomposition in `single_event_sensitivity.md`). It is also the **least stable** of the top 20:
  - 5th–95th percentile rank across 20 bootstrap refits #1–#687;
  - range across window strategies #1–#390;
  - top-100 in 60% of refits, top-1,000 in all 20.

  Supported: continued top-1,000 membership. Not supported: a stable forecast value or a stable exact rank. Keep the single-event flag and show the range. Do not drop the segment or alter its score.

## 5. Are the explanations stable?

`ranking_stability_attributions.csv`. Mean |SHAP| on a fixed 5,000-segment uniform sample
across 8 bootstrap refits:
- **Groups are stable:** coefficient of variation 2.5% (road), 3.8% (history), 5.0% (context).
- **The leading features keep their places:** segment length is #1 in every refit, nearby collisions #2–3, junctions #2–4, own collisions #7 every time (CV 3–12%).
- **Within the correlated crash-history group, own collisions consistently take the credit.** Its near-duplicates (casualties, years with a crash, collisions per km) stay small, and the KSI-count features are tiny and unstable (CV 29–53%). So individual labels for the top features are stable enough to show, but labels for minor features, especially KSI-count features, are not.

## 6. What this means for use

- **Treat the ranking as tiers, not positions.** A defensible statement is "this segment is in the national top 1,000 in 95% of refits", not "this segment is 37th".
- **Compare segments by their rank ranges.** Two segments whose 5th–95th percentile ranges overlap should not be prioritised over each other on the forecast alone.
- **The robust core is the place to start a programme.** 668 of the top 1,000 stay in the top 1,000 in ≥ 90% of refits. Borderline segments (234) need local knowledge.
- **The bootstrap captures estimation variability only.** Future casualties will also scatter around the forecasts by Poisson/NB noise, which is larger still for any single segment.
- **Twenty refits are a screening estimate, not a definitive one.** Per-segment frequencies move in 5% steps. The 5th and 95th percentile ranks are interpolated between the two most extreme of 20 values. The overlap and order-preservation figures are means over the replicate pairs, with no confidence interval of their own. None of these numbers should be quoted as a confidence interval or treated as precise to the percentage point.

## 7. Reproduce

```bash
.venv/Scripts/python ml/experiments/ranking_stability.py --boot 20 --seeds 5                         # ~30-40 min
.venv/Scripts/python ml/experiments/ranking_stability.py --boot 20 --seeds 5 --reuse-preds --attr-boot 8   # analysis only
.venv/Scripts/python ml/experiments/single_event_case.py                                            # ~3 min, no fitting (Phase 3)
.venv/Scripts/python -m pytest ml/tests/test_stability.py
```
Replicate predictions (and, from now on, attributions) are checkpointed in
`ml/interim/stability_preds.npz`. The first full run stopped twice after its refits, on two
bugs (loading the Phase-2 file; a pandas dtype error). Both are fixed. The refits were reused,
not recomputed.
