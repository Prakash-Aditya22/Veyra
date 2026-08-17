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
import { BLACKSPOTS, DATASET } from '../data/blackspots.js';
import { MODEL_RUN } from '../data/series.js';
import { num, shortDate } from '../lib/format.js';
import './Landing.css';

// The two crops in the headline are centred on the corridor's two
// highest-scoring clusters, so the imagery is the dataset's own.
const [TOP, SECOND] = BLACKSPOTS;

const PREVIEW_ROWS = BLACKSPOTS.slice(0, 5);

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
          <motion.h1 className="hero__headline" {...rise(0)}>
            A few stretches
            <MapFragment lat={TOP.lat} lng={TOP.lng} label={TOP.name} />
            account for most of the
            <MapFragment lat={SECOND.lat} lng={SECOND.lng} label={SECOND.name} />
            harm.
          </motion.h1>

          <motion.p className="hero__sub" {...rise(0.06)}>
            Historical incident records for the Bhubaneswar to Cuttack corridor, clustered
            and scored so the worst stretches surface first.
          </motion.p>
        </div>
      </section>

      {/* ---------------- Metric strip ---------------- */}
      <section className="metrics">
        <div className="container metrics__inner">
          <div className="metric">
            <p className="metric__value mono">
              <CountUp value={DATASET.records} />
            </p>
            <p className="label">Records analysed</p>
          </div>
          <div className="metric">
            <p className="metric__value mono">
              <CountUp value={DATASET.clusters} />
            </p>
            <p className="label">Clusters identified</p>
          </div>
          <div className="metric">
            {/* A span of years is not a quantity, so it does not count up. */}
            <p className="metric__value mono">
              {DATASET.from} to {DATASET.to}
            </p>
            <p className="label">Coverage window</p>
          </div>
        </div>
      </section>

      {/* ---------------- Capability one: map, copy on the right ---------------- */}
      <section className="capability container">
        <div className="capability__visual">
          <MapCanvas
            blackspots={BLACKSPOTS}
            selectedId={null}
            interactive={false}
            showLegend={false}
          />
        </div>
        <div className="capability__copy">
          <h2 className="capability__title">Read the whole corridor in one view</h2>
          <p className="body-secondary">
            Every cluster is drawn at its centroid, sized by how many records fall inside
            it and filled with its danger tier. Filter by period, severity, road class or
            conditions, and the map and the ranked panel move together.
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
            The composite score combines how often a stretch appears, how severe those
            records were, and how recent they are. Boundaries are fixed and published, so
            a score of 74 means the same thing on every screen and in every filter state.
          </p>
          <Link to="/rankings" className="capability__link">
            See the full ranking
            <ArrowRight size={14} weight="bold" />
          </Link>
        </div>

        {/*
          Not a mock-up: these are the same row and badge components the
          rankings screen renders, reading the same data.
        */}
        <div className="capability__rows">
          {PREVIEW_ROWS.map((b, i) => (
            <Link key={b.id} to={`/explorer?cluster=${b.id}`} className="preview-row">
              <span className="preview-row__rank mono">
                {String(i + 1).padStart(2, '0')}
              </span>
              <span className="preview-row__body">
                <span className="preview-row__name">{b.name}</span>
                <span className="preview-row__meta mono">
                  {num(b.incidents)} incidents, last {shortDate(b.lastIncident)}
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
          <h2 className="method__title">
            Density clustering first, severity weighting second
          </h2>
          <p className="body-secondary">
            Records are cleaned and projected, then grouped by spatial density so clusters
            follow the shape of the road rather than a grid. A severity classifier
            estimates outcome from road class, hour, light and surface state. The two feed
            a single composite score with recent records weighted higher.
          </p>
          <p className="method__caveat">
            The model surfaces historical clustering. It describes where harm has
            concentrated, not where harm will occur.
          </p>
        </div>

        <dl className="method__spec">
          <div className="method__row">
            <dt>Clustering</dt>
            <dd>{MODEL_RUN.algorithm}</dd>
          </div>
          <div className="method__row">
            <dt>Neighbourhood radius</dt>
            <dd className="mono">{MODEL_RUN.epsilonMetres} m</dd>
          </div>
          <div className="method__row">
            <dt>Minimum cluster size</dt>
            <dd className="mono">{MODEL_RUN.minSamples} records</dd>
          </div>
          <div className="method__row">
            <dt>Silhouette score</dt>
            <dd className="mono">{MODEL_RUN.silhouette.toFixed(2)}</dd>
          </div>
          <div className="method__row">
            <dt>Severity classifier</dt>
            <dd>{MODEL_RUN.classifier}</dd>
          </div>
          <div className="method__row">
            <dt>Macro F1</dt>
            <dd className="mono">{MODEL_RUN.macroF1.toFixed(2)}</dd>
          </div>
          <div className="method__row">
            <dt>Recall, fatal class</dt>
            <dd className="mono">{MODEL_RUN.recallFatal.toFixed(2)}</dd>
          </div>
        </dl>
      </section>

      <footer className="landing__foot">
        <div className="container landing__foot-inner">
          <ProvenanceStrip />
          <p className="landing__foot-note">
            Figures on this build are a demonstration fixture standing in for the
            processed dataset. Clusters are precomputed and served as static output; the
            interface does not read live traffic or incident feeds.
          </p>
        </div>
      </footer>
    </div>
  );
}
