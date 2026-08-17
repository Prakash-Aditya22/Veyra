import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { ArrowRight } from '@phosphor-icons/react';
import MapFragment from '../components/MapFragment.jsx';
import MapCanvas from '../components/MapCanvas.jsx';
import RiskBadge from '../components/RiskBadge.jsx';
import ProvenanceStrip from '../components/ProvenanceStrip.jsx';
import Reveal from '../components/motion/Reveal.jsx';
import CountUp from '../components/motion/CountUp.jsx';
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

  const rise = (delay = 0) => ({
    initial: reduce ? false : { opacity: 0, y: 14 },
    animate: { opacity: 1, y: 0 },
    transition: { type: 'spring', stiffness: 100, damping: 20, delay },
  });

  return (
    <div className="landing">
      {/* ---------------- Hero: left type column, map bleeding off the right ---------------- */}
      <section className="hero">
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

          <motion.div {...rise(0.12)}>
            <Link to="/explorer" className="btn btn-primary hero__cta">
              Open the map
              <ArrowRight size={16} weight="bold" />
            </Link>
          </motion.div>
        </div>

        <div className="hero__map" aria-hidden="true">
          <MapCanvas
            blackspots={BLACKSPOTS}
            selectedId={null}
            interactive={false}
            showLegend={false}
          />
          <span className="hero__map-fade" />
        </div>
      </section>

      {/* ---------------- Metric strip ---------------- */}
      <section className="metrics">
        <div className="container metrics__inner">
          <Reveal className="metric" index={0}>
            <p className="metric__value mono">
              <CountUp value={DATASET.records} />
            </p>
            <p className="label">Records analysed</p>
          </Reveal>
          <Reveal className="metric" index={1}>
            <p className="metric__value mono">
              <CountUp value={DATASET.clusters} />
            </p>
            <p className="label">Clusters identified</p>
          </Reveal>
          <Reveal className="metric" index={2}>
            {/* A span of years is not a quantity, so it does not count up. */}
            <p className="metric__value mono">
              {DATASET.from} to {DATASET.to}
            </p>
            <p className="label">Coverage window</p>
          </Reveal>
        </div>
      </section>

      {/* ---------------- Capability one: map, copy on the right ---------------- */}
      <section className="capability container">
        <Reveal className="capability__visual">
          <MapCanvas
            blackspots={BLACKSPOTS}
            selectedId={null}
            interactive={false}
            showLegend={false}
          />
        </Reveal>
        <Reveal className="capability__copy" delay={0.08}>
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
        </Reveal>
      </section>

      {/* ---------------- Capability two: copy left, real ranked rows right ---------------- */}
      <section className="capability capability--flip container">
        <Reveal className="capability__copy">
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
        </Reveal>

        {/*
          Not a mock-up: these are the same row and badge components the
          rankings screen renders, reading the same data. They cascade in on the
          same 30ms step the explorer's ranked list uses.
        */}
        <div className="capability__rows">
          {PREVIEW_ROWS.map((b, i) => (
            <Reveal key={b.id} index={i}>
              <Link to={`/explorer?cluster=${b.id}`} className="preview-row">
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
            </Reveal>
          ))}
        </div>
      </section>

      {/* ---------------- Methodology: asymmetric, spec values in mono ---------------- */}
      <section className="method container">
        <Reveal className="method__intro">
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
        </Reveal>

        <Reveal as="dl" className="method__spec" delay={0.08}>
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
        </Reveal>
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
