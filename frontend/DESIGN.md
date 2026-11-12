# Design System: Accident Blackspot Detection & Visualization System

**Product:** A map-first web application that surfaces ML-derived accident blackspots, ranks road stretches by a composite danger score, and gives commuters and municipal authorities a way to read road risk at a glance.

**Audience:** Two modes of use in one interface — a commuter scanning a route in ten seconds, and a traffic authority reading a ranked table for twenty minutes. The design must serve the second without punishing the first.

**Use this document as the single source of truth when prompting Stitch for any screen in this product.**

---

## 1. Visual Theme & Atmosphere

A dark, instrument-grade interface with the composure of a transit operations console — quiet chrome, loud data. The atmosphere is factual and unsentimental: this product reports where people have been hurt, so nothing about it should feel celebratory, gamified, or playful. Think night-shift control room, not consumer travel app.

The chrome recedes to a black ground with paper-white type, and the whole product draws its colour from just four plate colours. Blue is the interface; yellow, red and violet are risk. When a stretch of road glows yellow-to-violet on the map, that colour carries meaning — it is never decoration. A screen where the interface is more colourful than the data has failed.

Layouts are asymmetric and rail-driven: a persistent filter rail, a dominant map canvas, and a docked results panel that never floats free over the map. Motion is restrained and functional — data settles into place, it does not perform.

**Calibration:**
- **Density: 7** (Data-forward, approaching cockpit — tight vertical rhythm, tabular numerals, minimal decorative padding)
- **Variance: 6** (Offset asymmetric — rail + canvas splits, no centered hero, no symmetric card rows)
- **Motion: 4** (Fluid but restrained — spring settling, staggered table reveals, no cinematic scroll choreography)

---

## 2. Color Palette & Roles

### The plate — four colours, and nothing else

Every colour in the product comes from four colours on a Japanese traditional colour plate. Every other value is black, white, or white at an opacity. `src/styles/tokens.css` transcribes this section; if a colour is not there, it does not exist in the product.

| Token | Name | Hex | Role |
|---|---|---|---|
| `--c-blue` | 青色 Blue | `#1F4FBF` | The interface accent |
| `--c-yellow` | 山吹色 Orange Yellow | `#F2A31B` | Risk: Watch and Elevated; notices |
| `--c-red` | 赤色 Spectrum Red | `#D7120F` | Risk: Severe; errors |
| `--c-violet` | 半色 Aconite Violet | `#8E44AD` | Risk: Critical |

### Neutrals — black ground, paper-white type

- **Canvas** (`--canvas`, `#0E0F11`) — Application ground, the base surface behind everything. Near-black, never `#000000`.
- **Panel** (`--panel`, `#16171A`) — Filter rail, docked results panel, table headers, modal surfaces.
- **Raised** (`--raised`, `#212327`) — Hover surfaces, selected table rows, input fills, tooltip bodies.
- **Line** (`--line`, `rgba(238, 240, 244, 0.12)`) — All 1px dividers, table rules, panel edges. Structure comes from hairlines, not shadows.
- **Track** (`--track`, `rgba(238, 240, 244, 0.08)`) — Empty bar tracks and the chart hover band.
- **Ink** (`--ink`, `#EEF0F4`) — Paper white. Primary text, headline type, active values.
- **Ink Soft** (`--ink-soft`, Ink at 72%) — Secondary text, labels, axis ticks, metadata, timestamps.
- **Ink Faint** (`--ink-faint`, Ink at 52%) — Tertiary text, disabled states, placeholder copy, map attribution.
- **Scrim** (`--scrim`, `rgba(0, 0, 0, 0.6)`) — Behind mobile sheets and modals.

### Interface accent — Blue, and only Blue

- **Accent** (`--accent`, Blue `#1F4FBF`) — The single UI accent. Primary buttons, active filter chips, selected navigation, chart series that are not split by severity, the selected route.
- **Accent Lift** (`--accent-lift`, Blue mixed 70/30 toward Ink) — Hover fills, focus rings and focus borders, and any blue *text*. Raw Blue is too dark to read as text on black; the lift is the same hue made legible.
- **Accent Wash** (`--accent-wash`, `rgba(31, 79, 191, 0.22)`) — Selected-row tint, active chip fill, focus halo.
- **On Accent** (`--on-accent`, `#FFFFFF`) — Text on a Blue fill. Text only, never a surface.

Blue is deliberate: yellow, red and violet are reserved wholesale for risk. If the accent were red, a primary button would read as a hazard. No interface element may borrow a risk colour, and Blue never appears in the risk ramp.

