# Veyra backend integration: what the frontend needs (checklist for the backend developer)

**Status:**
- **No backend integration exists yet.** The frontend runs on the local demo bundle (`VITE_DATA_MODE=local`).
- **Every endpoint below is a proposal.** Only four paths appear, as suggestions, in the ML contract (`data/v2/INTEGRATION_CONTRACT.md` §8, ML branch). The rest are decisions for the two developers, marked **D1–D9**. Nothing here assumes they are agreed.
- **One file to change.** `src/data/apiSource.js` implements the proposals and fails loudly on anything unagreed, so switching to the API is one file plus `VITE_DATA_MODE=api` and `VITE_API_BASE_URL`.
- **Frontend side is ready for integration (Phase 5, 2026-10-17).** Done: Veyra branding, exact rank groups, an accessibility pass and basemap configuration. What remains is the backend decisions D1–D9 below. The tile provider is a deployment decision (README, "Map provider configuration"), independent of the backend API.

## 1. What the frontend relies on (from the ML contract, not negotiable here)

| Rule | Why |
|---|---|
| Field names, types and units exactly as in `INTEGRATION_CONTRACT.md` §2 (`segment_id`, `rank`, `blackspot_score`, …) | `src/data/normalize.js` reads contract names; renaming breaks it silently |
| `segment_id` is the key everywhere (segments, geometry, explanations, stability, single-event) | joins and deep links (`/explorer?segment=<id>`) |
| Lists ordered by `rank` ascending; never by `blackspot_score` | the CSV score is rounded; 6,729 rows share a rounded value |
| `ksi_per_100m_vkm_eb`, `aadf`: `null` when `exposure_available` is false | the UI must show "Not available", never 0 |
| Optional extension absent → `404` or `{"available": false}`, never an empty or zero record | the UI renders absence explicitly |
| Coordinates WGS84; GeoJSON positions `[lon, lat]` | `normalize.js` converts to Leaflet order |
| Release metadata (version, periods, national count, tiers) available with the data | the UI labels every figure with its period and population |

## 1a. National rank groups (what the backend must serve with the release)

The UI colours, legends and filters use four contiguous, mutually exclusive bands of `rank`:

| `key` | `min_rank` | `max_rank` | Display label (built by the frontend) |
|---|---|---|---|
| `top100` | 1 | 100 | Ranks 1–100 |
| `top1000` | 101 | 1,000 | Ranks 101–1,000 |
| `top1pct` | 1,001 | floor(N / 100) = 18,275 | Ranks 1,001–18,275 |
| `below1pct` | 18,276 | N = 1,827,550 | Ranks 18,276–1,827,550 |

- **N:** `n_segments_scored_nationally`. The top-1% cutoff rounds **down**.
- **Validation:** the frontend refuses a release whose groups overlap, leave a gap, do not run from 1 to N, or use another cutoff (`src/lib/priority.js` → `tierProblems`).
- **Ranks unchanged:** the groups only band `rank`; the backend must not recompute rank or score.
- **Where to get them:** serve the four objects (and `tier_rules`) exactly as in the local bundle's `manifest.json`, or derive them from N with the rule above. The `key` values are internal identifiers, not display text.

## 2. Endpoints

| Need | Proposed request | Contract status | Response (contract field names) |
|---|---|---|---|
| Segment list | `GET /segments?order=rank&limit=&offset=&bbox=` | suggested in §8 (`bbox`, `limit`) | `[{rank, segment_id, location, road_id, road_class, road_number, road_name, form_of_way, length_m, lat, lon, blackspot_score, n_crashes, n_ksi, n_fatal, n_ksi_casualties, n_ksi_casualties_adjusted, speed_max, pct_night, pct_junction_v2, eb_expected_ksi, eb_excess_ksi_history, exposure_available, aadf, aadf_share_counted, ksi_per_100m_vkm_eb, data_sufficiency, max_single_collision_ksi, single_event_share, single_event_flag, forecast_period, history_period}]` |
| One segment | `GET /segments/{segment_id}` | suggested in §8 | one object as above |
| Explanation | `GET /segments/{segment_id}/explanation` | suggested in §8 | `{top: [{contrib_rank, feature, label, group, display_value, shap_log, factor}], base?, groups?}`, or 404 |
| Stability | `GET /segments/{segment_id}/stability` | suggested in §8 | `{rank_median, rank_p05, rank_p95, freq_top100, freq_top1000, freq_top5pct, stability_class, window_rank_min, window_rank_max}`, or 404 |
| **D1** Release metadata | e.g. `GET /release` | **not in the contract** | `score_version`, `forecast_period`, `history_period`, `n_segments_scored_nationally`, rank `tiers` and `tier_rules` (see §1a), national forecast total, `outputs_generated_utc`, contract version. The local bundle's `manifest.json` shows the shape. Could be served from `release_manifest_v2.json` + meta |
| **D2** Line geometry | GeoJSON by `bbox`, or vector tiles | **not in the contract** | the release has lines for the top 5,000 only; other rows have midpoints. Decide the format and whether ML should export more lines |
| **D3** Single-event sensitivity | e.g. `GET /segments/{id}/single-event` | **not in the contract** | `{forecast_without_largest_collision, rank_without_largest_collision_one_at_a_time, rank_without_largest_collision_simultaneous, largest_collision_adj_ksi}` (top 1,000 only), or 404 |
| **D4** Filter support | query parameters or a bulk summary | **not in the contract** | see §3 |
| **D5** Search | e.g. `GET /segments?q=` | **not in the contract** | case-insensitive match on `location`, `road_id`, `road_name`, `road_number`, `segment_id` |
| **D6** National context (STATS19 by year, holdout figures) | static file or endpoint, or drop | **not in the contract** | `context.json` shape in the local bundle; research values, not part of the backend contract |

