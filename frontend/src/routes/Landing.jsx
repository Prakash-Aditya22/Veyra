import { useLayoutEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { ArrowRight } from '@phosphor-icons/react';
import MapFragment from '../components/MapFragment.jsx';
import MapCanvas from '../components/MapCanvas.jsx';
import GradientWaves from '../components/GradientWaves.jsx';
import RiskBadge from '../components/RiskBadge.jsx';
import ProvenanceStrip from '../components/ProvenanceStrip.jsx';
import CountUp from '../components/motion/CountUp.jsx';
import { gsap, ScrollTrigger } from '../lib/gsapScroll.js';
import GB from '../data/gbStats.json';
import { toView } from '../lib/geo.js';
import { num } from '../lib/format.js';
import './Landing.css';

/*
  Everything on this page comes from gbStats.json, built by
  ml/build_stats_summary.py from the scored segments and the pipeline's own
  validation and model reports. The page is static on purpose: it should
  render even when the backend is down.
*/
const SEGMENTS = GB.topSegments.map(toView);
const T = GB.totals;
const [MODEL, CRASH_COUNT] = GB.validation.rows;
const CRASH_SPAN = `${GB.crashYears[0]} to ${GB.crashYears[1]}`;
const FORECAST_SPAN = `${GB.forecastYears[0]} to ${GB.forecastYears[1]}`;

// The two crops in the headline are centred on Great Britain's two
// highest-scoring segments, so the imagery is the dataset's own.
const [TOP, SECOND] = SEGMENTS;

const PREVIEW_ROWS = SEGMENTS.slice(0, 5);

/* The extent of the STATS19 record, framed so London's cluster reads too. */
const GB_CENTER = [53.6, -2.4];
const GB_ZOOM = 5;

export default function Landing() {
  const reduce = useReducedMotion();
  const rootRef = useRef(null);

  const rise = (delay = 0) => ({
    initial: reduce ? false : { opacity: 0, y: 14 },
    animate: { opacity: 1, y: 0 },
    transition: { type: 'spring', stiffness: 100, damping: 20, delay },
  });

  /*
    Scroll-linked choreography for the overview page, built on GSAP +
    ScrollTrigger. This deliberately goes further than DESIGN.md's default
    "motion level 4" (opacity + 14px settle, no scroll choreography) — an
    explicit, one-off exception for this page, chosen after flagging the
    conflict.

    The hero and both capability rows pin briefly so their content can
    transform while the scrollbar holds; the metric strip, methodology and
    footer scrub into place as they pass through instead of freezing the
    page for every section. `gsap.context` scopes every selector to this
    page and its `revert()` cleanly tears down all triggers and inline
    styles on unmount, which matters here because ScrollTrigger instances
    are otherwise global and would leak across route changes.
  */
  useLayoutEffect(() => {
    if (reduce) return undefined;

    // The nav bar is sticky with its own z-index, and a pinned section is
    // otherwise fixed flush to the viewport top — without this offset its
    // top edge (headline, first ranked row) renders behind the nav instead
    // of below it.
    const navHeight = parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue('--nav-height'),
    ) || 64;
    const pinStart = `top ${navHeight}px`;

    const ctx = gsap.context(() => {
      // ---- Hero: pins, then recedes as the wave field pushes in. ----
      gsap
        .timeline({
          scrollTrigger: {
            trigger: '.hero',
            start: pinStart,
            end: '+=100%',
            scrub: 0.6,
            pin: true,
          },
        })
        .to('.hero__type', { opacity: 0, y: -50, scale: 0.94, ease: 'none' }, 0)
        .to('.hero__bg', { scale: 1.15, ease: 'none' }, 0);

      // ---- Metrics: scrub into place as the strip enters, no pin. ----
      gsap.set('.metric', { opacity: 0, y: 28 });
      gsap.to('.metric', {
        opacity: 1,
        y: 0,
        stagger: 0.12,
        ease: 'none',
        scrollTrigger: {
          trigger: '.metrics',
          start: 'top 85%',
          end: 'top 35%',
          scrub: 0.6,
        },
      });

      // ---- Capability one: pins, map and copy slide in from opposite
      //      edges. ----
      const capOne = '.capability:not(.capability--flip)';
      gsap.set(`${capOne} .capability__visual`, { opacity: 0, x: -60, scale: 0.96 });
      gsap.set(`${capOne} .capability__copy`, { opacity: 0, x: 60 });
      gsap
        .timeline({
          scrollTrigger: {
            trigger: capOne,
            start: pinStart,
            end: '+=90%',
            scrub: 0.6,
            pin: true,
          },
        })
        .to(`${capOne} .capability__visual`, { opacity: 1, x: 0, scale: 1, ease: 'none' }, 0)
        .to(`${capOne} .capability__copy`, { opacity: 1, x: 0, ease: 'none' }, 0.1);

      // ---- Capability two (flip): mirrored slide-in, ranked rows cascade
      //      across the same pinned scrub. ----
      const capTwo = '.capability--flip';
      gsap.set(`${capTwo} .capability__copy`, { opacity: 0, x: -60 });
      gsap.set(`${capTwo} .preview-row`, { opacity: 0, x: 60 });
      gsap
        .timeline({
          scrollTrigger: {
            trigger: capTwo,
            start: pinStart,
            end: '+=100%',
            scrub: 0.6,
            pin: true,
          },
        })
        .to(`${capTwo} .capability__copy`, { opacity: 1, x: 0, ease: 'none' }, 0)
        .to(`${capTwo} .preview-row`, { opacity: 1, x: 0, stagger: 0.15, ease: 'none' }, 0.1);

      // ---- Methodology: scrub into place, spec rows cascade, no pin. ----
      gsap.set('.method__intro', { opacity: 0, y: 30 });
      gsap.set('.method__row', { opacity: 0, y: 16 });
      gsap
        .timeline({
          scrollTrigger: {
            trigger: '.method',
            start: 'top 80%',
            end: 'top 20%',
            scrub: 0.6,
          },
        })
        .to('.method__intro', { opacity: 1, y: 0, ease: 'none' }, 0)
        .to('.method__row', { opacity: 1, y: 0, stagger: 0.06, ease: 'none' }, 0.1);

      // ---- Footer: simple scrub fade-up. ----
      gsap.set('.landing__foot-inner', { opacity: 0, y: 20 });
      gsap.to('.landing__foot-inner', {
        opacity: 1,
        y: 0,
        ease: 'none',
        scrollTrigger: {
          trigger: '.landing__foot',
          start: 'top 92%',
          end: 'top 60%',
          scrub: 0.6,
        },
      });
    }, rootRef);

    // Section heights depend on fonts/images that can settle after mount;
    // one refresh once everything has painted keeps trigger positions honest.
    const id = requestAnimationFrame(() => ScrollTrigger.refresh());

    return () => {
      cancelAnimationFrame(id);
      ctx.revert();
    };
  }, [reduce]);

  return (
    <div className="landing" ref={rootRef}>
      {/* ---------------- Hero: type column over a full-bleed wave field ---------------- */}
      <section className="hero">
        {!reduce && (
          <div className="hero__bg" aria-hidden="true">
            <GradientWaves
              horizonColor="#131417"
              waveColor="#0f766e"
              crestColor="#eef1f5"
              speed={0.4}
              amplitude={2.4}
              waveScale={0.55}
              waveRatio={0.9}
              swell={32}
              turbulence={18}
              tilt={1.15}
              zoom={1.8}
              height={4.5}
              fogDepth={17}
              detail="low"
              brightness={1.3}
              opacity={0.92}
              mouseInteraction
              parallaxStrength={0.35}
              grain
              grainIntensity={0.04}
            />
          </div>
        )}
        <span className="hero__scrim" aria-hidden="true" />

        <div className="hero__type">
          {/*
            The claim is the validation result, not a slogan: the top 20% of
            held-out segments by score carried 50.4% of the next two years'
            killed-or-seriously-injured casualties.
          */}
          <motion.h1 className="hero__headline" {...rise(0)}>
            A fifth of the road
            <MapFragment lat={TOP.lat} lng={TOP.lng} label={TOP.name} />
            carries half the
            <MapFragment lat={SECOND.lat} lng={SECOND.lng} label={SECOND.name} />
            harm.
          </motion.h1>

          <motion.p className="hero__sub" {...rise(0.06)}>
            STATS19 crash records for Great Britain&rsquo;s numbered roads, cut into 500 m
            segments and scored so the stretches most likely to see serious harm surface
            first.
          </motion.p>
        </div>
      </section>

      {/* ---------------- Metric strip ---------------- */}
      <section className="metrics">
        <div className="container metrics__inner">
          <div className="metric">
            <p className="metric__value mono">
              <CountUp value={T.crashes} />
            </p>
            <p className="label">Crashes analysed, {CRASH_SPAN}</p>
          </div>
          <div className="metric">
            <p className="metric__value mono">
              <CountUp value={T.segments} />
            </p>
            <p className="label">500 m segments scored</p>
          </div>
          <div className="metric">
            {/* A span of years is not a quantity, so it does not count up. */}
            <p className="metric__value mono">
              {GB.crashYears[0]} to {GB.forecastYears[1]}
            </p>
            <p className="label">Coverage window</p>
          </div>
        </div>
      </section>

      {/* ---------------- Capability one: map, copy on the right ---------------- */}
      <section className="capability container">
        <div className="capability__visual">
          {/* The top 300 evidenced segments; the explorer draws all of them. */}
          <MapCanvas
            blackspots={SEGMENTS}
            selectedId={null}
            center={GB_CENTER}
            zoom={GB_ZOOM}
            homeLabel="Great Britain"
            interactive={false}
            showLegend={false}
          />
        </div>
        <div className="capability__copy">
          <h2 className="capability__title">Read the whole country in one view</h2>
          <p className="body-secondary">
            Every scored segment is drawn at its midpoint, sized by how many crashes it
            recorded and filled with its risk tier. Filter by tier, by how much evidence
            sits behind a score, or by road, and the map and the ranked panel move
            together.
          </p>
          <Link to="/explorer" className="capability__link">
            Open the map
            <ArrowRight size={14} weight="bold" />
          </Link>
        </div>
      </section>

      {/* ---------------- Capability two: copy left, real ranked rows right ---------------- */}
      <section className="capability capability--flip container">
        <div className="capability__copy">
          <h2 className="capability__title">Rank stretches by evidence, not impression</h2>
          <p className="body-secondary">
            Each score is a forecast: the killed-or-seriously-injured casualties a 500 m
            stretch is expected to see over two years, learned from {CRASH_SPAN} crashes
            and checked against {FORECAST_SPAN}. Tier boundaries are fixed and published,
            so a score of 74 means the same thing on every screen and in every filter
            state.
          </p>
          <Link to="/rankings" className="capability__link">
            See the full ranking
            <ArrowRight size={14} weight="bold" />
          </Link>
        </div>

        {/*
          Not a mock-up: the top five segments nationally, with the same badge
          component the rankings screen renders. Each row opens that segment
          in the explorer by its real segment id.
        */}
        <div className="capability__rows">
          {PREVIEW_ROWS.map((b, i) => (
            <Link
              key={b.id}
              to={`/explorer?segment=${encodeURIComponent(b.id)}`}
              className="preview-row"
            >
              <span className="preview-row__rank mono">
                {String(i + 1).padStart(2, '0')}
              </span>
              <span className="preview-row__body">
                <span className="preview-row__name">{b.name}</span>
                <span className="preview-row__meta mono">
                  {num(b.incidents)} crashes, {num(b.ksi)} fatal or serious,{' '}
                  {b.blackspotScore.toFixed(2)} expected KSI
                </span>
              </span>
              <RiskBadge score={b.score} size="sm" />
            </Link>
          ))}
        </div>
      </section>

      {/* ---------------- Methodology: asymmetric, spec values in mono ---------------- */}
      <section className="method container">
        <div className="method__intro">
          <p className="label">How the scores are produced</p>
          <h2 className="method__title">Segment the road first, forecast harm second</h2>
          <p className="body-secondary">
            Crashes on each numbered road are split into geographic stretches, ordered
            along the road by a minimum spanning tree over the crash points, and binned
            into 500 m segments. A Poisson model then learns, from each segment&rsquo;s{' '}
            {CRASH_SPAN} record, how many killed-or-seriously-injured casualties it will
            see in {FORECAST_SPAN}, and is scored on segments it never trained on.
          </p>
          <p className="method__caveat">
            The model beats simply ranking by past crash count by about one point: crash
            history does most of the work, and the model refines it. Scores resting on
            fewer than {GB.minCrashes} crashes are noisy and are hidden by default.
          </p>
        </div>

        <dl className="method__spec">
          <div className="method__row">
            <dt>Segment length</dt>
            <dd className="mono">500 m</dd>
          </div>
          <div className="method__row">
            <dt>Roads covered</dt>
            <dd className="mono">{num(T.roads)}, each with 60+ crashes</dd>
          </div>
          <div className="method__row">
            <dt>Blackspot model</dt>
            <dd>Poisson regression, expected KSI over two years</dd>
          </div>
          <div className="method__row">
            <dt>Top 20% of segments capture</dt>
            <dd className="mono">{MODEL.values[3]}% of future KSI</dd>
          </div>
          <div className="method__row">
            <dt>Ranking by crash count captures</dt>
            <dd className="mono">{CRASH_COUNT.values[3]}%</dd>
          </div>
          <div className="method__row">
            <dt>Severity model, deployable</dt>
            <dd className="mono">
              ROC-AUC {GB.severityModels.deployable.rocAuc.toFixed(2)},{' '}
              {GB.severityModels.deployable.features} features
            </dd>
          </div>
          <div className="method__row">
            <dt>Evidence floor shown</dt>
            <dd className="mono">{GB.minCrashes}+ crashes</dd>
          </div>
        </dl>
      </section>

      <footer className="landing__foot">
        <div className="container landing__foot-inner">
          <ProvenanceStrip
            items={[
              'STATS19, Great Britain',
              `crashes ${CRASH_SPAN}`,
              `KSI forecast ${FORECAST_SPAN}`,
              `${num(T.segments)} scored 500 m segments`,
            ]}
          />
          <p className="landing__foot-note">
            Scores are precomputed from the Department for Transport&rsquo;s STATS19 record
            and served from a database. The interface does not read live traffic or
            incident feeds.
          </p>
        </div>
      </footer>
    </div>
  );
}
