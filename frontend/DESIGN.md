# Design System: Accident Blackspot Detection & Visualization System

**Product:** A map-first web application that surfaces ML-derived accident blackspots, ranks road stretches by a composite danger score, and gives commuters and municipal authorities a way to read road risk at a glance.

**Audience:** Two modes of use in one interface — a commuter scanning a route in ten seconds, and a traffic authority reading a ranked table for twenty minutes. The design must serve the second without punishing the first.

**Use this document as the single source of truth when prompting Stitch for any screen in this product.**

---

## 1. Visual Theme & Atmosphere

A dark, instrument-grade interface with the composure of a transit operations console — quiet chrome, loud data. The atmosphere is factual and unsentimental: this product reports where people have been hurt, so nothing about it should feel celebratory, gamified, or playful. Think night-shift control room, not consumer travel app.

The chrome recedes to graphite and steel so that the only saturated color on screen is risk itself. When a stretch of road glows amber-to-oxblood on the map, that color carries meaning — it is never decoration. A screen where the interface is more colorful than the data has failed.

Layouts are asymmetric and rail-driven: a persistent filter rail, a dominant map canvas, and a docked results panel that never floats free over the map. Motion is restrained and functional — data settles into place, it does not perform.

**Calibration:**
- **Density: 7** (Data-forward, approaching cockpit — tight vertical rhythm, tabular numerals, minimal decorative padding)
- **Variance: 6** (Offset asymmetric — rail + canvas splits, no centered hero, no symmetric card rows)
- **Motion: 4** (Fluid but restrained — spring settling, staggered table reveals, no cinematic scroll choreography)

---

## 2. Color Palette & Roles

### Interface neutrals — one cool graphite family, no warm/cool drift

- **Deep Graphite** (`#131417`) — Application canvas, the base surface behind everything. Never pure black.
- **Panel Graphite** (`#1A1C21`) — Filter rail, docked results panel, table headers, modal surfaces.
- **Raised Slate** (`#22252B`) — Hover surfaces, selected table rows, input fills, tooltip bodies.
- **Structural Line** (`rgba(148, 163, 184, 0.14)`) — All 1px dividers, table rules, panel edges. Structure comes from hairlines, not shadows.
- **Bone White** (`#EEF1F5`) — Primary text, headline type, active values.
- **Steel Grey** (`#9AA2AE`) — Secondary text, labels, axis ticks, metadata, timestamps.
- **Dim Grey** (`#6B7280`) — Tertiary text, disabled states, placeholder copy, map attribution.

### Interface accent — exactly one, and it is not red

- **Beacon Teal** (`#0F766E`) — The single UI accent. Primary buttons, focus rings, active filter chips, selected navigation, chart selection brush, the user's own location marker.
- **Beacon Teal Wash** (`rgba(15, 118, 110, 0.16)`) — Selected-row tint, active chip fill, focus halo.

Teal is deliberate: red, amber and orange are reserved wholesale for risk encoding. If the accent were red, a primary button would read as a hazard. No color in the interface may borrow from the risk ramp.

### Risk ramp — the only saturated color, reserved exclusively for data

This is the one sanctioned exception to the single-accent rule, and it exists because severity is the product. It is a **single-direction sequential ramp** (warm, monotonically darkening), not a rainbow, so it survives greyscale printing and the common forms of color vision deficiency.

- **Risk Tier 1 — Watch** (`#C9A227`) — Muted ochre. Composite danger score 0–24.
- **Risk Tier 2 — Elevated** (`#C2711F`) — Burnt amber. Score 25–49.
- **Risk Tier 3 — Severe** (`#A33A2B`) — Brick. Score 50–74.
- **Risk Tier 4 — Critical** (`#7A1F1A`) — Oxblood. Score 75–100.
- **No Data** (`#3A3E46`) — Neutral graphite for road segments with insufficient records. Absence of data must never be rendered as absence of risk.

**Ramp rules:**
- Every tier must carry a text or shape label alongside its color. Color alone never encodes tier.
- Tier boundaries are fixed and published in the legend. Do not rescale per viewport or per filter.
- The ramp appears on: map markers, heat layers, rank badges, table risk cells, chart series. Nowhere else.

### Status colors — utility only, never on the map

- **Confirm Green** (`#3F7D58`) — Save/export success toasts only.
- **Notice Amber** (`#B4813A`) — Stale-data and low-confidence warnings in panels only.

Status colors are banned from the map canvas and from any chart, where they would be misread as risk.

---

## 3. Typography Rules

