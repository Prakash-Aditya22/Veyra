import { useMemo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  Legend as RechartsLegend,
} from 'recharts';
import ChartFrame, { ChartTooltip, AXIS, GRID } from '../components/charts/ChartFrame.jsx';
import ProvenanceStrip from '../components/ProvenanceStrip.jsx';
import Reveal from '../components/motion/Reveal.jsx';
import CountUp from '../components/motion/CountUp.jsx';
import SpringBar from '../components/motion/SpringBar.jsx';
import { BLACKSPOTS, DATASET } from '../data/blackspots.js';
import { BY_MONTH, BY_YEAR_SEVERITY } from '../data/series.js';
import { byHour, byRoadClass, topFactors, totals, peakHour } from '../lib/stats.js';
import { num, pct, hourLabel } from '../lib/format.js';
import './Statistics.css';

const TEAL = '#0F766E';
const TEAL_LIFT = '#14918A';

export default function Statistics() {
  const t = useMemo(() => totals(BLACKSPOTS), []);
  const hours = useMemo(() => byHour(BLACKSPOTS), []);
  const peak = useMemo(() => peakHour(BLACKSPOTS), []);
  const roads = useMemo(() => byRoadClass(BLACKSPOTS).slice(0, 8), []);
  const factors = useMemo(() => topFactors(BLACKSPOTS, 7), []);

  const clusterMeta = `${num(t.incidents)} records inside ${DATASET.clusters} clusters, ${DATASET.from} to ${DATASET.to}`;
  const datasetMeta = `${num(DATASET.records)} records, all of ${DATASET.from} to ${DATASET.to}`;

  return (
    <div className="stats">
      <div className="container stats__head">
        <h1 className="screen-title">Statistics</h1>
        <p className="body-secondary">
          Aggregate patterns across the {DATASET.region}. The monthly and yearly panels
          cover every record in the window; the hourly and road-class panels cover only
          records that fell inside a detected cluster.
        </p>
        <ProvenanceStrip />
      </div>

      {/* KPI strip. Plain layout, hairline separated. No cards in a dense region. */}
      <div className="container">
        <div className="kpi-strip">
          <Reveal className="kpi" index={0}>
            <p className="label">Records in window</p>
            <p className="kpi__value mono">
              <CountUp value={DATASET.records} />
            </p>
          </Reveal>
          <Reveal className="kpi" index={1}>
            <p className="label">Clustered records</p>
            <p className="kpi__value mono">
              <CountUp value={t.incidents} />
            </p>
            <p className="kpi__note mono">{pct(t.incidents, DATASET.records)}% of window</p>
          </Reveal>
          <Reveal className="kpi" index={2}>
            <p className="label">Fatal outcomes</p>
            <p className="kpi__value mono">
              <CountUp value={t.fatal} />
            </p>
            <p className="kpi__note mono">{pct(t.fatal, t.incidents)}% of clustered</p>
          </Reveal>
          <Reveal className="kpi" index={3}>
            <p className="label">Peak hour</p>
            {/* A clock reading is not a quantity, so it does not count up. */}
            <p className="kpi__value mono">{hourLabel(peak.hour)}</p>
            <p className="kpi__note mono">{num(peak.count)} incidents</p>
          </Reveal>
        </div>
      </div>

      {/* Asymmetric 2:1, then 1:2. Never four equal cards. */}
      <div className="container stats__grid">
        <Reveal className="stats__panel stats__panel--wide">
        <ChartFrame
          title="Incidents by calendar month"
          meta={datasetMeta}
        >
          <div className="stats__chart">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={BY_MONTH} margin={{ top: 4, right: 4, bottom: 0, left: -14 }}>
                <CartesianGrid {...GRID} />
                <XAxis {...AXIS} dataKey="month" />
                <YAxis {...AXIS} width={46} />
                <Tooltip
                  cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
                  content={(p) => <ChartTooltip {...p} unit="records in month" />}
                />
                <Bar
                  dataKey="count"
                  name="Records"
                  radius={[3, 3, 0, 0]}
                  isAnimationActive={false}
                >
                  {BY_MONTH.map((m) => (
                    <Cell
                      key={m.month}
                      fill={TEAL}
                      // Monsoon months carry the visual weight; same hue, no second accent.
                      fillOpacity={['Jun', 'Jul', 'Aug', 'Sep'].includes(m.month) ? 1 : 0.5}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartFrame>
        </Reveal>

        <Reveal className="stats__panel">
        <ChartFrame
          title="Incidents by hour"
          meta={`${clusterMeta}. Peak at ${hourLabel(peak.hour)}.`}
        >
          <div className="stats__chart">
            <ResponsiveContainer width="100%" height="100%">
              {/* left margin kept shallow so three-digit y ticks are not clipped */}
              <BarChart data={hours} margin={{ top: 4, right: 4, bottom: 0, left: -6 }}>
                <CartesianGrid {...GRID} />
                <XAxis
                  {...AXIS}
                  dataKey="hour"
                  interval={3}
                  tickFormatter={(h) => String(h).padStart(2, '0')}
                />
                <YAxis {...AXIS} width={42} />
                <Tooltip
                  cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
                  content={(p) => (
                    <ChartTooltip {...p} label={hourLabel(p.label)} unit="clustered incidents" />
                  )}
                />
                <Bar
                  dataKey="count"
                  name="Incidents"
                  radius={[2, 2, 0, 0]}
                  isAnimationActive={false}
                >
                  {hours.map((h) => (
                    <Cell
                      key={h.hour}
                      fill={h.hour === peak.hour ? TEAL_LIFT : TEAL}
                      fillOpacity={h.hour === peak.hour ? 1 : 0.55}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartFrame>
        </Reveal>

        <Reveal className="stats__panel">
        <ChartFrame
          title="Severity split by year"
          meta={datasetMeta}
        >
          <div className="stats__chart">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={BY_YEAR_SEVERITY}
                margin={{ top: 4, right: 4, bottom: 0, left: -14 }}
              >
                <CartesianGrid {...GRID} />
                <XAxis {...AXIS} dataKey="year" />
                <YAxis {...AXIS} width={46} />
                <Tooltip
                  cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
                  content={(p) => <ChartTooltip {...p} unit="records" />}
                />
                <RechartsLegend
                  iconType="square"
                  iconSize={9}
                  wrapperStyle={{
                    fontSize: 11,
                    fontFamily: "'Satoshi', sans-serif",
                    color: '#9AA2AE',
                    paddingTop: 6,
                  }}
                />
                {/* Severity uses the risk ramp. Status green and amber are banned here. */}
                <Bar
                  dataKey="slight"
                  stackId="s"
                  name="Slight"
                  fill="#C2711F"
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="serious"
                  stackId="s"
                  name="Serious"
                  fill="#A33A2B"
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="fatal"
                  stackId="s"
                  name="Fatal"
                  fill="#7A1F1A"
                  radius={[3, 3, 0, 0]}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartFrame>
        </Reveal>

        <Reveal className="stats__panel stats__panel--wide">
        <ChartFrame
          title="Clustered incidents by road class"
          meta={clusterMeta}
        >
          <div className="stats__chart">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={roads}
                layout="vertical"
                /* bottom margin leaves room for the wrapped "Rural district road" tick */
                margin={{ top: 4, right: 12, bottom: 10, left: 34 }}
              >
                <CartesianGrid
                  stroke="rgba(148, 163, 184, 0.14)"
                  horizontal={false}
                  strokeDasharray="0"
                />
                <XAxis {...AXIS} type="number" />
                <YAxis {...AXIS} type="category" dataKey="roadClass" width={124} />
                <Tooltip
                  cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
                  content={(p) => <ChartTooltip {...p} unit="clustered incidents" />}
                />
                <Bar
                  dataKey="incidents"
                  name="Incidents"
                  fill={TEAL}
                  radius={[0, 3, 3, 0]}
                  barSize={14}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartFrame>
        </Reveal>
      </div>

      {/* A different layout family: a ranked list, not another chart panel. */}
      <div className="container stats__factors">
        <div className="stats__factors-head">
          <h2 className="panel-title">Contributing factors, weighted by cluster size</h2>
          <p className="label stats__factors-meta">
            {clusterMeta}. Weights scaled against the highest-ranked factor.
          </p>
        </div>
        <ol className="factor-rank">
          {factors.map((f, i) => (
            <Reveal as="li" key={f.label} className="factor-rank__row" index={i}>
              <span className="factor-rank__index mono">{String(i + 1).padStart(2, '0')}</span>
              <span className="factor-rank__label">{f.label}</span>
              <span className="factor-rank__track" aria-hidden="true">
                <SpringBar className="factor-rank__fill" percent={f.share} index={i} />
              </span>
              <span className="factor-rank__value mono">{f.share}</span>
            </Reveal>
          ))}
        </ol>
      </div>
    </div>
  );
}
