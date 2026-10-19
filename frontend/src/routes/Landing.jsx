import { useLayoutEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { ArrowRight } from '@phosphor-icons/react';
import MapFragment from '../components/MapFragment.jsx';
import MapCanvas from '../components/MapCanvas.jsx';
import GradientWaves from '../components/GradientWaves.jsx';
import PriorityBadge from '../components/PriorityBadge.jsx';
import ProvenanceStrip from '../components/ProvenanceStrip.jsx';
import CountUp from '../components/motion/CountUp.jsx';
import { gsap, ScrollTrigger } from '../lib/gsapScroll.js';
import { useData } from '../data/DataContext.jsx';
import { fixed, int, ksi, period, pct } from '../lib/format.js';
import { BASEMAP } from '../config/basemap.js';
import { PRODUCT, PRODUCT_SUBTITLE, usePageTitle } from '../lib/usePageTitle.js';
import './Landing.css';

/*
  Overview. Every figure on this page comes from the loaded ML release (manifest, segments,
  context.json); nothing is typed in by hand. The two headline crops are centred on the two
  highest-ranked segments, so the imagery is the data's own.
*/

export default function Landing() {
  const reduce = useReducedMotion();
  const rootRef = useRef(null);
  const data = useData();
  const ready = data.status === 'ready';
  const r = ready ? data.release : null;
  const [top, second] = ready ? data.segments : [];
  const preview = ready ? data.segments.slice(0, 5) : [];
  const holdout = ready ? data.context?.holdout ?? null : null;
  usePageTitle(null);
  const topSum = ready ? data.segments.filter((s) => s.stratum !== 'reference_case').reduce((a, s) => a + s.score, 0) : 0;

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
    // The choreography targets rows rendered from the data, so it starts once the data are ready.
    if (reduce || !ready) return undefined;

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
  }, [reduce, ready]);

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
          <motion.h1 className="hero__headline" {...rise(0)}>
            Ranking Great Britain&rsquo;s roads
            {top && <MapFragment lat={top.lat} lng={top.lon} label={top.location} />}
            by expected serious and fatal
            {second && <MapFragment lat={second.lat} lng={second.lon} label={second.location} />}
            casualties.
          </motion.h1>

          <motion.p className="hero__sub" {...rise(0.06)}>
            {ready
              ? `A forecast for ${period(r.forecastPeriod)} from police-reported collisions in ${period(
                  r.historyPeriod,
                )} (DfT STATS19), on OS Open Roads segments across England, Scotland and Wales. It ranks the expected casualty burden on each segment; it does not predict individual crashes.`
              : 'Loading the Great Britain forecast.'}
          </motion.p>
          {top && (
            <p className="hero__credit">
              Map crops: segments ranked 1 and 2 nationally.{' '}
              {BASEMAP.disabled ? 'No basemap configured.' : `Basemap ${BASEMAP.attributionText || 'attribution not configured'}.`}
            </p>
          )}
        </div>
      </section>

      {/* ---------------- Metric strip ---------------- */}
      <section className="metrics">
        <div className="container metrics__inner">
          <div className="metric">
            <p className="metric__value mono">{ready ? <CountUp value={r.nationalSegments} /> : '—'}</p>
            <p className="label">Road segments scored in Great Britain</p>
          </div>
          <div className="metric">
            <p className="metric__value mono">{ready ? `${fixed(r.nationalKsiCoveragePct, 1)}%` : '—'}</p>
            <p className="label">Of serious and fatal casualties lie on scored roads</p>
          </div>
          <div className="metric">
            {/* A span of years is not a quantity, so it does not count up. */}
            <p className="metric__value mono">{ready ? period(r.forecastPeriod) : '—'}</p>
            <p className="label">Forecast period (two years combined)</p>
          </div>
        </div>
      </section>

      {/* ---------------- Capability one: map, copy on the right ---------------- */}
      <section className="capability container">
        <div className="capability__visual">
          {ready && <MapCanvas segments={data.segments} selectedId={null} interactive={false} showLegend={false} />}
        </div>
        <div className="capability__copy">
          <h2 className="capability__title">Read the highest-priority roads in one view</h2>
          <p className="body-secondary">
            {ready
              ? `This demonstration loads the ${int(r.subset.nTop)} highest-ranked of ${int(
                  r.nationalSegments,
                )} scored segments, drawn on their OS Open Roads centrelines, plus ${int(
                  r.subset.nReference,
                )} lower-ranked reference cases. Together the top ${int(r.subset.nTop)} carry ${ksi(
                  topSum,
                  0,
                )} expected serious or fatal casualties in ${period(r.forecastPeriod)}, ${pct(
                  topSum,
                  r.nationalExpectedKsi,
                )} of the national forecast total of ${int(r.nationalExpectedKsi)}.`
              : 'Loading.'}
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
          <h2 className="capability__title">Ranked by expected burden, shown with its uncertainty</h2>
          <p className="body-secondary">
            Each segment carries its national rank and the range that rank takes when the model is refitted on
            resampled data. Membership of the top 1,000 is stable; exact positions are not, so neighbouring ranks are
            not treated as different. Model explanations, single-event warnings and per-vehicle rates are shown where
            the data support them, and marked not available where they do not.
          </p>
          <Link to="/rankings" className="capability__link">
            See the ranking
            <ArrowRight size={14} weight="bold" />
          </Link>
        </div>

        <div className="capability__rows">
          {preview.map((s) => (
            <Link key={s.id} to={`/explorer?segment=${encodeURIComponent(s.id)}`} className="preview-row">
              <span className="preview-row__rank mono">{int(s.rank)}</span>
              <span className="preview-row__body">
                <span className="preview-row__name">{s.location}</span>
                <span className="preview-row__meta mono">
                  {ksi(s.score)} expected KSI, {period(s.forecastPeriod)}
                </span>
              </span>
              <PriorityBadge segment={s} size="sm" showRank={false} />
            </Link>
          ))}
        </div>
      </section>

      {/* ---------------- Methodology: asymmetric, spec values in mono ---------------- */}
      <section className="method container">
        <div className="method__intro">
          <p className="label">How the forecast is produced</p>
          <h2 className="method__title">A frozen model, tested once on years it never saw</h2>
          <p className="body-secondary">
            Each road segment&rsquo;s recent collision record, road attributes and neighbouring roads feed a
            gradient-boosted count model. Its specification was fixed on earlier years, then tested once on
            2024&ndash;25 outcomes before being used to forecast {ready ? period(r.forecastPeriod) : 'the next two years'}.
          </p>
          <p className="method__caveat">
            The forecast is an expected casualty burden. It is not a per-vehicle risk, not a probability that a
            collision will happen, and not a statement of cause: it does not say what would reduce casualties.
          </p>
        </div>

        <dl className="method__spec">
          <div className="method__row">
            <dt>Model</dt>
            <dd>LightGBM, Poisson objective</dd>
          </div>
          <div className="method__row">
            <dt>Frozen specification</dt>
            <dd className="mono">{ready ? r.frozenSpec.slice(0, 12) : '—'}</dd>
          </div>
          <div className="method__row">
            <dt>Target</dt>
            <dd>KSI casualties per segment, DfT severity-adjusted, two-year total</dd>
          </div>
          <div className="method__row">
            <dt>Segments</dt>
            <dd>OS Open Roads, about 500 m, built without crash data</dd>
          </div>
          {holdout && (
            <>
              <div className="method__row">
                <dt>Holdout, top 10% capture</dt>
                <dd className="mono">
                  {fixed(holdout.top10_capture_model_pct, 1)}% vs {fixed(holdout.top10_capture_crash_counts_pct, 1)}%
                  for crash counts
                </dd>
              </div>
              <div className="method__row">
                <dt>Holdout population</dt>
                <dd className="mono">2024–25 outcomes, all {int(r.nationalSegments)} segments</dd>
              </div>
            </>
          )}
        </dl>
      </section>

      <footer className="landing__foot">
        <div className="container landing__foot-inner">
          <p className="landing__foot-brand">
            {PRODUCT} · {PRODUCT_SUBTITLE}
          </p>
          <ProvenanceStrip />
          <p className="landing__foot-note">
            {ready
              ? `Local demonstration build: ${int(data.segments.length)} of ${int(
                  r.nationalSegments,
                )} scored segments, copied from the verified v2 ML release. The forecast is precomputed; nothing here reads live traffic or incident feeds. Coverage is Great Britain only; Northern Ireland is not covered.`
              : 'Loading.'}
          </p>
        </div>
      </footer>
    </div>
  );
}