- **Display & UI:** **Satoshi** — Headlines, panel titles, labels, buttons. Track-tight at large sizes (`-0.02em` at 2rem and above). Hierarchy is built from weight (500 / 700) and color (Bone White vs Steel Grey), never from inflating size alone.
- **Body:** **Satoshi**, weight 400, line-height `1.65`, maximum measure `65ch`. Secondary body copy sits in Steel Grey.
- **Numerals & Metadata:** **JetBrains Mono** — Mandatory for every number in the product: risk scores, accident counts, coordinates, timestamps, cluster IDs, dates, percentages, axis ticks, table cells. Tabular figures on, so digits align down a column without jitter.

**Scale (fluid, `clamp()`-driven):**

| Role | Size | Weight | Notes |
|---|---|---|---|
| Hero headline | `clamp(2.5rem, 6vw, 4.5rem)` | 700 | Landing only, tracking `-0.03em` |
| Screen title | `clamp(1.5rem, 3vw, 2rem)` | 700 | Tracking `-0.02em` |
| Panel title | `1.125rem` (18px) | 600 | |
| Body | `0.9375rem` (15px) | 400 | Minimum `1rem` on mobile |
| Label / eyebrow | `0.75rem` (12px) | 600 | Uppercase, tracking `0.08em`, Steel Grey |
| Data readout | `0.875rem` (14px) | 500 | JetBrains Mono, tabular |
| Hero metric | `clamp(2rem, 4vw, 3rem)` | 700 | JetBrains Mono |

**Banned:** `Inter` in any role. System-font stacks as a primary choice. All serif faces — this is a dashboard, and serifs read as editorial softness the subject matter does not permit. No letter-spacing on body copy. No all-caps runs longer than three words.

---

## 4. Component Stylings

### Buttons
Flat fills, `0.5rem` (8px) corner radius, `44px` minimum height. Primary is Beacon Teal fill with Bone White label. Secondary is a Structural Line outline over transparent with Bone White label. Tertiary is bare text in Steel Grey. On press, translate down `1px` — a tactile push, nothing else. No outer glow, no gradient fill, no scale-up hover, no custom cursor.

### Cards
Used sparingly and only where elevation communicates hierarchy — the blackspot detail popup, the KPI strip, the export dialog. Panel Graphite fill, `0.75rem` (12px) radius, `1px` Structural Line border, and a diffused shadow tinted to the canvas hue: `0 8px 24px rgba(10, 11, 14, 0.5)`. Never a glow.

Inside dense regions — the rankings table, the filter rail, the stats column — cards are **banned outright**. Use `1px` top borders and vertical rhythm to separate content. A dense list of cards inside cards is the single fastest way to make this product look generic.

### Rankings Table (the ranked list of dangerous stretches)
A borderless table over Panel Graphite. Header row in Label style, sticky on scroll, separated by one Structural Line. Rows are `52px` tall with a `1px` bottom rule; hover fills Raised Slate; the selected row fills Beacon Teal Wash with a `2px` Beacon Teal left edge and simultaneously flies the map to that cluster.

Each row carries: rank (mono), stretch name, a risk badge (ramp color chip plus tier word plus mono score), incident count (mono), and last-incident date (mono, Steel Grey). Sortable columns show a small chevron in Steel Grey; the active sort column's header turns Bone White.

### Map Canvas
- **Basemap:** dark, desaturated tiles (CartoDB Dark Matter or equivalent). Never the default OpenStreetMap color tiles — their road and landuse colors collide directly with the risk ramp.
- **Markers:** the default Leaflet blue teardrop pin is banned. Blackspots render as filled circles, radius scaled by incident count (`6px`–`22px`), filled with the tier's ramp color at 85% opacity, with a `1.5px` Deep Graphite ring for separation against the basemap.
- **Clusters:** cluster bubbles inherit the color of their highest-severity member, never an average. Count sits inside in JetBrains Mono.
- **Heat layer:** the same ramp as a continuous gradient, maximum 55% opacity so street geometry stays readable underneath.
- **Selected blackspot:** a `2px` Bone White ring plus a slow perpetual pulse. One selection at a time.
- **Legend:** permanently docked bottom-left, never collapsible, showing all four tiers with score ranges plus the No Data swatch. A risk map without a visible legend is unreadable.
- **Attribution:** bottom-right, `0.6875rem`, Dim Grey. Required for OpenStreetMap tiles — do not remove it.
- **Controls:** custom zoom and layer controls in Panel Graphite matching the interface. The default Leaflet control chrome is banned.

### Filter Rail
A `280px` fixed-width left rail in Panel Graphite. Grouped filters — time period, severity, road type, weather — each with a Label-style eyebrow. Active filters appear as chips in Beacon Teal Wash with a small clear affordance. A single "Reset filters" text button sits at the base. On mobile the rail becomes a bottom sheet at 60% viewport height with a drag handle.