### Risk ramp — reserved exclusively for data

This is the one sanctioned exception to the single-accent rule, and it exists because severity is the product. The ramp runs **yellow → red → violet**: three plate colours for four tiers.

- **Risk Tier 1 — Watch** (`--risk-1`, Orange Yellow `#F2A31B`) — Composite danger score 0–24.
- **Risk Tier 2 — Elevated** (`--risk-2`, Orange Yellow `#F2A31B`) — Score 25–49.
- **Risk Tier 3 — Severe** (`--risk-3`, Spectrum Red `#D7120F`) — Score 50–74.
- **Risk Tier 4 — Critical** (`--risk-4`, Aconite Violet `#8E44AD`) — Score 75–100.
- **No Data / Thinly evidenced** (`--risk-none`, Ink at 22%) — Segments with too few records (fewer than 6 crashes). Drawn in ink, not a colour, because absence of data must never be rendered as absence of risk.

**Ramp rules:**
- **Watch and Elevated share a colour.** They are told apart by their tier word, which every tier display (badge, legend, table cell, tooltip) already shows. This is why the label rule below is mandatory, not a nicety.
- Every tier must carry a text or shape label alongside its colour. Colour alone never encodes tier.
- The ramp is not a single-hue lightness ramp, so it does not survive greyscale printing on its own. The tier word is what carries the meaning there too.
- Tier boundaries are fixed and published in the legend. Do not rescale per viewport or per filter. The cutoffs live only in `src/lib/riskScale.js`.
- The ramp appears on: map markers, heat layers, rank badges, table risk cells, severity-split chart series. Nowhere else.

### Status colours — utility only, never on the map

- **Confirm** (`--status-confirm`, Blue) — Save/export success.
- **Notice** (`--status-notice`, Orange Yellow) — Stale-data and low-confidence warnings, as a left border inside panels only.

Both reuse plate colours. Status colours are banned from the map canvas and from any chart, where Notice in particular would be misread as Watch or Elevated.

---

## 3. Typography Rules

- **Display & UI:** **Satoshi** — Headlines, panel titles, labels, buttons. Track-tight at large sizes (`-0.02em` at 2rem and above). Hierarchy is built from weight (500 / 700) and colour (Ink vs Ink Soft), never from inflating size alone.
- **Body:** **Satoshi**, weight 400, line-height `1.65`, maximum measure `65ch`. Secondary body copy sits in Ink Soft.
- **Numerals & Metadata:** **JetBrains Mono** — Mandatory for every number in the product: risk scores, accident counts, coordinates, timestamps, cluster IDs, dates, percentages, axis ticks, table cells. Tabular figures on, so digits align down a column without jitter.

**Scale (fluid, `clamp()`-driven):**

| Role | Size | Weight | Notes |
|---|---|---|---|
| Hero headline | `clamp(2.5rem, 6vw, 4.5rem)` | 700 | Landing only, tracking `-0.03em` |
| Screen title | `clamp(1.5rem, 3vw, 2rem)` | 700 | Tracking `-0.02em` |
| Panel title | `1.125rem` (18px) | 600 | |
| Body | `0.9375rem` (15px) | 400 | Minimum `1rem` on mobile |
| Label / eyebrow | `0.75rem` (12px) | 600 | Uppercase, tracking `0.08em`, Ink Soft |
| Data readout | `0.875rem` (14px) | 500 | JetBrains Mono, tabular |
| Hero metric | `clamp(2rem, 4vw, 3rem)` | 700 | JetBrains Mono |

**Banned:** `Inter` in any role. System-font stacks as a primary choice. All serif faces — this is a dashboard, and serifs read as editorial softness the subject matter does not permit. No letter-spacing on body copy. No all-caps runs longer than three words.

---

## 4. Component Stylings

### Buttons
Flat fills, `0.5rem` (8px) corner radius, `44px` minimum height. Primary is a Blue (Accent) fill with an On Accent white label; hover lifts the fill to Accent Lift. Secondary is a Line outline over transparent with Ink label. Tertiary is bare text in Ink Soft. On press, translate down `1px` — a tactile push, nothing else. No outer glow, no gradient fill, no scale-up hover, no custom cursor.

### Cards
Used sparingly and only where elevation communicates hierarchy — the blackspot detail popup, the KPI strip, the export dialog. Panel fill, `0.75rem` (12px) radius, `1px` Line border, and a diffused black shadow: `0 8px 24px rgba(0, 0, 0, 0.5)`. Never a glow.

