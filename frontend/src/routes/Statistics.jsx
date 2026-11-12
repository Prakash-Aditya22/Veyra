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
import GB from '../data/gbStats.json';
import { TIERS, tierOf } from '../lib/risk.js';
import { scoreToDisplay } from '../lib/riskScale.js';
import { num, pct } from '../lib/format.js';
import './Statistics.css';

/*
  Great Britain, from what the pipeline actually produced.

  gbStats.json is built by ml/build_stats_summary.py from the scored segment
  CSV, the blackspot run's validation log and the severity model's SHAP
  output. The crash-level STATS19 file is not shipped, so there is no
  month, hour or year breakdown here: every panel is either a per-segment
  aggregate of 2019-2021 counts or a number the pipeline printed.
*/

const BLUE = '#1F4FBF'; // 青色, the interface accent
const BLUE_DEEP = BLUE; // the peak bar is marked by full opacity, not a second blue
const SLATE = 'rgba(238, 240, 244, 0.5)'; // paper-white, for comparison series
const SLATE_DIM = 'rgba(238, 240, 244, 0.22)';

const T = GB.totals;
const CRASH_SPAN = `${GB.crashYears[0]} to ${GB.crashYears[1]}`;
const FORECAST_SPAN = `${GB.forecastYears[0]} to ${GB.forecastYears[1]}`;

const LEGEND_STYLE = {
  fontSize: 11,
  fontFamily: "'Satoshi', sans-serif",
  color: 'rgba(238, 240, 244, 0.74)',
  paddingTop: 6,
};

/** Validation rows -> one record per cutoff, one key per method, for grouped bars. */
function validationSeries() {
  const [model, crashes, ksi] = GB.validation.rows;
  return GB.validation.cutoffs.map((cutoff, i) => ({
    cutoff,
    model: model.values[i],
    crashes: crashes.values[i],
    ksi: ksi.values[i],
  }));
}

/*
  Tiers are binned here, with the map's own functions, rather than in the
  Python script, so the cutoffs keep living in riskScale.js alone.
*/
function tierCounts() {
  const counts = new Map(TIERS.map((t) => [t.key, 0]));
  for (const s of GB.evidencedScores) {
    const tier = tierOf(scoreToDisplay(s));
    counts.set(tier.key, (counts.get(tier.key) ?? 0) + 1);
  }
  return TIERS.map((t) => ({ tier: t.word, count: counts.get(t.key), fill: t.hex }));
}

