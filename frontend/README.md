# Veyra (frontend)

**Veyra, Great Britain Road Safety Intelligence.** The map-first interface for the Veyra
road-safety project. It shows **Great Britain road segments ranked by the ML forecast of expected
killed-or-seriously-injured (KSI) casualties for 2026–27**. For each segment it shows the recorded
history, rank stability, model explanation, warnings and, where valid, the per-vehicle rate.
Built to the design system in [`DESIGN.md`](DESIGN.md).

Coverage is **Great Britain only (England, Scotland, Wales)**. The ML release uses DfT STATS19 (GB)
and OS Open Roads (GB); it makes no claim about Northern Ireland or anywhere else.

## Running it

```bash
npm ci            # exact versions from package-lock.json
npm run dev       # http://localhost:5173, local demo data, no backend needed
npm test          # data, adapter, rank-group, branding, basemap, content and rendering tests
npm run build     # production build in dist/
```

## Where the data come from

The app reads the **v2 ML release** (ML branch, `data/v2/`, documented in
`data/v2/INTEGRATION_CONTRACT.md`) through one data layer:

| File | Role |
|---|---|
| `src/config/dataSource.js` | the only place that decides the **data** source: `VITE_DATA_MODE` (`local` or `api`), `VITE_API_BASE_URL`, `VITE_LOCAL_DATA_URL` (see `.env.example`) |
| `src/data/localSource.js` | local mode: the verified demo bundle in `public/data/demo-v2/`, fetched once and cached |
| `src/data/apiSource.js` | API mode: **not connected**. Uses only the endpoints *suggested* in the contract; every unagreed one fails with a clear message (see `BACKEND_INTEGRATION.md`) |
| `src/data/normalize.js` | contract records → what the UI shows; rate, explanation, stability and single-event views, each with an explicit "not available" state |
| `src/data/catalog.js`, `DataContext.jsx` | loads the catalog once per session, checks the rank groups, shares it across screens |
| `src/config/basemap.js` | the **map tiles**, configured separately (see "Map provider configuration") |

Components never compute a risk value. They show the ML forecast, the documented rank and the
optional extensions as delivered.

### The local demo bundle (`public/data/demo-v2/`, about 3 MB)

**Real records, not a fixture.** It is generated on the ML branch by
`ml/demo/make_frontend_demo_data.py` from the v2 release and verified value by value by
`ml/audit/validate_frontend_demo.py`. `manifest.json` records the release hashes, the selection
rule, the rank groups and the counts.

**Selection (deterministic):**
- the **national top 1,000** segments by rank, complete;
- **6 lower-ranked reference cases** from the ML integration fixture: no recent collisions, the tied pair, rank 50,000, the lowest-ranked exported row, and a segment outside the line-geometry file.

That makes 1,006 segments. It is a top-ranked subset of the 1,827,550 nationally scored segments,
**not a sample and not the national map**. Its sums and shares describe the subset only, and every
screen says how many of the national segments are loaded.

### What each number means

- **Forecast** (`blackspot_score`): expected KSI casualties on the segment over 2026 and 2027 combined, on DfT's severity-adjusted scale. It is a burden (an expected count), not a probability of a collision and not a per-vehicle risk. It is always shown with its units, separately from the rank.
- **Order:** always by `rank`. The release CSV rounds the score, so the UI never re-ranks by score.
- **National rank groups:** four contiguous, mutually exclusive bands of `rank`, used for the legend, colours and filters (table below). There is no 0–100 score.
- **Rank range:** the 5th–95th percentile across 20 model refits. Neighbouring ranks are not meaningfully different.
- **Per-vehicle rate:** a 2023–25 rate, shown only where a DfT traffic count exists and the segment is at least 250 m long. Otherwise "Not available" with the reason, never zero.
- **Model explanation:** the top 5 of 45 TreeSHAP attributions of the production model. These are associations, not causes. If none exists, the UI shows "Explanation not available".

### National rank groups