### Inputs & Search
Label above the field in Label style, field in Raised Slate with a `1px` Structural Line border and `0.5rem` radius, helper or error text below in `0.8125rem`. Focus swaps the border to Beacon Teal with a `3px` Beacon Teal Wash halo. Errors swap the border to Risk Tier 3 with matching message text. No floating labels, no placeholder-as-label.

### Charts (Chart.js / Recharts)
No chart junk — no gridline crosshatch, no 3D, no donut holes with a number crammed inside. Horizontal gridlines only, in Structural Line. Axis ticks in JetBrains Mono, Steel Grey. Severity-split series use the risk ramp; all other series use Beacon Teal with opacity steps. Tooltips are Raised Slate cards with mono values. Every chart states its date range and record count beneath the title in Label style.

### Loading States
Skeleton shimmer blocks in Raised Slate matching the exact dimensions of the content they replace — table rows as row-height bars, the map as a graphite panel with a centered Label-style "Loading incident clusters". Circular spinners are banned.

### Empty States
Composed, not apologetic. A muted line-art road-fork mark, a plain statement of why the view is empty, and the action that fills it — for example: "No recorded incidents match this filter combination. Widen the date range or clear the road-type filter." Never a bare "No data".

### Error States
Inline and specific. A Risk Tier 3 left border on a Panel Graphite strip, the failure in plain language, and a retry action. Never a full-screen error takeover that discards the user's filter state.

### Data-Provenance Strip
Every screen carries a `0.75rem` Dim Grey line stating dataset coverage and model run date, for example: `Dataset 2019–2024 · 18,462 records · clusters computed 2026-03-14`. This product makes claims about public safety; it must always say what it is claiming from.

---

## 5. Layout Principles

- **Shell:** CSS Grid at every level. No flexbox percentage math, no `calc()` width hacks.
- **Explorer screen (the primary view):** three-zone asymmetric grid — `280px` filter rail, fluid map canvas, `380px` docked results panel. The results panel is docked in the grid, never floated over the map. Nothing overlaps the map except the legend and map controls, which occupy reserved corners.
- **Full-height regions:** `min-h-[100dvh]`. `h-screen` is banned — it produces a catastrophic layout jump in iOS Safari.
- **Containment:** content-only screens (about, methodology, report) cap at `1400px` centered. The explorer runs full-bleed.
- **Spacing:** an 8px base scale — `8 / 12 / 16 / 24 / 32 / 48 / 64`. Section gaps use `clamp(3rem, 8vw, 6rem)`.
- **Overlap:** banned. Every element occupies its own spatial zone. No absolutely positioned content stacking on top of other content.
- **The three-equal-cards feature row is banned.** For the landing page's capability section, use a 2-column zig-zag alternating a screenshot with copy, or an asymmetric 2:1:1 grid.
- **Centered hero layouts are banned** at this variance level. The landing hero is a left-aligned type column against a right-side live map fragment.

### Responsive Rules
- **Below 768px:** all multi-column layouts collapse to a single column, without exception. The explorer becomes map-first with the results panel as a draggable bottom sheet and filters as a modal sheet.
- **Horizontal overflow on mobile is a critical failure.** The rankings table scrolls inside its own container with a sticky rank column; the page body never scrolls sideways.
- **Typography** scales via `clamp()`. Body text never drops below `1rem` on mobile.
- **Touch targets** are `44px` minimum, including map markers — increase marker hit radius on touch pointers without changing visual radius.
- **Inline hero images** stack below the headline on mobile rather than sitting between words.
- **Navigation** collapses from a horizontal bar to a sheet menu; the legend moves from bottom-left to a collapsible strip under the map header.

---

## 6. Motion & Interaction

- **Physics:** spring defaults of `stiffness: 100, damping: 20` for all interactive transitions. No linear easing anywhere.
- **Map transitions:** selecting a ranked row flies the map to the cluster over `600ms` with eased zoom. Marker radius changes are spring-driven, never stepped.
- **Staggered reveals:** table rows and chart series mount on a `30ms` cascade. Lists never appear all at once.
- **Perpetual micro-motion, used with restraint:** the selected blackspot marker carries a slow `2.4s` opacity pulse on its ring, and the live-data indicator in the header carries a gentle breathing dot. Nothing else loops. In a safety product, ambient animation on unselected hazards would read as alarm.
- **Filter changes:** results cross-fade over `180ms` rather than blanking to a loader, when data is already cached.
- **Performance:** animate `transform` and `opacity` exclusively. Never animate `top`, `left`, `width`, or `height`. Any grain or texture overlay lives on a fixed pseudo-element outside the scroll container.
- **Reduced motion:** honor `prefers-reduced-motion` — replace flies with instant jumps, drop the cascade to `0ms`, and stop all perpetual loops.