export default function Statistics() {
  const validation = useMemo(validationSeries, []);
  const tiers = useMemo(tierCounts, []);
  const peakSpeed = useMemo(
    () => GB.bySpeed.reduce((a, b) => (b.ksiShare > a.ksiShare ? b : a)),
    [],
  );
  const [model, crashCount] = GB.validation.rows;

  const segmentMeta = `${num(T.segments)} segments on ${num(T.roads)} roads, crashes ${CRASH_SPAN}`;

  return (
    <div className="stats">
      <div className="container stats__head">
        <h1 className="screen-title">Statistics</h1>
        <p className="body-secondary">
          Patterns across Great Britain&rsquo;s numbered roads, from the STATS19 record. Counts
          are recorded crashes from {CRASH_SPAN}; the blackspot score is the model&rsquo;s
          forecast of killed-or-seriously-injured casualties in {FORECAST_SPAN}, checked on
          road it never trained on.
        </p>
        <ProvenanceStrip
          items={[
            'STATS19, Great Britain',
            `crashes ${CRASH_SPAN}`,
            `KSI forecast ${FORECAST_SPAN}`,
            `${num(T.segments)} scored 500 m segments`,
            `${num(T.roads)} roads`,
          ]}
        />
      </div>

      {/* KPI strip. Plain layout, hairline separated. No cards in a dense region. */}
      <div className="container">
        <div className="kpi-strip">
          <Reveal className="kpi" index={0}>
            <p className="label">Crashes on scored roads</p>
            <p className="kpi__value mono">
              <CountUp value={T.crashes} />
            </p>
            <p className="kpi__note mono">{CRASH_SPAN}</p>
          </Reveal>
          <Reveal className="kpi" index={1}>
            <p className="label">Fatal or serious</p>
            <p className="kpi__value mono">
              <CountUp value={T.ksi} />
            </p>
            <p className="kpi__note mono">{pct(T.ksi, T.crashes)}% of crashes</p>
          </Reveal>
          <Reveal className="kpi" index={2}>
            <p className="label">Fatal</p>
            <p className="kpi__value mono">
              <CountUp value={T.fatal} />
            </p>
            <p className="kpi__note mono">{pct(T.fatal, T.crashes)}% of crashes</p>
          </Reveal>
          <Reveal className="kpi" index={3}>
            <p className="label">Evidenced segments</p>
            <p className="kpi__value mono">
              <CountUp value={T.evidencedSegments} />
            </p>
            <p className="kpi__note mono">
              {GB.minCrashes}+ crashes, of {num(T.segments)}
            </p>
          </Reveal>
        </div>
      </div>

      {/* Asymmetric 2:1, then 1:2. Never four equal cards. */}
      <div className="container stats__grid">
        <Reveal className="stats__panel stats__panel--wide">
          <ChartFrame
            title="Share of future serious harm found by each ranking"
            meta={`Held-out segments, KSI in ${FORECAST_SPAN}. The model's top 20% captures ${model.values[3]}%; ranking by past crash count captures ${crashCount.values[3]}%.`}
          >
            <div className="stats__chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={validation} margin={{ top: 4, right: 4, bottom: 0, left: -14 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis {...AXIS} dataKey="cutoff" />
                  <YAxis {...AXIS} width={46} unit="%" />
                  <Tooltip
                    cursor={{ fill: 'rgba(238, 240, 244, 0.06)' }}
                    content={(p) => (
                      <ChartTooltip {...p} unit={`% of ${FORECAST_SPAN} KSI on those segments`} />
                    )}
                  />
                  <RechartsLegend iconType="square" iconSize={9} wrapperStyle={LEGEND_STYLE} />
                  <Bar dataKey="model" name="Blackspot model" fill={BLUE} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                  <Bar dataKey="crashes" name="Past crash count" fill={SLATE} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                  <Bar dataKey="ksi" name="Past KSI count" fill={SLATE_DIM} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartFrame>
        </Reveal>

        <Reveal className="stats__panel">
          <ChartFrame
            title="Evidenced segments by risk tier"
            meta={`${num(T.evidencedSegments)} segments with ${GB.minCrashes}+ crashes. Tiers are relative to these, not to every road.`}
          >
            <div className="stats__chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={tiers} margin={{ top: 4, right: 4, bottom: 0, left: -6 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis {...AXIS} dataKey="tier" />
                  <YAxis {...AXIS} width={42} />
                  <Tooltip
                    cursor={{ fill: 'rgba(238, 240, 244, 0.06)' }}
                    content={(p) => <ChartTooltip {...p} unit="segments" />}
                  />
                  <Bar dataKey="count" name="Segments" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    {tiers.map((t) => (
                      <Cell key={t.tier} fill={t.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartFrame>
        </Reveal>

        <Reveal className="stats__panel">
          <ChartFrame
            title="Crashes that were fatal or serious, by speed limit"
            meta={`${segmentMeta}. Highest speed limit on each segment. Peak at ${peakSpeed.speed}.`}
          >
            <div className="stats__chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={GB.bySpeed} margin={{ top: 4, right: 4, bottom: 0, left: -14 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis {...AXIS} dataKey="speed" />
                  <YAxis {...AXIS} width={46} unit="%" />
                  <Tooltip
                    cursor={{ fill: 'rgba(238, 240, 244, 0.06)' }}
                    content={(p) => <ChartTooltip {...p} unit="% of crashes at this limit" />}
                  />
                  <Bar dataKey="ksiShare" name="Fatal or serious" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    {GB.bySpeed.map((s) => (
                      <Cell
                        key={s.speed}
                        fill={s.speed === peakSpeed.speed ? BLUE_DEEP : BLUE}
                        fillOpacity={s.speed === peakSpeed.speed ? 1 : 0.55}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartFrame>
        </Reveal>

        <Reveal className="stats__panel stats__panel--wide">
          <ChartFrame
            title="Roads with the most fatal or serious crashes"
            meta={`Summed over each road's scored segments, ${CRASH_SPAN}.`}
          >
            <div className="stats__chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={GB.topRoads}
                  layout="vertical"
                  margin={{ top: 4, right: 12, bottom: 10, left: 0 }}
                >
                  <CartesianGrid stroke="rgba(238, 240, 244, 0.12)" horizontal={false} strokeDasharray="0" />
                  <XAxis {...AXIS} type="number" />
                  <YAxis {...AXIS} type="category" dataKey="road" width={56} />
                  <Tooltip
                    cursor={{ fill: 'rgba(238, 240, 244, 0.06)' }}
                    content={(p) => <ChartTooltip {...p} unit="crashes" />}
                  />
                  <RechartsLegend iconType="square" iconSize={9} wrapperStyle={LEGEND_STYLE} />
                  <Bar dataKey="ksi" name="Fatal or serious" fill={BLUE} radius={[0, 3, 3, 0]} barSize={14} isAnimationActive={false} />
                  <Bar dataKey="fatal" name="Fatal" fill="#D7120F" radius={[0, 3, 3, 0]} barSize={14} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartFrame>
        </Reveal>
      </div>

      {/* A different layout family: a ranked list, not another chart panel. */}
      <div className="container stats__factors">
        <div className="stats__factors-head">
          <h2 className="panel-title">Conditions linked to more serious crashes</h2>
          <p className="label stats__factors-meta">
            Severity model, {FORECAST_SPAN} collisions. Ranked by how far the predicted chance
            of a serious outcome moves between a condition&rsquo;s levels, scaled to the top
            factor. Associations, not causes; police force excluded as administrative.
          </p>
        </div>
        <ol className="factor-rank">
          {GB.factors.map((f, i) => (
            <Reveal as="li" key={f.key} className="factor-rank__row" index={i}>
              <span className="factor-rank__index mono">{String(i + 1).padStart(2, '0')}</span>
              <span className="factor-rank__label">
                {f.label}
                {f.highest && (
                  <span className="factor-rank__detail">
                    {f.highest} highest, {f.lowest} lowest
                  </span>
                )}
              </span>
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
