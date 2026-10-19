# Integration fixture (v2 contract)

Thirteen **real** segments copied verbatim from the v2 release (`data/v2/`). CSV rows are
byte-for-byte copies, so rounding and empty cells are exactly those of the real files; JSON and
GeoJSON objects are unchanged. Nothing is invented or recomputed. The folder has the same
layout as `data/v2/`, so one validator serves both:

```bash
.venv/Scripts/python ml/audit/validate_contract.py ml/tests/fixtures/integration
.venv/Scripts/python -m pytest ml/tests/test_integration_contract.py
```
Neither needs the national pipeline, LightGBM or the 1.8 M-row table; pandas and numpy suffice.

| Case | Segment | Rank | What it exercises |
|---|---|---|---|
| high_rank_normal | B5339 Hanover Street (Liverpool) | 1 | top segment; **B road, so no traffic exposure**: every exposure field is empty, and no rate may be shown |
| high_rank_with_exposure | A100 | 2 | exposure available, 736 m: the rate may be shown |
| single_event | A57 Water Street | 10 | `single_event_flag`; the per-vehicle rate (1,651 per 100 M vkm) is dominated by one incident; the forecast **rises** without that collision |
| borderline_stability | A57 Water Street, next piece | 140 | `stability_class = borderline top-1000` |
| exposure_short_segment | A4 | 147 | exposure available but 99.6 m: the rate exists in the file and **must not be displayed** |
| forecast_rises_without_largest_collision | A5038 | 240 | largest relative rise (×1.26) when one collision is removed, for a non-flagged segment |
| sparse_history | A34 | 369 | `data_sufficiency = sparse` (5 collisions) |
| explained_without_map_json | A551 | 5,001 | explanation in the CSV but not in the map JSON, and no line geometry (outside the top 5,000) |
| no_history | B5167 | 6,563 | no collision in 2023–25 (`data_sufficiency = none`): every history descriptor is empty |
| tie_pair | A6005, pieces 01 and 02 | 19,459 / 19,460 | **identical full-precision forecasts**: the tie is broken by `segment_id` |
| rank_50000 | A629 | 50,000 | last row of the top-N export; no collision, but exposure available |
| lowest_ranked | U road | 136,820 | exported only because of ≥ 6 collisions; shows the rank gaps; unclassified road, 99 m |

Files:
- **CSV:** `road_segments_ranked_v2.csv` (13 rows).
- **Map and fallback files:** `road_segments_top500_v2.json` (the 7 within the top 500); `road_segments_top5000_v2.geojson` (the 7 within the top 5,000).
- **Meta:** `road_segments_meta_v2.json`, copied **unchanged**. Its `n_rows_in_this_file` describes the full release, not this fixture.
- **Extensions:** the explanations CSV (5 rows each), the map explanation JSON, the stability CSV and the single-event CSV (the 7 within the top 1,000).
- **`fixture_manifest.json`:** the selection rule for each case and the sha256 of each source file.

Rebuild after a new release with `.venv/Scripts/python ml/audit/make_integration_fixtures.py`.
The rules pick segments by rank and attributes, so a new release picks new segments of the same kinds.
