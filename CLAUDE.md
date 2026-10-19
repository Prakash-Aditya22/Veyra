# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The ML half of a university group project: **road blackspot detection for Great
Britain**. Backend (Spring Boot), frontend (React/Leaflet) and architecture are
owned by teammates. This repo produces the data and models they consume.

Deliverables: **expected KSI casualties per ~500 m road segment** (the primary
product), Empirical Bayes excess and exposure-adjusted rates beside it, a
**deployable severity model**, and **SHAP explanations** of that model.

There are two generations. **v2** (`ml/pipeline.py`, `ml/blackspot/`) is current.
**v1** (`ml/build_recent.py`, `ml/road_segments.py`, `ml/severity_*.py`) is
superseded but kept runnable, so its committed outputs stay reproducible. Do not
"fix" v1 in place. Its defects are documented in
`ml/reports/preliminary_audit.md`.

## Running things

Use the project venv: `.venv/Scripts/python` (Windows). Exact pins are in
`ml/requirements.txt`, the full freeze in `ml/requirements-lock.txt`. Do not
install into the global Python.

```bash
.venv/Scripts/python ml/blackspot/download.py stats19 aadf os_open_roads guide   # once, ~1.6 GB
.venv/Scripts/python ml/pipeline.py data|network|snap|coverage|develop|holdout|forecast|severity
.venv/Scripts/python -m pytest ml/tests
.venv/Scripts/python ml/audit/final_audit.py
```

`network` (~13 min), `develop` (~2 h) and `holdout` (~1 h) exceed a 10-minute
foreground timeout, so run them in the background. Only `download.py` needs
internet. `stats19_recent.csv` (v1 extract, repo root) is reused for 2015–2020.
Downloads go to `ml/raw/` and intermediates to `ml/interim/` (both gitignored).
Run Python that reads downloaded files with `-I`.

## Non-negotiable protocol

- **Fold convention** (`features.Fold`): train on features c-4..c-2 → target c-1..c; test on features c-2..c → target c+1..c+2. Dev cutoffs 2019–21, **final holdout cutoff 2023 (target 2024–25)**, production cutoff 2025 (forecast 2026–27).
- `develop` writes `ml/outputs/frozen_spec.json` with a hash. `holdout` refuses to run without it. **Never change the spec after looking at holdout results.** If you must, document the change as post-hoc.
- Segments come from OS Open Roads only (`network.segment_network` takes no crash input). Eligibility is road class, never crash history.
- Every model and baseline is evaluated on the same rows (`experiment.evaluate`). Capture ties count at their expected value (`WeightedRanker`). CIs come from a 50 km block bootstrap, never a row bootstrap.
- `ml/tests/test_leakage.py` and `ml/audit/final_audit.py` check these. Keep them passing.

## Data traps (each has caused a bug here)

- **Severity labels drift.** CRASH/COPA injury-based reporting went from 6% of casualties (2015) to 86% (2025), and the Met switched in 2024, inside the holdout. The primary target is therefore **DfT severity-adjusted KSI casualties** (`adj_ksi_cas`). The severity classifier trains on injury-based records only.
- **Ten fields leak severity.** Adjusted and enhanced severity fields are targets or history only, never features describing the same collision. Police attendance responds to severity.
- **KSI casualties ≠ KSI collisions.** v1 counted collisions while claiming casualties.
- **Casualty key**: `casualty_reference` is not unique (one 2016 collision reuses it). Use `(collision_index, vehicle_reference, casualty_reference)`.
- **2024 code changes**: `junction_detail_historic` is blank for 59% of 2024 and 87% of 2025 records. `special_conditions_at_site` is 61–87% unknown from 2024. 2024-format `junction_detail = 0` includes roundabouts. `junction_control = -1` means "not at junction" in practice. Labels come from the official guide via `blackspot/codes.py`.
- **Road numbers are not geographically unique**, which is handled by network topology (same number, no shared node, separate stroke).
- **Large downloads truncate silently.** `download.py` checks bytes, MD5 where published, last-record field count and zip CRC.

## Honest results: do not overstate

See `ml/reports/final_audit.md` for the numbers. The shape of the findings:
- On segments **with** crash history, models beat raw crash counts by small margins. Crash history dominates.
- Most of the models' advantage over count baselines on the full network comes from ranking roads **without** recent crashes (road type, junctions, neighbours). Counts cannot rank those, because they tie at zero.
- AADF adds little *predictive* value on M/A roads once crash history is known. It changes the *interpretation* (rate vs burden).
- The deployable severity model is weak (ROC-AUC ≈ 0.58 on untouched 2025 data). Never present anything as "predicted severity".
- `police_force` is administrative. Do not present it as a cause. Rank SHAP categoricals by between-level spread computed **without unknown levels**.

## Phase 2 research (ml/experiments/)

`historical_windows.py`, `explain_blackspot.py` and `ranking_stability.py` are research
scripts. They never write production files; `ml/audit/artifact_manifest.py verify` and
`test_production_artefacts_unchanged` check this. The 2024–25 holdout has already been
examined, so do not tune against it. The production LightGBM was never saved by v2. Phase 2 (explainability)
reconstructed it exactly into `ml/outputs/explainability/production_lgbm.txt` (verified
against every stored score). Use that file rather than refitting when you only need
predictions. These jobs are memory-heavy on the 16 GB laptop (windows run ~8 GB): run one at
a time, use a single poller, and prefer the checkpoint/`--reuse-preds` paths over recomputing.

## Integration contract (Phase 3)

`data/v2/INTEGRATION_CONTRACT.md` is the ML → backend reference. `ml/blackspot/contract.py` holds the
field specs it documents (a test checks they match), and `ml/audit/validate_contract.py` checks a
release or the fixture in `ml/tests/fixtures/integration/`.
- **Changes are additive only within v2.x.** Never rename or redefine a column in place.
- **The backend orders by `rank`**, because the CSV score is rounded.
- **`rank_without_largest_collision` is the simultaneous definition.** Per-segment wording uses `segment_single_event_sensitivity_v2.csv`.
- **Protected files:** after any regeneration, run `ml/audit/artifact_manifest.py verify` and `verify phase3`. The `phase3` set adds the Phase 2 research outputs. Then rerun `ml/audit/release_manifest.py` and `make_integration_fixtures.py`.

## Frontend demo (Phase 4)

The GB frontend is on local branch `frontend-uk-demo`, in the worktree `.worktrees/frontend-uk`
(excluded via `.git/info/exclude`). Never switch this tree's branch to reach it.
- **Bundle:** its data are `frontend/public/data/demo-v2`, built by `ml/demo/make_frontend_demo_data.py` and checked by `ml/audit/validate_frontend_demo.py`. Regenerate the bundle after any release change, never hand-edit it.
- **Commands:** `npm test` and `npm run build` in `.worktrees/frontend-uk/frontend`.
- **Scope:** the backend is not connected; see `frontend/BACKEND_INTEGRATION.md` there.
- **Rank groups:** they are exact rank bands from the bundle manifest (`tiers`, `tier_rules`; top-1% cutoff = floor(N/100)). Never relabel them as "Top 1,000"-style overlapping names, and never recompute rank or score. Tile settings (`src/config/basemap.js`) stay separate from the data source (`src/config/dataSource.js`).

## Layout

See `ml/README.md`. `ml/archive/` holds superseded experiments. Keep them;
`ml/archive/README.md` classifies which are valid negative results and which
are unreliable or invalid.
