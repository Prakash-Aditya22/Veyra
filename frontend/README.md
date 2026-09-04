# Blackspot Atlas

Frontend for the Accident Blackspot Detection & Visualization System. Built to
the design system in [`DESIGN.md`](DESIGN.md), which is the single source of truth for
colour, type, layout and motion. If this README and `DESIGN.md` disagree,
`DESIGN.md` wins.

## Running it

```bash
npm install
```

```bash
npm run dev
```

Then open `http://localhost:5173`. Production build:

```bash
npm run build
```

## Screens

| Route | Screen | Notes |
|---|---|---|
| `/` | Landing / Overview | Asymmetric hero with inline map typography, two capability rows, methodology, provenance |
| `/explorer` | Blackspot Explorer | The primary screen. Filter rail, map canvas, docked results panel, permanent legend |
| `/explorer?segment=<id>` | Blackspot Detail | The docked panel switches to detail for that segment id (e.g. `A23_run3_km0.5`). Deep linkable; the route screen's blackspot rows link here |
| `/rankings` | Rankings Table | Sortable, searchable, sticky header, sticky rank column |
| `/statistics` | Statistics Dashboard | Four panels on an asymmetric 2:1 grid, plus a weighted factor ranking |

## The data is a demonstration fixture

**Nothing in this build is derived from `AccidentsBig.csv` yet.** The road names
and coordinates in `src/data/blackspots.js` are real locations on the
Bhubaneswar / Cuttack / Puri corridor; the incident counts, scores and dates are
hand-authored stand-ins shaped like the clustering pipeline's output.

This is stated in the user interface too, in the provenance strip on every
screen and in the landing page footer, so the build never claims data it does
not have. Keep that honesty when you swap the real data in: if the pipeline has
not run, the interface should say so.

### Swapping in the real pipeline output

`src/data/blackspots.js` documents the exact shape the UI expects. Match it in
the Spring Boot response and no component needs to change:

```
id            stable cluster identifier
name          human-readable stretch name
lat, lng      cluster centroid
score         composite danger score, 0-100, one decimal, or null
incidents     total records in the cluster
fatal/serious/slight   severity split, must sum to `incidents`
lastIncident  ISO date of the most recent record
roadType, roadClass, speedLimit
factors       [{ label, weight }], descending
landmarks     [string], nearest first
hourly        [{ hour, count }], 24 entries
```

Replace the module's export with a fetch, and update `DATASET` in the same file
(`label`, `records`, `computedOn`, `isDemo`). `score: null` is meaningful: it
renders as the No Data tier, never as low risk.

The two dataset-level chart series live in `src/data/series.js` and cover every
record in the window, not only clustered records. The charts that use them say
so beneath their titles.

## Motion

All timings live in `src/lib/motion.js` and follow DESIGN.md section 6: one
spring (stiffness 100, damping 20), a 30ms stagger step, a 180ms cross-fade.
Nothing invents its own timing.

Three reusable pieces in `src/components/motion/`:

| Component | What it does | Where |
|---|---|---|
| `Reveal` | Scroll-triggered fade plus a 14px settle, `viewport.once` so it never replays | Landing sections, statistics panels, factor rows |
| `CountUp` | A figure springs from zero to its value when scrolled into view | Landing metrics, dashboard KPI strip |
| `SpringBar` | Proportion bar grows via `scaleX` from a left origin | Severity split, contributing factors |

`<MotionConfig reducedMotion="user">` in `App.jsx` makes every Motion component
in the tree respect the operating system setting, rather than each component
checking for itself.

Two rules this product holds harder than the animation is worth:

- **Bars animate `scaleX`, never `width`.** Width forces layout every frame, and
  DESIGN.md restricts animation to transform and opacity.
- **`CountUp` renders its true value on first paint and force-writes it after
  1200ms**, whatever the animation did. A figure frozen part way through a count
  is a wrong figure, and this product reports casualty counts.

Perpetual motion is still limited to exactly two things, as the design document
requires: the selected marker's ring pulse and the header's dataset dot. Nothing
else loops.

**Not implemented:** DESIGN.md asks for spring-driven marker radius changes on
the map. Markers currently resize in one step when the filter set changes.

## Structure

```
src/
  styles/tokens.css      Every colour, size and duration in the product
  styles/global.css      Reset, type primitives, buttons, inputs, Leaflet overrides
  data/                  The demonstration fixture
  lib/risk.js            Tier boundaries and marker sizing
  lib/filters.js         Filter definitions and the pure filter function
  lib/stats.js           Aggregations over whatever clusters are in view
  components/            Shared UI, one CSS file per component
  routes/                One file per screen
```

## Things worth knowing before you change something

- **Tier boundaries are published and fixed.** They are stated in the legend and
  must not rescale per viewport or per filter. `tierOf` treats the upper bound
  as exclusive of the next tier's minimum, because scores carry one decimal and
  a literal `<= 74` would drop a score of 74.8 into No Data.
- **`global.css` is imported before `App.jsx` in `main.jsx`, deliberately.** The
  base `.btn` and `.label` rules must be injected before component CSS,
  otherwise they win same-specificity ties against a component's own overrides.
- **Leaflet applies `className` when a path is created and ignores it on later
  restyles.** That is why the selected marker is keyed on its selected state in
  `MapCanvas.jsx`; without the key the white ring never appears.
- **Grids that contain the wide table use `minmax(0, 1fr)`.** An `auto` column
  sizes to max-content, which lets the table push the whole page sideways on
  mobile rather than scrolling inside its own container.
- **The filter sheet animates with CSS keyframes, not an animation library.** An
  exit animation that has to complete before unmount can strand a full-screen
  sheet with no way to dismiss it.
- **Risk colours are for data only.** They never appear on interface chrome, and
  the interface accent (Beacon Teal) never appears on the risk ramp. Status
  green and amber are banned from the map and from every chart.
- **Every risk colour carries a text label.** Colour alone never encodes tier.

## Fonts and tiles

Satoshi loads from Fontshare and JetBrains Mono from Google Fonts, both via
`<link>` in `index.html`. Basemap tiles come from CARTO Dark Matter. All three
are network dependencies: if you need a fully offline demo for the viva,
self-host the two font files and cache a tile set for the corridor first.

## Known limits

- The map fragments in the hero headline fetch nine basemap tiles each. They are
  small and above the fold, so they load eagerly on purpose.
- The explorer's short boot delay drives the skeleton state. Replace it with the
  real request's pending state when the API is wired up.
- Route Risk Check and the Authority Dashboard, items 6 and 7 in the design
  document's screen inventory, are not built.
