# Phase 5: product polish and frontend integration readiness

*2026-10-17. Polish and integration preparation only:*
- *no ML model was added or refitted, and no national computation was rerun;*
- *the production model, forecast, release files, backend-facing schema and protected artefacts are unchanged (45/45 and 78/78 hashes verified after the work);*
- *nothing is committed or pushed;*
- *no backend code exists in the repository, and none was written.*

## 1. Where the work is

| Part | Location | State at the end of Phase 5 |
|---|---|---|
| Frontend | `C:\Blackspot Proj1\.worktrees\frontend-uk` (git worktree), branch **`frontend-uk-demo`**, based on `origin/frontend-v1` `cd32390`, no upstream | 43 tracked files changed (5 of them deleted fixture/score files), 28 new; nothing staged or committed |
| ML side | `C:\Blackspot Proj1`, branch `ML`, HEAD `8f13aa4` | Phase 5 edits: `ml/demo/make_frontend_demo_data.py` (rank-group labels and rules), `ml/audit/validate_frontend_demo.py` (partition checks), `ml/tests/test_frontend_demo.py` (2 new tamper cases), this report, short pointers in `ml/README.md` and `CLAUDE.md` |

The worktree was verified before any change: it existed, was on `frontend-uk-demo` with HEAD
`cd32390` and no upstream, and held the Phase 4 changes unstaged (38 changed and 26 new files).
Its demo bundle matched the release. No branch was switched; no checkout, reset, clean or stash
was run; Git author settings were not touched.

## 2. Changes