| Group | Ranks | Description |
|---|---|---|
| Ranks 1–100 | 1 to 100 | the national top 100 |
| Ranks 101–1,000 | 101 to 1,000 | the rest of the national top 1,000 |
| Ranks 1,001–18,275 | 1,001 to 18,275 | the rest of the national top 1% |
| Ranks 18,276–1,827,550 | 18,276 to 1,827,550 | all remaining scored segments |

- **Top-1% cutoff:** 1% of the 1,827,550 nationally scored segments, **rounded down**: floor(18,275.5) = 18,275.
- **Coverage:** the groups cover every rank from 1 to 1,827,550 exactly once.
- **Where they come from:** boundaries come from the release manifest (`tiers`, `tier_rules`), and labels are built from the boundaries (`src/lib/priority.js`).
- **Checks:** the app refuses a release whose groups overlap, leave a gap, or use another cutoff. Tests check every boundary rank. The ML-side validator checks the same rules.
- **Ranks unchanged:** groups only band the release `rank`; no score or rank is recomputed.

## Screens

| Route | Screen |
|---|---|
| `/` | Overview: what the forecast is, real figures from the release, methodology and holdout result |
| `/explorer` | Map of the loaded segments, search and filters, segment list, segment detail |
| `/explorer?segment=<segment_id>` | Deep link to one segment (stable contract ID) |
| `/rankings` | Sortable, searchable table in national rank order |
| `/statistics` | Summaries for the national model, the loaded subset and the current filter selection, each with its denominator |

There is no region or local-authority filter: the release has no reliable administrative field.

## Accessibility

What is implemented:
- **Labels and descriptions.** Search and every filter group have visible labels; counts read as "914 segments"; each rank group shows its description; the disabled "Reset filters" button explains why it is disabled.
- **The keyboard path to every segment.** Map lines are drawn on a canvas for performance and cannot take focus, so the segment list is the keyboard alternative: **Tab** reaches the list, **Up/Down** move between segments, **Home/End** jump, **Enter** opens one.
  - Focus moves to the segment's heading when it opens, and returns to its row after "Back to results".
  - A "Skip the map" link jumps from the map to the list.
  - The rankings table supports the same keys.
- **Announcements.** A polite live region announces the selected segment (rank, group, forecast with units) and, once typing settles, how many loaded segments match.
- **The map.** The map container has a name and keyboard instructions (arrow keys pan, plus and minus zoom). Every tier colour has its text label, and low history is shown as a dashed outline as well as in words.
- **Focus.** Every interactive element has a visible teal focus ring, drawn inside scrolling and clipped containers.
- **Page titles** name each screen ("Explorer · Veyra").
- **Charts** carry a text summary of their data.

What is **not** done:
- no screen-reader session (NVDA, JAWS, VoiceOver);
- no full WCAG audit;
- no colour-contrast measurement of the design-system palette.

Treat this as an improvement pass, not a certification.

## Map provider configuration

Map tiles are configured in `src/config/basemap.js`, **independently of the ML data source**:
changing tiles never changes which predictions are shown. Set the variables in `.env.local` (not
committed); see `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `VITE_BASEMAP_URL` | OpenStreetMap standard tiles | XYZ raster template, e.g. `https://tiles.example.com/{z}/{x}/{y}.png`; `{s}` and `{r}` are supported. `none`: no basemap (neutral background and a notice) |
| `VITE_BASEMAP_ATTRIBUTION` | OSM attribution | attribution HTML the provider requires. **Required** whenever `VITE_BASEMAP_URL` is set (the map shows a notice if it is missing) |
| `VITE_BASEMAP_SUBDOMAINS` | `abc` | letters for `{s}` |
| `VITE_BASEMAP_MAX_ZOOM` | `19` | the provider's maximum zoom |
| `VITE_BASEMAP_FILTER` | `auto` | `auto`: darken only the OSM default; `on`: always darken (a light provider); `off`: never (a dark provider) |
| `VITE_BASEMAP_LABEL` | the tile host | provider name used in the tile-failure notice |
| `VITE_BASEMAP_CORS` | `true` for the OSM default | `true` if the provider sends CORS headers: tiles are then loaded with `crossOrigin` so a provider's "Access blocked" image can be recognised |

