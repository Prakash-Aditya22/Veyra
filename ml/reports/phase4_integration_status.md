# Phase 4 status: Great Britain frontend demo and backend integration path

*2026-10-15. Nothing is committed or pushed. The production model, forecast, release files and
backend-facing schema are unchanged (45/45 and 78/78 protected artefacts verified). No ML model
was trained and no national experiment was rerun.*

## 1. Where the work is

| Part | Location | State |
|---|---|---|
| Frontend | git worktree `.worktrees/frontend-uk`, local branch **`frontend-uk-demo`** (from `origin/frontend-v1` `cd32390`, no upstream) | 38 tracked files changed (including 5 deleted fixture/score files), 26 new (7 of them the data bundle); **all unstaged and uncommitted** |
| ML side | this working tree, branch `ML` (HEAD `8f13aa4`) | new: `ml/demo/make_frontend_demo_data.py`, `ml/audit/validate_frontend_demo.py`, `ml/tests/test_frontend_demo.py`, two reports; edited: `ml/README.md`, `CLAUDE.md`, contract §9 (a note only) |
| Local only (not versioned) | `.git/info/exclude` (`/.worktrees/`), `.claude/launch.json` (dev-server entry) | |

**To review:**
```bash
git -C .worktrees/frontend-uk status
git -C .worktrees/frontend-uk diff
```

**If the work is rejected:**
```bash
git worktree remove .worktrees/frontend-uk
git branch -D frontend-uk-demo
```
Those are destructive, so they were not run here.

## 2. What was built

**Real GB data only:**
- **Demo bundle:** `public/data/demo-v2`, about 3 MB:
  - the national **top 1,000** segments (complete);
  - **6 reference cases** from the ML integration fixture: no history, the tied pair, rank 50,000, the lowest-ranked row, and a segment outside the line-geometry file.

  Records are copied verbatim from `data/v2`, with OS centreline geometry for the 1,000.
- **Bundle manifest:** records the release hashes, the selection rule and the counts. It labels the bundle "not a sample of the national network".
- **Validator:** `validate_frontend_demo.py` re-checks every field, geometry, explanation, stability and single-event value against the release.

**Data layer** (`src/config/dataSource.js`, `src/data/*`):
- **Configuration:** one source of truth (`VITE_DATA_MODE`, `VITE_API_BASE_URL`, `VITE_LOCAL_DATA_URL`).
- **Local adapter:** fetches each file once and caches it.
- **API adapter:** covers only the endpoints the contract suggests; everything unagreed fails loudly.
- **Pure normalisation module:** rate, explanation, stability and single-event views, each with an explicit "not available" state.

**Screens** (same design system and architecture):
- **Overview:** real release figures and holdout result.
- **Explorer:** GB map with points at national zoom and OS lines from zoom 12, search, 7 filter groups on real fields, a rank-ordered list, and a segment panel. The panel shows the forecast with units, rank with refit range, warnings, history, explanation and a separate rate block.
- **Rankings:** table in rank order with search.
- **Statistics:** national, loaded and selection populations, each with its denominator.

**Removed:**
- the fixture, the 0–100 score, the invented model metrics, `en-IN` formatting and km/h;
- the density heat layer, which has no meaning for a rank-based product.

**Basemap:** CARTO now returns an API-key placeholder, so OpenStreetMap tiles are darkened by CSS. A keyed provider can be configured instead.

## 3. Verification