### 2.1 Veyra branding
- **Nav:** the wordmark is now **Veyra**, with the subtitle **"Great Britain Road Safety Intelligence"** (hidden below 1,100 px). The brand link is named "Veyra, Great Britain Road Safety Intelligence: overview". Visual design is unchanged.
- **Page metadata:** the page title is "Veyra · Great Britain Road Safety Intelligence". Each screen sets its own title ("Explorer · Veyra", "Rankings · Veyra", "Statistics · Veyra", or the segment's name when one is open). The meta description says England, Scotland and Wales, and that Northern Ireland is not covered. `application-name` is "Veyra".
- **Overview footer:** carries the brand line.
- **Package names:** `package.json` / `package-lock.json` renamed `veyra-web` (only the two name fields changed in the lockfile); local launcher renamed `veyra-web`.
- **Docs:** README, DESIGN.md (title and a dated Phase 5 note) and BACKEND_INTEGRATION.md now use Veyra. Tests fail if "Blackspot Atlas", "United Kingdom" or "UK-wide" appear in the frontend source.

### 2.2 Ranking tiers made exact
**Audit finding.** The four groups were already contiguous by boundary (1–100, 101–1,000,
1,001–18,275, 18,276–1,827,550). But their labels, "Top 100 / Top 1,000 / Top 1% / Below top
1%", read as overlapping: "Top 1,000" seems to include the top 100. The top-1% rounding rule was
not documented, and nothing checked the partition.

**Now:**

| Group (display label) | Ranks | Description |
|---|---|---|
| Ranks 1–100 | 1 to 100 | the national top 100 |
| Ranks 101–1,000 | 101 to 1,000 | the rest of the national top 1,000 |
| Ranks 1,001–18,275 | 1,001 to 18,275 | the rest of the national top 1% |
| Ranks 18,276–1,827,550 | 18,276 to 1,827,550 | all remaining scored segments |

- **Rounding rule:** the top-1% cutoff is 1% of the 1,827,550 nationally scored segments, rounded down: floor(18,275.5) = 18,275. It is published in the bundle manifest as `tier_rules`.
- **Labels follow the boundaries.** Labels are built from the boundaries in the frontend (`src/lib/priority.js`) and generated identically on the ML side. Legend, filters, badges, the rankings column and the statistics chart all use them; compact form "Ranks 18,276+".
- **Partition is enforced:**
  - the app refuses a release whose groups do not run from 1 to N, overlap, leave a gap or use another cutoff;
  - a segment outside every group is rejected;
  - the ML validator checks the same rules and that the labels match the boundaries.
- **Tests:** every boundary rank (1, 100, 101, 1,000, 1,001, 18,275, 18,276, 1,827,550) falls in exactly one group; overlapping, gapped or wrong-cutoff groups are rejected; tampered manifests are caught.
- **Ranks unchanged:** the groups only band the release `rank`. No score or rank was recomputed: the bundle was regenerated with the same selection and field list (only the manifest's group labels and `tier_rules` are new), and the validator re-checked every segment value against the release.

### 2.3 Accessibility improvements

| Area | Change |
|---|---|
| Search and filters | visible label "Search by road, place or segment ID", with a description and the live match count linked (`aria-describedby`); filter groups are fieldsets with legends; counts read as "914 segments"; rank groups show their description; active-filter chips are named "Remove filter: …"; the disabled "Reset filters" button explains itself |
| Results list (the keyboard alternative to map lines) | a real `<ul>` of buttons with a descriptive name per row (rank, place, forecast with units, group, collisions, warnings); **Up/Down/Home/End** move focus; **Enter** opens; focus moves to the segment heading on open and returns to its row on "Back to results"; usage instructions for screen readers |
| Skip link | "Skip the map: go to the segment list", hidden until focused |
| Map | the Leaflet container has `role=region`, a name ("Map of 1,006 loaded road segments") and a description of the keyboard alternative; it has a visible focus ring; the decorative preview map on the overview is hidden from assistive technology |
| Announcements | a polite live region announces the selected segment (rank, group, forecast with units) and, after typing settles, "N of 1,006 loaded segments match" |
| Focus | focus rings that clipping containers had hidden are now drawn inside: map container, map buttons, result rows, filter option rows; ranking rows show a teal edge |
| Rankings table | Up/Down/Home/End between rows; Enter or Space opens; keyboard instructions linked to the table |
| Legend | a named region; every colour has its exact text label and a description; the dashed low-history swatch is described in words |
| Charts | each chart panel carries a text summary of its data (`role=img` with the values) |
| Warnings, missing data, disabled controls | warning blocks are labelled notes with text titles; missing values read "Not available." with the documented reason; disabled controls have descriptions |

### 2.4 Map-provider configuration
- **Separate from the data source.** `src/config/basemap.js` is independent of `src/config/dataSource.js`; a test confirms that tile settings do not change the data configuration and that tile URLs appear only in the basemap module.
- **Variables:** `VITE_BASEMAP_URL`, `VITE_BASEMAP_ATTRIBUTION`, `VITE_BASEMAP_SUBDOMAINS`, `VITE_BASEMAP_MAX_ZOOM`, `VITE_BASEMAP_FILTER` (auto/on/off) and `VITE_BASEMAP_LABEL`, documented in the README ("Map provider configuration") and `.env.example`.
- **Demo default unchanged:** OpenStreetMap tiles, darkened by CSS.
- **Attribution always visible:**
  - in the map attribution control, with the OS Open Roads and DfT STATS19 credits;
  - in a new credit line under the overview's inline map crops, which had none before.
- **Safeguards:**
  - a custom provider without attribution triggers an on-map notice;
  - repeated tile failures show a notice ("Basemap tiles from … could not be loaded. Road segments are still drawn"), checked in the browser with an unreachable host;
  - the notice uses a neutral edge, because status amber is banned on the map canvas.
- **What was not done:** no API key was invented or stored, and no mapping dependency was added. The README explains how to switch to an approved provider and to restrict keys by referrer.

## 3. Tests and build

| Check | Result |
|---|---|
| Frontend tests, `npm test` | **43 passed, 0 failed, 0 skipped** (34 before Phase 5). New: rank-group partition and boundaries, label/boundary agreement, rejection of bad groups, branding, basemap configuration and separation, accessible markup of the filter rail and results list |
| Production build, `npm run build` | passes; the content test also scans `dist/` for fixture strings and the removed score: clean |
| ML suite, `pytest ml/tests` | **133 passed** (131 before; +2 tier tamper cases), none skipped |
| `validate_frontend_demo.py` on the regenerated bundle | matches the v2 release, including the new partition checks |
| `validate_contract.py` on `data/v2` and on the integration fixture | all files conform |
| `artifact_manifest.py verify` / `verify phase3` | 45/45, 78/78 unchanged |
| README number check | 38/38 |
| Original v2 map (`ml/demo/blackspot_map_v2.html`) | hash unchanged |

**Browser checks** (in-app browser, dev server; real key presses):
- **Keyboard path:** the skip link appears on Tab (230 × 39 px) and moves focus to the list. Tab into the list, then Down, Down, End (row 150, the page size), Home, Down, Enter opens rank 2. Focus is on the segment heading and the live region announces it. Shift+Tab twice reaches "Back" (Chrome makes the scrollable panel a focus stop). Enter returns focus to the same row.
- **Rankings:** arrow keys plus Space open the segment.
- **Visible focus:** focus rings measured as a 2 px teal outline.
- **Content:** branding and titles on every screen; the exact rank-group legend with the cutoff note; all four axis labels on the statistics chart (fixed during testing); chart summaries; population denominators.
- **Layout:** 375 px phone width, no horizontal scroll.
- **Failure states:** the tile-failure notice with an unreachable provider (the temporary server was stopped afterwards).
- **Console:** no errors on any screen.

**Not done:** no screen-reader session (NVDA, JAWS or VoiceOver), no full WCAG audit, and no
contrast measurement. This was an improvement pass with automated semantics checks and manual
keyboard tests, not an accessibility certification.

## 4. Product invariants re-verified

| Invariant | Evidence |
|---|---|
| The local UK demo works without a backend | tests load the bundle from disk; the production build was checked in Phase 4 and rebuilt now; the dev server reads only `public/data` |
| The predicted KSI burden is shown separately from rank and group | the panel shows the forecast with units and a separate group/rank badge; list rows show "x.xx expected KSI" and the group badge separately |
| Missing exposure never becomes a zero rate | bundle, data-layer and render tests (rate shows "Not available." and no digit) |
| Missing explanation and stability handled | render tests show "Explanation not available." and "Not available." for stability; adapter tests cover missing files |
| Results follow `rank` | sort tests including the tied pair; national ranks unchanged in the catalog test |
| Population statistics state their denominator | statistics KPIs name national / loaded / selection; checked in the browser |
| The 1,006-record demo is never presented as national | the provenance strip on every screen ("1,006 of 1,827,550 scored segments loaded"); bundle test; statistics note "not a sample: do not read its totals as national" |
| No fabricated 0–100 score | content test over source, docs and `dist/`; the badge shows group and rank only |
| Production model, forecast and backend schema unchanged | manifests 45/45 and 78/78; contract validator; v2 map hash |

## 5. Remaining warnings
- **Accessibility:**
  - map lines are still not keyboard-focusable (canvas renderer, kept for performance); the list, search and skip link are the alternative;
  - no screen-reader or contrast audit was run;
  - Chrome adds the scrollable detail panel as an extra focus stop.
- **Basemap:**
  - the demo relies on OpenStreetMap's public tiles, which are for light use only;
  - a production provider (with key and terms) or self-hosted tiles must be chosen before deployment;
  - placeholder images (such as CARTO's "API key required") cannot be detected automatically.
- **Basemap labels:** "United Kingdom", "Belfast" and similar come from the tile provider. The UI states GB-only coverage, but the basemap shows Northern Ireland without data.
- **Brand assets:** the favicon is the pre-existing generic mark; no Veyra logo was designed (out of scope).
- **Dependencies:** `leaflet.heat` is unused but still declared; Recharts 2 is flagged deprecated upstream.
- **Data scope:**
  - the explanation-missing state does not occur naturally in the v2 release; it is shown only when a source omits the extension;
  - the demo holds 1,006 of 1,827,550 segments, by design;
  - the backend is not connected.

## 6. Outstanding backend decisions (teammate)

From `frontend/BACKEND_INTEGRATION.md` (§5 and the new §8 checklist):

| ID | Decision |
|---|---|
| D1 | release metadata endpoint, including `tiers` and `tier_rules` (§1a) |
| D2 | geometry delivery (GeoJSON by bbox or vector tiles); lines beyond the top 5,000 |
| D3 | single-event sensitivity endpoint |
| D4 | server-side filter parameters (`rank_min`/`rank_max` inclusive, road class, …) or a bulk summary |
| D5 | search semantics |
| D6 | national context: served or static |
| D7 | absence semantics: 404 or `{"available": false}` |
| D8 | pagination |
| D9 | release identifier and sha256 check against `release_manifest_v2.json` |

Plus a deployment decision, not a backend one: the production tile provider.

## 7. Readiness

**The frontend side is ready for integration.** It has consistent Veyra branding, exact and
validated rank groups, an improved and keyboard-tested interface, a documented and separate
tile-provider configuration, and a backend checklist with an open-items table. Full integration
waits on decisions D1–D5 (needed to implement `src/data/apiSource.js`) and on the production
tile-provider choice.

## 8. Checklist

| Requirement | Status |
|---|---|
| Worktree verified; no branch switch, discard, commit or push | **PASS** |
| Veyra branding (nav, titles, metadata, README, DESIGN, checklist) without implying NI or other countries | **PASS** |
| Rank groups exact, mutually exclusive, documented floor rule, no gaps or overlaps, ranks unchanged | **PASS** |
| Accessible labels for search and filters | **PASS** |
| Keyboard navigation and selection through results; visible focus; selection announced | **PASS** (manual keyboard test + automated semantics) |
| Legend colours with readable text; warnings, missing data and disabled controls described | **PASS** |
| Full screen-reader / WCAG audit | **NOT IMPLEMENTED** (not performed) |
| Map lines themselves keyboard-reachable | **WARNING** (list alternative; canvas kept for performance) |
| Map attribution visible; provider configuration documented and separate from data | **PASS** |
| Production tile provider chosen | **WARNING** (deployment decision; OSM demo default) |
| Local demo without backend; burden separate from rank; no zero rates; missing data handled; rank order; denominators; subset labelled; no 0–100 score | **PASS** |
| Production model, forecasts, backend schema unchanged | **PASS** |
| Frontend tests and production build | **PASS** (43/43; build OK) |
| ML contract validation and ML suite | **PASS** (133 passed; both validators clean) |
| Backend implementation | **NOT IMPLEMENTED** (teammate's; decisions D1–D9 open) |