**Example: CARTO with your own key.** CARTO's raster basemaps need a key since 25 September 2026.
They are free for non-commercial use up to 5 million requests a month: <https://carto.com/basemaps/apikey/>,
terms <https://carto.com/legal/basemap-terms/>. Put this in `.env.local` and restart `npm run dev`:

```
VITE_BASEMAP_URL=https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?key=YOUR_CARTO_KEY
VITE_BASEMAP_SUBDOMAINS=abcd
VITE_BASEMAP_ATTRIBUTION=&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>
VITE_BASEMAP_FILTER=off
VITE_BASEMAP_LABEL=CARTO
```

**The demo default.** CARTO Dark Matter, the design system's first choice, now returns an "API key
required" placeholder without a key. The demo therefore uses OpenStreetMap's standard tiles,
darkened and desaturated with a CSS filter. Attribution is always visible:
- in the map's attribution control, with OS Open Roads and DfT STATS19 credits;
- in a credit line under the overview page's inline map crops.

**For production.** OpenStreetMap's tile servers are for light use only
(<https://operations.osmfoundation.org/policies/tiles/>). Before deploying:
1. Choose an approved provider, with its own account, key and terms (any raster XYZ provider), or serve your own tiles.
2. Put its URL template, including the key if it uses one, in `VITE_BASEMAP_URL`, and its attribution in `VITE_BASEMAP_ATTRIBUTION`.
3. Set `VITE_BASEMAP_FILTER=off` for a dark style, or `on` for a light one.
4. Run `npm run build` and check that tiles load and the attribution is shown.

No key is stored in this repository, and none should be committed. A key used in a browser app is
visible to users, so restrict it by HTTP referrer at the provider.

**If tiles fail to load** (offline, wrong URL), or the provider sends OpenStreetMap's "Access
blocked" image, the map drops the basemap:
- it shows a neutral background and a "Basemap unavailable" notice;
- the road segments, ranks, legend and data credits stay.

The block image matters because OSM serves it as HTTP 200. Leaflet would otherwise draw it as a tile.
It was observed on 2026-10-17 in Chrome for the standalone ML maps opened from a file, which send
no Referer. The page recognises its yellow and black edge stripe (`src/lib/tileGuard.js`). This
needs CORS, which OSM allows.

The dev server sends `Referer: http://localhost:5173/` and gets real tiles. Do not open `dist/`
as a file.

Other providers' placeholder images (CARTO's "API key required") cannot be recognised; check
visually after any change. No mapping dependency was added: Leaflet's own tile layer is used.

Fonts (Fontshare, Google Fonts) and tiles are network dependencies; the data are not.

## Map performance

Below zoom 12, segments are drawn as midpoints, because a 500 m line is under a pixel. From zoom
12, they are drawn as their OS centrelines, on a canvas renderer. With 1,006 segments this is light.
The full release (50,015 rows) or the national model (1.8 M) must not be sent to the browser
whole: see `BACKEND_INTEGRATION.md` for the viewport and tile strategy the backend should provide.

## Things worth knowing before you change something

- **`global.css` is imported before `App.jsx` in `main.jsx`, deliberately.** Base `.btn` and `.label` rules must load before component CSS.
- **Leaflet applies `className` only when a path is created**, so the selected segment is keyed on its selected state in `MapCanvas.jsx`.
- **Grids that contain the wide table use `minmax(0, 1fr)`**, so the table scrolls inside its container on mobile.
- **Risk-ramp colours are for data only.** Every group colour carries its text label, and status amber never appears on the map canvas.
- **`CountUp` renders its true value on first paint and force-writes it after 1200 ms**: a figure frozen part way through a count is a wrong figure.

## Known limits

- **Not wired to the backend.** API mode is not connected; the backend endpoints are not agreed yet (`BACKEND_INTEGRATION.md`).
- **Partial geometry.** Line geometry exists only for the top 5,000 in the release.
- **Not built.** Route Risk Check and the Authority Dashboard (DESIGN.md items 6 and 7) are not built.