---

## 7. Hero Section (Landing / Project Overview)

The landing page is the first thing evaluators and authorities see. It is left-aligned and asymmetric — a type column occupying roughly 55% of the width, with a live, non-interactive map fragment bleeding off the right edge showing real clustered blackspots.

**Signature technique — inline map typography.** The headline embeds small rounded fragments of the actual dark basemap, cropped to real blackspot locations, set inline at type-height between words as visual punctuation. For example, a headline reading "Where the road [map fragment] keeps taking people" with the fragment sitting inline at cap height with `0.375rem` radius. These are real crops from the dataset's own clusters, not stock imagery. Text must never overlap them — each fragment holds its own inline slot.

Beneath the headline: one line of plain sub-copy stating what the system does and the dataset it draws on, then a single primary CTA reading "Open the map". No secondary "Learn more" link. Below the fold, a horizontal strip of three mono metrics — records analyzed, clusters identified, coverage window — in JetBrains Mono with Label-style captions.

**Banned in the hero:** scroll arrows, bouncing chevrons, "Scroll to explore", "Swipe down", any centered layout, any second CTA, gradient text on the headline.

---

## 8. Screen Inventory

Prompt Stitch for these screens using the rules above:

1. **Landing / Overview** — asymmetric hero with inline map typography, zig-zag capability section, methodology summary, data provenance.
2. **Blackspot Explorer** — the primary screen. Filter rail, dark map canvas with graded markers and clusters, docked ranked results panel, permanent legend.
3. **Blackspot Detail** — the panel or modal that opens on selection: composite score with tier badge, contributing factor breakdown, incident-time histogram, severity split, nearest landmarks, last-incident date.
4. **Rankings Table** — full-width sortable table of the most dangerous stretches with sticky header, risk badges, and mono metrics.
5. **Statistics Dashboard** — accidents by month, by hour of day, by severity, by road type. Four chart panels on an asymmetric 2:1 grid, not four equal cards.
6. **Route Risk Check** (stretch) — origin/destination inputs, drawn route, blackspots flagged along it with a cumulative route risk readout.
7. **Authority Dashboard** (stretch) — aggregated statistics with an export action and a documented date range.

---

## 9. Content & Copy Rules

The subject is injury and death on public roads. Copy is factual, specific, and never dramatized.

- State findings, do not editorialize. "Score 78.4 — Critical. 23 incidents since 2019, 6 fatal." Not "This road is a death trap."
- Never imply prediction certainty. The model surfaces historical clustering; copy says "historically high-risk", never "will be dangerous".
- Attribute every figure to its dataset and date range.
- Placeholder and demo data must be plausible and irregular — `1,847` records, `74.2` score, `NH-16 near Chandaka junction` — never `1,000`, never `99.9%`, never "Main Street".

---

## 10. Anti-Patterns (Banned)

**Typography & color**
- No emojis, anywhere, in any state — including empty and error states.
- No `Inter`. No system-font fallback stacks as a primary choice.
- No serif fonts of any kind.
- No pure black (`#000000`) and no pure white (`#FFFFFF`) as surfaces.
- No gradient text on headlines.
- No second UI accent. No accent above 80% saturation.
- No purple, violet, or neon-blue "AI" palette. No neon or outer-glow shadows.
- No status green or amber on the map or in charts.

**Layout & components**
- No overlapping elements. No absolutely positioned content stacked over other content.
- No centered hero.
- No three-equal-cards feature row.
- No cards nested inside cards inside cards.
- No `h-screen`. No `calc()` percentage width hacks.
- No horizontal page scroll on mobile.
- No circular loading spinners.
- No custom mouse cursors.
- No default Leaflet blue pins, default Leaflet control chrome, or full-color OSM basemap tiles.
- No risk color used without an accompanying text label.
- No map without a visible legend.

**Content**
- No AI copywriting clichés: "Elevate", "Seamless", "Unleash", "Next-Gen", "Revolutionize", "Empower", "Game-changing".
- No filler UI text: "Scroll to explore", "Swipe down", scroll arrows, bouncing chevrons.
- No generic placeholder names: "John Doe", "Acme", "Nexus", "Main Street", "Lorem ipsum".
- No fake round numbers: `99.99%`, `50%`, `10,000 users`.
- No hotlinked Unsplash URLs — use `picsum.photos` or inline SVG for any placeholder imagery.
- No claim of live or real-time data unless the pipeline actually delivers it. The system serves precomputed clusters; the interface must say so.
