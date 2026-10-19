import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import ChartFrame, { AXIS, ChartTooltip, GRID } from '../components/charts/ChartFrame.jsx';
import ProvenanceStrip from '../components/ProvenanceStrip.jsx';
import { ErrorState, ChartSkeleton } from '../components/States.jsx';
import Reveal from '../components/motion/Reveal.jsx';
import SpringBar from '../components/motion/SpringBar.jsx';
import { useData } from '../data/DataContext.jsx';
import { useFilters } from '../data/FiltersContext.jsx';
import { applyFilters, countActive } from '../lib/filters.js';
import { styledTiers } from '../lib/priority.js';
import { byTier, leadingFactors, summarize } from '../lib/stats.js';
import { int, ksi, pct, period } from '../lib/format.js';
import { usePageTitle } from '../lib/usePageTitle.js';
import './Statistics.css';

const TEAL = '#0F766E';

/*
  Three populations, always named:
    national  - every scored GB segment (from the release; not loaded here)
    loaded    - the segments in this demo (a top-ranked subset plus reference cases)
    selection - the loaded segments left by the explorer's current filters
*/
export default function Statistics() {
  const data = useData();
  const { filters } = useFilters();
  const ready = data.status === 'ready';
  const selection = useMemo(() => (ready ? applyFilters(data.segments, filters) : []), [ready, data.segments, filters]);
  const s = useMemo(() => summarize(selection), [selection]);
  const tiers = useMemo(() => (ready ? byTier(selection, styledTiers(data.release.tiers)) : []), [ready, selection, data.release]);
  const factors = useMemo(() => leadingFactors(selection, 8), [selection]);
  usePageTitle('Statistics');

  if (data.status === 'error') {
    return (
      <div className="stats container">
        <ErrorState message={`Statistics could not be loaded. ${data.error}`} onRetry={data.retry} />
      </div>
    );
  }
  if (!ready) {
    return (
      <div className="stats container">
        <ChartSkeleton height={320} />
      </div>
    );
  }

  const r = data.release;
  const fp = period(r.forecastPeriod);
  const hp = period(r.historyPeriod);
  const filtered = countActive(filters) > 0;
  const years = data.context?.stats19_by_year?.rows ?? [];
  const selMeta = `${int(s.n)} segments in the selection (${filtered ? 'explorer filters applied' : 'no filters: all loaded segments'})`;

  return (
    <div className="stats">
      <div className="container stats__head">
        <h1 className="screen-title">Statistics</h1>
        <p className="body-secondary">
          Figures for three different populations, each named where it is used. The national model scores{' '}
          {int(r.nationalSegments)} road segments; this demo loads {int(data.segments.length)} of them (the national top{' '}
          {int(r.subset.nTop)} and {int(r.subset.nReference)} lower-ranked reference cases); the selection is what the
          explorer&rsquo;s filters leave.{' '}
          <Link to="/explorer" className="stats__link">
            Change the filters in the explorer
          </Link>
          .
        </p>
        <ProvenanceStrip />
      </div>

      <div className="container">
        <div className="kpi-strip">
          <div className="kpi">
            <p className="label">National model</p>
            <p className="kpi__value mono">{int(r.nationalSegments)}</p>
            <p className="kpi__note">
              segments scored · {int(r.nationalExpectedKsi)} expected KSI casualties in {fp} (sum of all forecasts)
            </p>
          </div>
          <div className="kpi">
            <p className="label">Loaded in this demo</p>
            <p className="kpi__value mono">{int(data.segments.length)}</p>
            <p className="kpi__note">
              {pct(data.segments.length, r.nationalSegments, 3)} of scored segments. A top-ranked subset, not a sample:
              do not read its totals as national.
            </p>
          </div>
          <div className="kpi">
            <p className="label">Current selection</p>
            <p className="kpi__value mono">{int(s.n)}</p>
            <p className="kpi__note">of {int(data.segments.length)} loaded segments</p>
          </div>
          <div className="kpi">
            <p className="label">Selection, expected KSI {fp}</p>
            <p className="kpi__value mono">{ksi(s.expectedKsi, 0)}</p>
            <p className="kpi__note">
              {pct(s.expectedKsi, r.nationalExpectedKsi, 1)} of the national forecast total of {int(r.nationalExpectedKsi)}
            </p>
          </div>
        </div>
        <dl className="stats__facts">
          <div>
            <dt>With 6 or more collisions in {hp}</dt>
            <dd className="mono">
              {int(s.sufficient)} of {int(s.n)} ({pct(s.sufficient, s.n, 0)})
            </dd>
          </div>
          <div>
            <dt>Per-vehicle rate available</dt>
            <dd className="mono">
              {int(s.rateShown)} of {int(s.n)} ({pct(s.rateShown, s.n, 0)})
            </dd>
          </div>
          <div>
            <dt>Single-event warning</dt>
            <dd className="mono">
              {int(s.singleEvent)} of {int(s.n)}
            </dd>
          </div>
          <div>
            <dt>Model explanation available</dt>
            <dd className="mono">{s.explained === null ? 'Not known for this data source' : `${int(s.explained)} of ${int(s.n)}`}</dd>
          </div>
        </dl>
      </div>

      <div className="container stats__grid">
        <Reveal className="stats__panel stats__panel--wide">
          <ChartFrame title={`Expected serious or fatal casualties, ${fp}, by road class`} meta={`${selMeta}. Sum of the ML forecast per class.`}>
            <div className="stats__chart" role="img" aria-label={`Expected serious or fatal casualties by road class, ${fp}: ${s.byClass.map((c) => `${c.label} ${ksi(c.expectedKsi, 1)}`).join('; ')}.`}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={s.byClass} layout="vertical" margin={{ top: 4, right: 12, bottom: 4, left: 34 }}>
                  <CartesianGrid stroke="rgba(148, 163, 184, 0.14)" horizontal={false} strokeDasharray="0" />
                  <XAxis {...AXIS} type="number" />
                  <YAxis {...AXIS} type="category" dataKey="label" width={150} />
                  <Tooltip
                    cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
                    content={(p) => <ChartTooltip {...p} unit={`expected KSI casualties, ${fp}`} />}
                  />
                  <Bar dataKey="expectedKsi" name="Expected KSI" fill={TEAL} radius={[0, 3, 3, 0]} barSize={14} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartFrame>
        </Reveal>

        <Reveal className="stats__panel">
          <ChartFrame title="Segments by national rank group" meta={`${selMeta}. Axis: national rank bands (exact, non-overlapping).`}>
            <div className="stats__chart" role="img" aria-label={`Segments by national rank group: ${tiers.map((t) => `${t.label}: ${int(t.n)}`).join('; ')}.`}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={tiers} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
                  <CartesianGrid {...GRID} />
                  {/* compact rank labels so all four fit; tooltip and summary give "Ranks ..." in full */}
                  <XAxis {...AXIS} dataKey="short" interval={0} />
                  <YAxis {...AXIS} width={42} allowDecimals={false} />
                  <Tooltip cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }} content={(p) => <ChartTooltip {...p} label={`Ranks ${p.label}`} unit="segments in the selection" />} />
                  <Bar dataKey="n" name="Segments" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    {tiers.map((t) => (
                      <Cell key={t.key} fill={t.hex} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartFrame>
        </Reveal>

        <Reveal className="stats__panel">
          <ChartFrame
            title="Rank stability across 20 model refits"
            meta={`${int(s.stabilityDenominator)} segments in the selection with stability data. Robust top 1,000: in the top 1,000 in at least 90% of refits.`}
          >
            <ul className="stab-list">
              {s.stability.map((row, i) => (
                <li key={row.key} className="stab-list__row">
                  <span className="stab-list__label">{row.key}</span>
                  <span className="stab-list__track" aria-hidden="true">
                    <SpringBar className="stab-list__fill" percent={Math.round((100 * row.n) / Math.max(1, s.stabilityDenominator))} index={i} />
                  </span>
                  <span className="mono stab-list__n">
                    {int(row.n)} ({pct(row.n, s.stabilityDenominator, 1)})
                  </span>
                </li>
              ))}
              {s.stability.length === 0 && <li className="stab-list__row">Not available for this selection.</li>}
            </ul>
          </ChartFrame>
        </Reveal>

        <Reveal className="stats__panel stats__panel--wide">
          <ChartFrame
            title="Serious or fatal casualties in Great Britain by year, DfT severity-adjusted"
            meta="All police-reported injury collisions in GB (DfT STATS19), not only the loaded segments. National context, not a model output."
          >
            <div className="stats__chart" role="img" aria-label={`Adjusted serious or fatal casualties in Great Britain by year: ${years.map((y) => `${y.collision_year} ${int(y.adj_ksi_cas)}`).join('; ')}.`}>
              {years.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={years} margin={{ top: 4, right: 4, bottom: 0, left: -6 }}>
                    <CartesianGrid {...GRID} />
                    <XAxis {...AXIS} dataKey="collision_year" />
                    <YAxis {...AXIS} width={52} />
                    <Tooltip
                      cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
                      content={(p) => <ChartTooltip {...p} unit="KSI casualties in GB (adjusted)" />}
                    />
                    <Bar dataKey="adj_ksi_cas" name="Adjusted KSI" fill={TEAL} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="detail__na">Not available from this data source.</p>
              )}
            </div>
          </ChartFrame>
        </Reveal>
      </div>

      <div className="container stats__factors">
        <div className="stats__factors-head">
          <h2 className="panel-title">Largest model attribution per segment</h2>
          <p className="label stats__factors-meta">
            How often each feature is the single largest TreeSHAP attribution, among {int(factors.denominator)} segments in the
            selection with an explanation. Associations learnt by the model, not causes.
          </p>
        </div>
        <ol className="factor-rank">
          {factors.rows.map((f, i) => (
            <Reveal as="li" key={f.label} className="factor-rank__row" index={i}>
              <span className="factor-rank__index mono">{String(i + 1).padStart(2, '0')}</span>
              <span className="factor-rank__label">{f.label}</span>
              <span className="factor-rank__track" aria-hidden="true">
                <SpringBar className="factor-rank__fill" percent={Math.round((100 * f.n) / Math.max(1, factors.denominator))} index={i} />
              </span>
              <span className="factor-rank__value mono">
                {int(f.n)} ({pct(f.n, factors.denominator, 1)})
              </span>
            </Reveal>
          ))}
          {factors.rows.length === 0 && <li className="factor-rank__row">Explanation not available for this selection.</li>}
        </ol>
      </div>
    </div>
  );
}
