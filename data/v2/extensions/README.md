# v2 extensions: explanations and ranking stability (optional, additive)

These files **add** information beside the v2 contract (`../road_segments_ranked_v2.csv`
and friends). Nothing in the v2 files changes. A backend that ignores this folder keeps
working. Every file is keyed by `segment_id`. The field-level reference, including units and
when each field is empty, is **`../INTEGRATION_CONTRACT.md`** §2.3 and §5.

Coverage:
- the explanations CSV and the stability CSV cover the same segments as `road_segments_ranked_v2.csv` (top 50,000 + all segments with ≥ 6 crashes in 2023–25);
- the map JSON covers the top 5,000;
- the single-event file covers the top 1,000.

| File | Rows | What it holds | Produced by |
|---|---|---|---|
| `segment_explanations_v2.csv` | 5 per segment | the 5 largest model attributions (TreeSHAP) of the production model: feature, plain-English `label`, `feature_value`, `shap_log`, `factor = exp(shap_log)` | `ml/experiments/explain_blackspot.py` |
| `segment_explanations_top5000_v2.json` | 5,000 | the same for the map: `base` (average segment), group factors (history / road / context), top 5 factors | same |
| `segment_stability_v2.csv` | 1 per segment | rank median and 5th–95th percentile across 20 spatial-block bootstrap refits; share of refits keeping the segment in the top 100 / 1,000 / 5% / 10% / 20%; seed-only rank range; rank range across historical-window choices; `rank_without_largest_collision` (top 1,000 only, **simultaneous** definition: every top-1,000 segment loses its largest collision at once); `stability_class` | `ml/experiments/ranking_stability.py` |
| `segment_single_event_sensitivity_v2.csv` | 1,000 | forecast with and without the segment's largest 2023–25 collision, and the rank without it **one at a time** (only this segment changes) and simultaneously. Added in Phase 3 | `ml/experiments/single_event_case.py` |

## How to read an explanation

`blackspot_score = base × Π factor_j` (exact, over all 45 features). The CSV keeps the 5
largest. `base` (0.0064) is exp of the model's mean log-forecast over its training rows, a
geometric-mean baseline, not the average forecast (that is 0.032). A factor of ×3.1 for
"Collisions on this segment, last 3 years" means the feature multiplies the forecast by 3.1
relative to that baseline, given the other features.

Explanations exist for every row of the base CSV (281,353 segments nationally). Anywhere else,
show "explanation not available", never zero or blank factors.

These are **model attributions, not causes.** They say what the model associates with a
high expected casualty count. That count is a burden, so many top factors measure how much
traffic the road carries (past collisions, network density, length), not how dangerous
each journey is. Never present a factor as "fix this to reduce casualties".

## How to read stability

The rank range comes from refitting the same frozen model on 50 km-block resamples of the
training data. It shows how much the ranking depends on which places the model learnt
from. It is **not** a confidence interval for future casualties, which would be wider.
Suggested wording: "ranks between #120 and #310 when the model is refitted".

`stability_class`:
- `robust top-1000`: ≥ 90% of refits;
- `borderline top-1000`: 50–90%;
- `robust top-5%`: outside the top 1,000 but in the top 5% in ≥ 90% of refits;
- `variable`: everything else.

## Suggested (non-breaking) endpoints

```
GET /segments/{segment_id}/explanation   -> rows of segment_explanations_v2.csv for that id
GET /segments/{segment_id}/stability     -> the row of segment_stability_v2.csv for that id
```
Existing endpoints and the `road_segment_v2` table are unchanged. Load the two CSVs into
separate tables (`segment_explanation_v2`, `segment_stability_v2`) with `segment_id` as
the foreign key.

Example response for `/explanation` (values from the real file, first factor only):
```json
{"segment_id": "A100-22D1CA35BA35-00", "rank": 2, "forecast": 7.5366, "base": 0.0064,
 "top": [{"feature": "h_n_coll", "label": "Collisions on this segment, last 3 years",
          "value": 44, "display": "44", "factor": 14.216}]}
```
For a segment without an explanation, return `{"segment_id": "...", "available": false}`.

## UI rules (in addition to `../README.md`)

1. Show burden (`blackspot_score`) and per-vehicle rate (`ksi_per_100m_vkm_eb`, a 2023–25 rate) in separate boxes, and the rate only when `exposure_available` and `length_m >= 250`.
2. Label factors as "the model associates…", never "caused by".
3. Show the rank range, not just the rank, whenever two segments are compared.
4. Keep the single-event warning. To say how much one crash matters for **this** segment, use
   `rank_without_largest_collision_one_at_a_time` from `segment_single_event_sensitivity_v2.csv`.
   The stability file's `rank_without_largest_collision` moves every top segment at once. If the
   forecast does not fall without the collision, say the rank does not **require** it, not that
   the segment is **independent** of it (`ml/reports/single_event_sensitivity.md`).

A working reference implementation is `ml/demo/blackspot_map_v2_explained.html`. Its `_r2` version has the same
panel and data with a configurable basemap.