| Check | Result |
|---|---|
| Frontend tests (`npm test`, Node's built-in runner, no new dependency) | **34 passed, 0 failed, 0 skipped**. They cover bundle geography and conventions, the data layer (no backend), content scans of source, docs and `dist/`, and server-side renders of the real panel components |
| ML suite (`pytest ml/tests`) | **131 passed** (125 + 6 new demo-bundle tests), none skipped |
| `validate_frontend_demo.py` on the frontend bundle | matches the v2 release |
| `validate_contract.py` on `data/v2` and on the fixture | all files conform |
| `artifact_manifest.py verify` / `verify phase3` | 45/45, 78/78 unchanged |
| README number check | 38/38 |
| Production build (`npm run build`) | passes; served with `vite preview`, the app loads its data and renders a segment with **no backend** |
| Browser, dev server, all four screens, desktop | no console errors or warnings after fixes (the router future-flag and GSAP warnings were resolved) |
| Browser, specific cases | Water Street (single event, rises without the collision); B5339 (no exposure); A4 99.6 m (rate withheld); B5167 (no history, midpoint only); tied pair; rank 136,820 (outside the top 1,000, so no one-collision sensitivity) |
| Browser, explanation missing | a second dev server on a bundle copy without `explanations.json`: the panel shows "Explanation not available" and the filter counts 1,006 without. The copy was deleted afterwards |
| Phone width (375 px) | no horizontal scroll; legend strip, map and panel stack |
| Keyboard | labelled search and filter inputs; result rows are native buttons; a real Enter key opens a segment; ranking rows open with Enter or Space |
| Displayed values vs release | Water Street panel checked field by field against the release (6.43, #10, #1–#687, 7 / 2 / 45.5, 34.97, 1,650.9); statistics total 2,638 = 4.5% of 57,991 |

**Not verified:**
- the map's line features are not keyboard-focusable (Leaflet canvas); every segment can be reached through the list and search instead;
- no screen-reader session was run;
- no automated browser interaction tests exist: the rendering tests are server-side, and the interaction checks above were run by hand in the browser.

## 4. Requirement checklist

| Requirement | Status | Evidence / note |
|---|---|---|
| Read-only audit, branch protection | **PASS** | `phase4_frontend_audit.md`; isolated worktree; no checkout, reset, clean or stash |
| Indian locations and fixture records removed | **PASS** | fixture modules deleted; content test over source, docs and `dist/` |
| Real GB segments, IDs, scores, ranks, geometry | **PASS** | bundle validated value by value against `data/v2` |
| Fictitious 0–100 score removed | **PASS** | rank tiers instead; badge test renders "Top 100 #10" |
| 0–100 percentile visualisation | **NOT IMPLEMENTED** (by decision) | not needed: rank and tier carry the order, and near the top a percentile reads 99.9x for every segment |
| Initial extent GB; Northern Ireland not implied | **PASS** | fits mainland GB, pan limited to the British Isles; "Great Britain (England, Scotland, Wales)" on every screen; NI stated as not covered |
| Subset labelled, never called national | **PASS** | provenance strip, statistics populations, bundle test |
| Segment panel: forecast with units, rank range, history, SHAP, single event, rate, warnings | **PASS** | browser + render tests |
| Missing exposure → "Not available" with reason, never 0 | **PASS** | bundle, data-layer and render tests; browser |
| Missing explanation → "Explanation not available" | **PASS** | render + adapter tests; browser with the extension removed. No segment in the v2 release lacks an explanation, so this state appears only when a source omits the extension |
| Unstable rank not shown as false precision | **PASS** | rank always with its 5th–95th percentile range; stability class; explanatory note |
| Search and filters on real fields only | **PASS** | 7 groups + search; no region filter, because the release has no reliable administrative field (stated in the UI) |
| Summary statistics with denominators | **PASS** | national / loaded / selection named on the Statistics screen |
| Single-event sensitivity worded accurately | **PASS** | uses the one-at-a-time rank; "does not require … sensitive to" |
| Data adapter separated from UI; config in one place | **PASS** | content test: no hard-coded data paths or API URLs outside `src/config` |
| Ordering by `rank`, not rounded score | **PASS** | sort tests including the tied pair |
| Optional extension joins by `segment_id`; graceful absence | **PASS** | adapter tests with missing files, including the static-host HTML fallback |
| Local demo works without the backend | **PASS** | tests + production build served alone |
| Backend API connected | **NOT IMPLEMENTED** | the backend is not built; API mode deliberately fails loudly on unagreed endpoints |
| Backend contract and decisions documented | **PASS** | `frontend/BACKEND_INTEGRATION.md` (fields, filters, queries, decisions D1–D9) |
| Performance | **PASS** | data fetched once; canvas renderer; points/lines by zoom; lists render 150–200 rows at a time |
| Accessibility | **WARNING** | labels, native controls and keyboard operation checked; map features not keyboard-focusable (list provides access); no screen-reader audit |
| No browser console errors | **PASS** | four screens, clean tab |
| Production build | **PASS** | `npm run build` |
| Tests | **PASS** | 34 frontend + 131 ML |
| Basemap | **WARNING** | the CARTO default no longer works without a key; OSM tiles (darkened) are for light use only; production needs a provider or self-hosted tiles |
| Branding ("Veyra") | **WARNING** | no Veyra branding exists in the repository; the existing wordmark "Blackspot Atlas" is kept. Renaming is your decision |
| Protected artefacts and backend-facing schema unchanged | **PASS** | 45/45, 78/78; release validator |
| Nothing committed or pushed | **PASS** | HEAD `8f13aa4` (ML) and `cd32390` (frontend branch base) unchanged; no staged changes |

## 5. Dependencies on the backend (teammate)

All are listed with proposed shapes in `frontend/BACKEND_INTEGRATION.md`:
1. **Segment list endpoint:** ordered by `rank`, with `bbox`, `limit` and pagination (contract §8 suggests `GET /segments?bbox=&limit=`; pagination style is decision D8).
2. **Single segment and extensions:** `GET /segments/{id}`, `/explanation`, `/stability`, suggested in contract §8, returning 404 or `available:false` when absent (D7).
3. **D1, release metadata:** version, periods, national count, tiers.
4. **D2, geometry delivery:** GeoJSON by bbox or vector tiles; also whether ML should export lines beyond the top 5,000.
5. **D3, single-event endpoint**, if the extension is loaded.
6. **D4, filtering:** server-side filter parameters, or a bulk summary of stability class, explanation availability and one-collision rank.
7. **D5, search semantics.**
8. **D6, national context:** whether STATS19-by-year and holdout figures are served or stay static.
9. **D9, release integrity:** a release identifier, and refusal of files whose sha256 differs from `release_manifest_v2.json`.
10. **Production map strategy:** viewport queries with PostGIS GiST indexes, rank-limited lists at national zoom, and caching keyed by release.

## 6. Remaining ML-side work

- **Review and commit:** review both trees, then commit (yours to do).
- **Geometry:** if the backend needs line geometry beyond the top 5,000, export it as an additive v2.x file.
- **Bundle refresh:** regenerate and revalidate the bundle whenever the release changes:
  ```bash
  .venv/Scripts/python ml/demo/make_frontend_demo_data.py --out .worktrees/frontend-uk/frontend/public/data/demo-v2
  .venv/Scripts/python ml/audit/validate_frontend_demo.py .worktrees/frontend-uk/frontend/public/data/demo-v2
  ```
- **Dependency cleanup:** `leaflet.heat` is now unused and can be dropped from the frontend's `package.json` (not done, to avoid lockfile churn); Recharts 2 is flagged deprecated upstream.

## 7. Integration checklist for the backend developer

1. Read `data/v2/INTEGRATION_CONTRACT.md` (ML branch) and `frontend/BACKEND_INTEGRATION.md` (frontend branch).
2. Agree decisions D1–D9 with the ML side.
3. Load `road_segments_ranked_v2.csv` and the meta JSON; key on `segment_id`; order by `rank`; keep the rate and AADF fields empty (NULL) when `exposure_available` is false.
4. Serve the agreed endpoints using contract field names unchanged.
5. Test with `ml/tests/fixtures/integration/`. The expected values are in the frontend checklist, §6.
6. Implement `src/data/apiSource.js` against the agreed endpoints, set `VITE_DATA_MODE=api` and `VITE_API_BASE_URL`, and run `npm test`.
7. Check the explorer against the same cases used here: Water Street, B5339, the A4 short segment, a missing explanation.
