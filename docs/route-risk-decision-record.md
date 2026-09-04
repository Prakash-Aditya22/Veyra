# Route Risk — Decision Record

**Phase 1, built 2026-09-03 → 2026-09-04, on branch `integration`.**

What follows is the reasoning behind the route-risk feature: the decisions
taken, the measurements that drove them, and the defects found along the way.
Git history records *what* changed; this records *why*, and what was tried and
rejected. Most of it is material a report or viva will ask about.

The working log this was distilled from lived in
`.superpowers/sdd/2026-09-03-route-risk-phase1/progress.md` (git-ignored
scratch).

---

## 1. The problem the branch started from

Three branches held three disconnected halves:

- `ML` — a finished Python pipeline and 45,014 scored road segments
- `frontend-v1` — a working React/Leaflet app
- `main` — a README

They had been built against **different projects**. The frontend's fixture
header described "the Bhubaneswar / Cuttack / Puri corridor" and a DBSCAN
clustering pipeline. The ML output was British roads scored by a chainage-based
Poisson model. The field contracts did not overlap: the UI wanted a 0–100
composite score, `incidents`, a `lastIncident` date and weighted `factors`; the
data had expected-KSI on 0–9.67, `n_crashes`, and no dates at all.

There was no backend of any kind.

**Decision:** keep the British data, retheme the frontend, and write the Spring
Boot backend that had never existed. Rebuilding the ML pipeline on an Indian
dataset would have cost weeks and depended on data nobody had.

---

## 2. Architecture decisions

| Decision | Chosen | Why, and what was rejected |
|---|---|---|
| Where route-risk logic runs | Spring Boot backend | Keeps the OpenRouteService key server-side. A frontend-only version would have put the key in the browser. |
| Database | Supabase Postgres + PostGIS | Real `ST_DWithin` corridor queries in metres. Rejected: in-memory (45,014 rows is small enough that a database is academically expected rather than technically required — worth saying plainly). |
| Routing + geocoding | OpenRouteService | One free key covers both, with a real quota. Rejected: OSRM demo + Nominatim (keyless but explicitly "no heavy use"), self-hosted OSRM (~1.5 GB extract, an hour of preprocessing). |
| Repo shape | one `integration` branch | `main` + `ML` + `frontend-v1` merged cleanly; `backend/` added alongside. |
| Backend port | **8081** | 8080 is permanently held by Oracle's TNS Listener on the development machine. |

### Row Level Security

Supabase warned that `road_segment` had no RLS. It was enabled. This costs
nothing: the backend connects as the table's owner, which bypasses RLS. Without
it, anyone holding the public `anon` key — which is designed to ship in
frontend code — could read *and delete* all 45,014 rows through Supabase's
auto-generated REST API.

---

## 3. Two calibrations that were measured, not guessed

Both of these started as plausible-looking defaults that turned out to be
wrong. Both were settled by measuring against the real data.

### 3.1 Route alternatives — `share_factor` 0.6 → 0.2

OpenRouteService returns up to three alternative routes. The natural default
produced three routes that were all 22.3 km and 62–63 minutes — suspiciously
alike. Measuring the actual geometric overlap (the fraction of a route's
coordinates lying within 50 m of the fastest route), Croydon → Camden:

| `share_factor` / `weight_factor` | overlap with route 0 | distance |
|---|---|---|
| 0.6 / 1.6 | **45.8%, 45.6%** | 22.3 km |
| 0.4 / 1.6 | 28.6%, 34.1% | 24.7 km |
| **0.2 / 2.0** | **1.9%, 7.0%** | 27.4 km |

At 0.6 the "alternatives" shared nearly half their road with the fastest route,
so they would have passed the same blackspots and the fastest-versus-safest
comparison — the entire point of the feature — would have shown three
near-identical cards.

**This single parameter is the difference between the feature working and the
feature being pointless.** It is now configurable in `application.yml` so it can
be retuned for different endpoints without a rebuild.

### 3.2 Risk tiers — recalibrated to the population users actually see

The published tier scale (Watch / Elevated / Severe / Critical over 0–100) was
first mapped from cutoffs derived from all 45,014 segments, where "Critical"
is a sensible 3.3%.

But the UI filters to `n_crashes >= 6`, because 86% of segments rest on fewer
than six crashes and their scores are noise. That filter strips out
overwhelmingly low-scoring rows, so the displayed population is far riskier
than the whole:

