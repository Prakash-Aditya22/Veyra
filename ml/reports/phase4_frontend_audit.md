# Phase 4 frontend audit: what the `frontend-v1` branch assumed, before any change

*2026-10-14. Read-only inspection of `origin/frontend-v1` before building the Great Britain
demo. Nothing in the ML working tree was changed by the audit.*

## 1. Repository state recorded at the start

| Item | Value |
|---|---|
| ML working tree | branch `ML`, HEAD `8f13aa4`, 9 modified tracked files, 72 untracked (Phase 2–3 work); nothing staged; no stash |
| `frontend-v1` | `cd32390`, identical to the remote (`git ls-remote`) |
| `main` | `d17ceba` (README only) |
| Backend code | none in any branch |
| Protected artefacts | 45/45 (`phase2` manifest) and 78/78 (`phase3` manifest) unchanged |
| Tools | Node 24.14, npm 11.9; the frontend has **no test runner** |

**How the frontend was inspected and changed safely:**
- **Inspection:** `git show origin/frontend-v1:<path>`, which never touches a working tree.
- **Changes:** made in an **isolated git worktree**, `.worktrees/frontend-uk`, on a new local branch `frontend-uk-demo` created from `origin/frontend-v1` with `--no-track`, so a push cannot reach `frontend-v1` by accident.
- **ML tree:** the directory is listed in `.git/info/exclude`, a local file that is not committed, so the ML tree's status is unchanged. No checkout, reset, clean or stash was run.

## 2. Files carrying the demonstration fixture or the 0–100 score

A search of the branch found 232 occurrences in 24 files.

| File | Assumption |
|---|---|
| `src/data/blackspots.js` | 30 hand-authored "clusters" on the Bhubaneswar–Cuttack–Puri corridor (India). Coordinates are real places, but incident counts, severity splits, 0–100 scores, dates, contributing factors and landmarks are invented, and hourly histograms are generated from a seeded random number generator. Also exports `DATASET` (21,847 "records", `isDemo`), `MAP_CENTER` [20.30, 85.83] and zoom 11 |
| `src/data/series.js` | invented dataset-level series (monthly counts, yearly severity) and **`MODEL_RUN`, invented model metrics**: DBSCAN ε 180 m, silhouette 0.61, macro-F1 0.73, fatal recall 0.68. No pipeline run produced them |
| `src/lib/risk.js` | four tiers on a fixed 0–100 "composite danger score" (Watch 0–24 … Critical 75–100), plus "No Data" for unscored clusters |
| `src/lib/filters.js` | Indian road classes (NH-16, SH-13 …), monsoon/"pilgrim" factor matching, periods anchored to the fixture's dates |
| `src/lib/stats.js` | aggregates fixture incidents, hourly histograms and factor weights |
| `src/lib/format.js`, `charts/ChartFrame.jsx`, `motion/CountUp.jsx` | `en-IN` number formatting |
| `src/components/DetailPanel.jsx` | "Composite danger score … fixed 0 to 100 scale", km/h speed limits, landmarks, synthetic hourly histogram |
| `RiskBadge.jsx`, `Legend.jsx`, `MapCanvas.jsx`, `ResultsPanel.jsx`, `ProvenanceStrip.jsx` | display the 0–100 score and its tiers; the map is centred on Odisha; a heat layer mixes score and incident counts |
| `src/routes/Landing.jsx`, `Explorer.jsx`, `Rankings.jsx`, `Statistics.jsx` | corridor copy, `MODEL_RUN` metrics, "a few stretches account for most of the harm", fixture KPIs |
| `index.html` | meta description of the corridor and "composite danger scoring" |
| `README.md`, `DESIGN.md` | fixture contract (0–100 `score`, incidents, landmarks, hourly) and score-based tier definitions |

**What the original build did honestly:**
- the provenance strip and footer said "Demonstration dataset";
- the README said nothing was derived from real data.

**The problems for this project:**
- **Geography:** wrong country.
- **Score:** a score scale no ML output supports.
- **Invented metrics:** model metrics presented as if from a run.
- **Unsupported claim:** the claim that "a few stretches account for most of the harm" is false for GB. The national top 1,000 segments carry 4.5% of the forecast burden.

## 3. Architecture found

| Aspect | Finding |
|---|---|
| Framework | React 18, react-router 6, Vite 6, react-leaflet 4 / Leaflet 1.9, Recharts 2 (npm reports v2 as deprecated), Motion, GSAP |
| Data access | components import the fixture module directly; no adapter, no configuration, no fetch |
| Tests | none |
| Basemap | CARTO Dark Matter. Checked now: it returns a 2.5 KB "API key required" placeholder for every tile, so the original map rendered no basemap |
| Branding | the wordmark is "Blackspot Atlas"; "Veyra" appears nowhere in the repository |
| Accessibility | good base: labelled inputs, native buttons, `aria-sort`, reduced-motion support, text labels on every tier colour |

## 4. Plan adopted (minimal, within the existing architecture)

1. **Demo bundle.** Generate a deterministic bundle from the v2 release on the ML side (`ml/demo/make_frontend_demo_data.py`). It holds the national top 1,000 plus the integration-fixture reference cases, copied verbatim, with a validator that cross-checks every value against `data/v2`.
2. **Data layer.** Add a data layer (`src/config/`, `src/data/`) with a local adapter and an API adapter. The API adapter is limited to the endpoints suggested in the contract and fails loudly on everything unagreed.
3. **Score replaced.** Replace the 0–100 score with **national-rank tiers** (Top 100 / Top 1,000 / Top 1% / Below top 1%) on the same four-colour ramp. Show the real forecast with its units everywhere; no percentile is needed.
4. **Screens rebuilt.** Keep the screens and design system, and rebuild their content on real fields:
   - panel sections for forecast, rank range, warnings, history, explanation and rate;
   - search and filters on real fields;
   - statistics with named populations.
5. **Fixture removed.** Delete the fixture modules, update the README and DESIGN.md where they encoded the old score, and add tests and a backend checklist.
6. **Basemap.** Make the basemap configurable: OpenStreetMap darkened by CSS by default, a keyed provider optionally.