Inside dense regions — the rankings table, the filter rail, the stats column — cards are **banned outright**. Use `1px` top borders and vertical rhythm to separate content. A dense list of cards inside cards is the single fastest way to make this product look generic.

### Rankings Table (the ranked list of dangerous stretches)
A borderless table over Panel. Header row in Label style, sticky on scroll, separated by one Line. Rows are `52px` tall with a `1px` bottom rule; hover fills Raised; the selected row fills Accent Wash with a `2px` Blue left edge and simultaneously flies the map to that cluster.

Each row carries: rank (mono), stretch name, a risk badge (ramp color chip plus tier word plus mono score), incident count (mono), and last-incident date (mono, Ink Soft). Sortable columns show a small chevron in Ink Soft; the active sort column's header turns Ink.

### Map Canvas
- **Basemap:** Esri World Dark Gray Canvas — dark, desaturated tiles that carry the black ground through to the map, served without an API key. Never the default OpenStreetMap color tiles — their road and landuse colors collide directly with the risk ramp.
- **Markers:** the default Leaflet blue teardrop pin is banned. Blackspots render as filled circles, radius scaled by incident count (`6px`–`22px`), filled with the tier's ramp color at 85% opacity, with a `1.5px` Canvas-black ring for separation against the basemap.
- **Clusters:** cluster bubbles inherit the color of their highest-severity member, never an average. Count sits inside in JetBrains Mono.
- **Heat layer:** the same ramp as a continuous gradient, maximum 55% opacity so street geometry stays readable underneath.
- **Selected blackspot:** a `2px` paper-white (Ink) ring plus a slow perpetual pulse. One selection at a time.
- **Legend:** permanently docked bottom-left, never collapsible, showing all four tiers with score ranges plus the No Data swatch. A risk map without a visible legend is unreadable.
- **Attribution:** bottom-right, `0.6875rem`, Ink Faint. Required for OpenStreetMap tiles — do not remove it.
- **Controls:** custom zoom and layer controls in Panel matching the interface. The default Leaflet control chrome is banned.

### Filter Rail
A `280px` fixed-width left rail in Panel. Grouped filters — time period, severity, road type, weather — each with a Label-style eyebrow. Active filters appear as chips in Accent Wash with a small clear affordance. A single "Reset filters" text button sits at the base. On mobile the rail becomes a bottom sheet at 60% viewport height with a drag handle.

### Inputs & Search
Label above the field in Label style, field in Raised with a `1px` Line border and `0.5rem` radius, helper or error text below in `0.8125rem`. Focus swaps the border to Accent Lift with a `3px` Accent Wash halo. Errors swap the border to Risk Tier 3 with matching message text. No floating labels, no placeholder-as-label.

### Charts (Chart.js / Recharts)
No chart junk — no gridline crosshatch, no 3D, no donut holes with a number crammed inside. Horizontal gridlines only, in Line. Axis ticks in JetBrains Mono, Ink Soft. Severity-split series use the risk ramp; all other series use Blue, with paper-white at reduced opacity for comparison series. Tooltips are Raised cards with mono values. Every chart states its date range and record count beneath the title in Label style.

### Loading States
Skeleton shimmer blocks in Raised matching the exact dimensions of the content they replace — table rows as row-height bars, the map as a Panel-coloured block with a centered Label-style "Loading incident clusters". Circular spinners are banned.

### Empty States
Composed, not apologetic. A muted line-art road-fork mark, a plain statement of why the view is empty, and the action that fills it — for example: "No recorded incidents match this filter combination. Widen the date range or clear the road-type filter." Never a bare "No data".

### Error States
Inline and specific. A Risk Tier 3 left border on a Panel strip, the failure in plain language, and a retry action. Never a full-screen error takeover that discards the user's filter state.

### Data-Provenance Strip
Every screen carries a `0.75rem` Ink Faint line stating dataset coverage and model run date, for example: `Dataset 2019–2024 · 18,462 records · clusters computed 2026-03-14`. This product makes claims about public safety; it must always say what it is claiming from.

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
- No pure black (`#000000`) and no pure white (`#FFFFFF`) as surfaces. (`#FFFFFF` exists only as On Accent text.)
- No gradient text on headlines.
- No second UI accent. Blue is the only one.
- No colour outside the four-colour plate. Violet exists only as the Critical risk tier, never in the interface. No neon or outer-glow shadows.
- No status colour (Confirm, Notice) on the map or in charts.

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