| | all 45,014 | displayed (≥6 crashes, 6,213) |
|---|---|---|
| median | 0.25 | **0.94** |
| p90 | 0.81 | **2.24** |

Under the original cutoffs, **23.3% of displayed segments landed in "Critical"
and 60% in Severe-or-worse** — a red screen that distinguishes nothing. This is
exactly the outcome percentile-mapping had been rejected to avoid, reproduced
in the filtered population.

Final cutoffs `0.94 / 1.57 / 3.09` are the 50th/80th/95th percentiles of the
displayed population, giving roughly 50/30/15/5%.

**The honesty condition attached to this:** the tiers are now *relative*. A
segment shown as "Watch" at 0.90 still sits above the national median of 0.25.
The legend states this. Without that disclosure the recalibration would quietly
understate risk, and the choice would not be defensible.

---

## 4. The honesty constraints, and why each exists

These are load-bearing. Several were violated during development and had to be
fixed, which is the best evidence they were worth writing down.

**`blackspot_score` is a prediction, not a tally.** It is a LightGBM Poisson
regression's output: expected killed-or-seriously-injured casualties on that
500 m over two years, *across all traffic*. The 2022–23 target window is held
out from the 2019–21 features precisely so the number is a forecast.

The Route screen initially shipped a sentence reading *"Risk figures are
**recorded** killed-or-seriously-injured casualties **accumulated** on each
corridor."* That was the only place the screen defined the number for a reader,
and it stated the opposite of what the number is. The phrasing originated in
the spec — guarding hard against one misreading ("your journey is 4.2
dangerous") introduced a different false claim in its place.

**But `n_crashes`, `n_ksi`, `n_fatal` ARE genuine recorded counts** from
2019–21. Describing *those* as expected is equally wrong. Both directions were
checked when the fix landed.

**`future_ksi` / `future_fatal` never reach the database or a response.** They
are the 2022–23 outcome the model was validated against; serving them shows the
answer it was graded on. There is deliberately no such column, no such record
field, and no reader mapping — and a test asserts the API's wire surface is
exactly 18 named keys, so a future column reaching JSON under *any* name fails
the build. The absence of the column is the enforcement, not a comment.

**Nothing is labelled "predicted severity."** The deployable severity model has
ROC-AUC 0.658 — a weak predictor — and the ML documentation forbids that
framing.

**"Safest" is an unnormalised sum.** `expectedKsi` is the plain sum of matched
segment scores, so it grows with route length. The UI says so.

---

## 5. Defects worth recording

### 5.1 A credential leak, and its root cause

During the data load, an ad-hoc `DriverManager` probe threw an `SQLException`
whose message embedded the **full `DATABASE_URL` including the password**, and
printed it. The agent that did it self-reported immediately. A scan found the
value in exactly two files (a transcript, and `.env` where it belonged); it was
never in git. The password was rotated and the transcript deleted.

The instructive part: the rule in force was "never print `.env`", and that was
followed. It was not enough, because *JDBC exceptions embed the connection
string*. The rule was widened to: no ad-hoc probes outside the app, and report
exception type and message only, never a full stack trace.

### 5.2 The `.env` loader that silently truncated an API key

The backend received `403 {"error": "Access to this API has been disallowed"}`
from OpenRouteService on every request, while direct calls with the same key
succeeded. Two full fix rounds failed to explain it.

The documented `.env` loader was:

```bash
while IFS='=' read -r key value; do export "$key=$value"; done < .env
```

Setting `IFS='='` makes `read` treat **every** `=` as a field separator, so a
value whose last character is `=` loses it. The ORS key is base64-shaped and
ends with `=`. Every run loaded it one character short.

`DATABASE_URL` escaped only by luck — it does not end in `=`. So the database
worked perfectly, which made the loader look correct.

The fix is parameter expansion, which splits on the first `=` only:

```bash
while IFS= read -r line; do export "${line%%=*}=${line#*=}"; done < .env
```

Two further traps in the same area, both now documented in `backend/README.md`:
`source .env` breaks because the `&` in `DATABASE_URL` is a background-job
operator; and the routing engine's structured `{"error":{"code":2010}}` is a
different failure from the auth layer's bare `{"error": "..."}` string — telling
them apart is what located this bug.

### 5.3 Two tests that would have passed with the feature broken

- A corridor-filter test asserted `strict.size() <= loose.size()`. If the filter
  were ignored entirely, both queries return identical sets, `<=` holds, and the
  follow-up check passes vacuously. Replaced with an assertion that the loose
  result *contains* segments the strict one excludes.
- A leak guard asserted two specific field names were absent — catching nothing
  if a leak arrived under a different name. Replaced with an exact key-set
  assertion.

### 5.4 `NO_ROUTE` never fired

The client inferred "no route" from an empty `features` array. Probing the live
API showed OpenRouteService actually returns **HTTP 404 with error code 2010**.
So a permanently impossible route was reported to users as "temporarily
unavailable, try again" — inverting the one distinction the error type existed
to make.

### 5.5 A rename that broke working links

Explorer's deep-link parameter was renamed `?cluster=` → `?segment=` to serve
the new Route screen. Two pre-existing callers — Rankings and Landing — were
not swept, so links that **worked before the branch** went dead. No per-task
review could see it; only the whole-branch review could.

The fix was not to rename those callers: they still read the Bhubaneswar
fixture, whose ids cannot resolve against the live API, so renaming would have
traded a dead link for a 404. Their navigation was removed until Phase 2.

---

## 6. Verification

The corridor query was computed **three independent ways** for Croydon → Camden
and the results agree:

| | Python from CSV | Service layer | HTTP |
|---|---|---|---|
| Fastest | 44 spots / 107.90 | 45 / 109.43 | 45 / 109.43 |
| Safest | 40 / 74.18 | 42 / 76.76 | 42 / 76.76 |
| Alternative | 38 / 87.81 | 40 / 90.39 | 40 / 90.39 |

The Python figure approximates the corridor as "within 50 m of a route vertex"
rather than PostGIS's true point-to-linestring `ST_DWithin`, which accounts for
the 1–2 segment difference. Same rank order, same magnitudes, two independent
implementations.

**The result that matters:** the safest route carries roughly **30% less
expected KSI for about 9% more travel time**, and the worst segment shifts
corridor entirely (A23 → A40). The comparison has real content.

Test counts at completion: **58 backend, 16 frontend**, clean production build.

---

## 7. Limitations to state in the report

1. **`blackspot_score` is partly an in-sample prediction.** The ML pipeline
   trains on 70% of segments and then scores 100% of them, so 77% of the top 500
   are rows the model memorised. The remediation plan at
   `docs/superpowers/plans/2026-09-01-ml-remediation.md` fixes this and was
   deliberately shelved to ship this feature.
2. **No exposure normalisation.** Segments rank by expected casualties, not
   casualties per vehicle-km, so 419 of the top 500 fall inside Greater London —
   a traffic-density map as much as a danger map. Comparing two London routes is
   meaningful; comparing a London route to a rural one is not.
3. **The model beats crash-counting by about one point** — 50.4% of future KSI
   captured in the top 20% of segments, versus 49.35% for ranking by raw crash
   count. It refines crash history rather than replacing it, which is why crash
   history is the standard blackspot criterion in practice.
4. **Injury collisions only.** STATS19 never records damage-only crashes.
5. **Great Britain only.** No Indian dataset with comparable coordinate
   precision and road numbering was available. The method transfers to any
   dataset carrying `(lat, lon, road id, date, severity)`.
6. **Rankings and Statistics still read a static fixture.** That is Phase 2, and
   they should not be demonstrated as live.
7. **The OpenRouteService free tier allows 200 directions requests per day** —
   not 2,000. Enough for development and a demo, but exhaustible.

---

## 8. Known follow-ups

- **Duplicate route cards.** OpenRouteService sometimes returns two identical
  alternatives, producing two identical cards. Visible in a live run. A dedupe
  by `(distanceMetres, durationSeconds)` in `RouteRiskService` closes it.
- `MapCanvas.jsx` still carries hex literals; `Route.jsx` demonstrates the
  className-plus-CSS-token technique that removes them.
- The `nodata` tier filter is unreachable — `blackspot_score` is `NOT NULL`.
- `motion.js` now exports `CROSSFADE`; other timings could follow.
- No component tests: `vitest.config.js` uses the node environment with no
  jsdom, which is a deliberate Phase 1 position rather than an oversight.