## 3. Filters the UI offers (all on real contract fields)

| Filter | Field | Server-side parameter (proposal, D4) |
|---|---|---|
| National rank group | `rank` bands from the release `tiers` (§1a) | `rank_min`, `rank_max` (inclusive) |
| Road class | `road_class` ∈ M, A, B, C, U, N | `road_class=A,B` |
| Recorded collisions | `data_sufficiency` | `data_sufficiency=sparse,none` |
| Single-event warning | `single_event_flag` | `single_event=true` |
| Leaves top 1,000 without largest collision | single-event extension, one-at-a-time rank | needs D3 |
| Rank stability | stability `stability_class` | needs a join with the stability table |
| Per-vehicle rate available | `exposure_available` and `length_m >= 250` | `rate_available=true` |
| Explanation available | presence of explanation rows | `explained=true` (needs the explanation table) |
| Search | text | `q=` (D5) |

There is **no region or local-authority filter**: the release has no reliable administrative
field (`spatial_block` is a 50 km validation grid). Adding one needs an ML-side change and a
documented source.

## 4. Volume and performance (production strategy)

- **Don't send the full release to the browser.** It has 50,015 rows; the national model has 1.83 M segments. Serve **viewport queries** (`bbox` with a PostGIS GiST index on the midpoint or line) and **rank-limited lists** (`order=rank&limit=`).
- **Zoom-dependent display.** At national zoom, send only the top N by rank (e.g. 1,000–5,000) as points; at street zoom, send lines in the viewport. The UI already switches from points to lines at zoom 12.
- **Caching.** The release is static until the next ML run, so responses can be cached with long max-age and keyed by `score_version` / release hash.
- **Indexes.** Suggested indexes are in contract §7: GiST on geometry, b-tree on `rank`, unique on `segment_id`.

## 5. Decisions the two developers must make

| ID | Decision |
|---|---|
| D1 | Release metadata endpoint and its shape |
| D2 | Geometry delivery (GeoJSON by bbox vs vector tiles); whether ML exports lines beyond the top 5,000 |
| D3 | Whether the single-event extension is loaded and served |
| D4 | Server-side filter parameters vs a bulk summary endpoint |
| D5 | Search semantics and endpoint |
| D6 | Whether national context and holdout figures come from the backend or stay static |
| D7 | Absence semantics for optional data: 404 vs `{"available": false}` (the frontend accepts 404 today) |
| D8 | Pagination style (offset vs cursor) and maximum page size |
| D9 | How the backend reports which release it serves, and refuses files whose sha256 differs from `release_manifest_v2.json` |

## 6. Test the backend against the same data

The ML branch ships `ml/tests/fixtures/integration/`: 13 real segments in the release layout,
plus `ml/audit/validate_contract.py`. A backend that loads that fixture should return, for
example:
- `A57-842C4722100B-00`: rank 10, `blackspot_score` 6.43057, `single_event_flag` true;
- `B5339-8AD45E53257A-00`: rank 1, `exposure_available` false, rate `null`;
- the tied pair `A6005-C33B1E4E8A91-01` / `-02`: ranks 19,459 / 19,460, the same score.

The frontend's own tests (`npm test`) run against the local bundle and need no backend.

## 7. Switching the frontend to the API, once D1–D5 are agreed

1. Implement the agreed endpoints in `src/data/apiSource.js` (one file; the interface is `getRelease`, `getSegments`, `getGeometry`, `getContext`, `getExplanation`, `getStability`, `getSingleEvent`, `extensionSummary`).
2. Set `VITE_DATA_MODE=api` and `VITE_API_BASE_URL` in `.env.local`.
3. Run `npm test` and check the explorer:
   - provenance strip;
   - a segment with and without exposure;
   - a missing explanation;
   - the rank-group legend.
4. Keyboard check: Tab to the segment list, move with the arrow keys, open a segment with Enter, return with "Back to results". The announcements and focus behaviour do not depend on the data source.

## 8. Integration checklist (status at the end of Phase 5)

| Item | Owner | Status |
|---|---|---|
| Contract field names, types, units (`INTEGRATION_CONTRACT.md` §2) | ML | done |
| Local demo on real GB data, no backend | frontend/ML | done |
| Rank groups exact and validated | frontend/ML | done |
| Missing exposure / explanation / stability shown as not available | frontend | done |
| Basemap provider chosen for production, key restricted by referrer | deployment | **open** (OSM demo default only) |
| D1 release metadata endpoint (incl. `tiers`, `tier_rules`) | backend + ML | **open** |
| D2 geometry delivery | backend + ML | **open** |
| D3 single-event endpoint | backend | **open** |
| D4 filter parameters or bulk summary | backend | **open** |
| D5 search semantics | backend | **open** |
| D6 national context (static or served) | backend + ML | **open** |
| D7 absence semantics (404 vs `available: false`) | backend | **open** |
| D8 pagination | backend | **open** |
| D9 release identifier and sha256 check | backend | **open** |
| `apiSource.js` implemented against agreed endpoints | frontend | blocked on D1–D5 |
