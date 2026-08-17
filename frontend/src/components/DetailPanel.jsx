import { ArrowLeft } from '@phosphor-icons/react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import { tierOf, TIERS } from '../lib/risk.js';
import { num, score as fmtScore, shortDate, coords, pct, hourLabel } from '../lib/format.js';
import RiskBadge from './RiskBadge.jsx';
import ChartFrame, { ChartTooltip, AXIS, GRID } from './charts/ChartFrame.jsx';
import SpringBar from './motion/SpringBar.jsx';
import './DetailPanel.css';

const SEVERITY_ROWS = [
  { key: 'fatal', word: 'Fatal', color: 'var(--risk-4)' },
  { key: 'serious', word: 'Serious', color: 'var(--risk-3)' },
  { key: 'slight', word: 'Slight', color: 'var(--risk-2)' },
];

export default function DetailPanel({ blackspot, onBack, rank }) {
  const b = blackspot;
  const tier = tierOf(b.score);
  const hasScore = b.score !== null;

  const peak = b.hourly.reduce((best, h) => (h.count > best.count ? h : best), b.hourly[0]);

  return (
    <div className="detail">
      <div className="detail__head">
        <button className="btn-tertiary detail__back" onClick={onBack}>
          <ArrowLeft size={15} weight="bold" />
          Back to results
        </button>
        <p className="label detail__id">
          Cluster <span className="mono">{b.id}</span>
        </p>
      </div>

      <div className="detail__scroll">
        <div className="detail__block">
          <h2 className="detail__name">{b.name}</h2>
          <p className="detail__coords mono">{coords(b.lat, b.lng)}</p>
        </div>

        {/* Composite score. The tier word sits beside the number, always. */}
        <div className="detail__block detail__score-block">
          <p className="label">Composite danger score</p>
          {hasScore ? (
            <>
              <div className="detail__score-row">
                {/*
                  The figure itself stays Bone White. The ramp is scoped to
                  markers, badges, table cells and chart series; a headline
                  numeral is not one of those. Oxblood on Panel Graphite also
                  lands near 1.7:1, below the large-text contrast floor. Tier is
                  carried by the badge and the ramp strip beneath.
                */}
                <span className="detail__score mono">{fmtScore(b.score)}</span>
                <RiskBadge score={b.score} size="lg" />
              </div>
              <div className="detail__ramp" role="img" aria-label={`Tier ${tier.word}`}>
                {TIERS.map((t) => (
                  <span
                    key={t.key}
                    className={`detail__ramp-seg${t.key === tier.key ? ' detail__ramp-seg--on' : ''}`}
                    style={{ background: t.color }}
                  />
                ))}
              </div>
              <p className="detail__score-note">
                Frequency, severity weighting and recency, combined on a fixed 0 to 100
                scale. Historically high risk, not a forecast.
              </p>
            </>
          ) : (
            <p className="detail__score-note">
              Under the 12-record minimum for scoring. Insufficient data is not
              evidence of low risk.
            </p>
          )}
        </div>

        <div className="detail__block detail__stats">
          <div className="stat">
            <p className="label">Rank</p>
            <p className="stat__value mono">{rank ? `${rank}` : '--'}</p>
          </div>
          <div className="stat">
            <p className="label">Incidents</p>
            <p className="stat__value mono">{num(b.incidents)}</p>
          </div>
          <div className="stat">
            <p className="label">Fatal</p>
            <p className="stat__value mono">{num(b.fatal)}</p>
          </div>
          <div className="stat">
            <p className="label">Last incident</p>
            <p className="stat__value stat__value--sm mono">{shortDate(b.lastIncident)}</p>
          </div>
        </div>

        {/* Severity split. Ramp colours, each with its word beside it. */}
        <div className="detail__block">
          <p className="label detail__block-title">Severity split</p>
          <ul className="severity">
            {SEVERITY_ROWS.map((row, i) => (
              <li key={row.key} className="severity__row">
                <span
                  className="severity__swatch"
                  style={{ background: row.color }}
                  aria-hidden="true"
                />
                <span className="severity__word">{row.word}</span>
                <span className="severity__bar" aria-hidden="true">
                  <SpringBar
                    className="severity__fill"
                    percent={Number(pct(b[row.key], b.incidents))}
                    index={i}
                    style={{ background: row.color }}
                  />
                </span>
                <span className="severity__count mono">{num(b[row.key])}</span>
                <span className="severity__pct mono">{pct(b[row.key], b.incidents)}%</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Contributing factors. Weights come from the model, not from the UI. */}
        {b.factors.length > 0 && (
          <div className="detail__block">
            <p className="label detail__block-title">Contributing factors</p>
            <ul className="factors">
              {b.factors.map((f, i) => (
                <li key={f.label} className="factors__row">
                  <span className="factors__label">{f.label}</span>
                  <span className="factors__track" aria-hidden="true">
                    <SpringBar className="factors__fill" percent={f.weight} index={i} />
                  </span>
                  <span className="factors__weight mono">{f.weight}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="detail__block">
          <ChartFrame
            title="Incidents by hour"
            meta={`${b.incidents} records inside this cluster, ${b.id}. Peak at ${hourLabel(peak.hour)}.`}
          >
            <div className="detail__chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={b.hourly} margin={{ top: 4, right: 0, bottom: 0, left: -22 }}>
                  <CartesianGrid {...GRID} />
                  <XAxis
                    {...AXIS}
                    dataKey="hour"
                    interval={3}
                    tickFormatter={(h) => String(h).padStart(2, '0')}
                  />
                  <YAxis {...AXIS} width={38} allowDecimals={false} />
                  <Tooltip
                    cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
                    content={(p) => (
                      <ChartTooltip
                        {...p}
                        label={hourLabel(p.label)}
                        unit="incidents in this cluster"
                      />
                    )}
                  />
                  <Bar
                    dataKey="count"
                    name="Incidents"
                    radius={[2, 2, 0, 0]}
                    isAnimationActive={false}
                  >
                    {b.hourly.map((h) => (
                      <Cell
                        key={h.hour}
                        fill="#0F766E"
                        fillOpacity={h.hour === peak.hour ? 1 : 0.55}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartFrame>
        </div>

        <div className="detail__block">
          <p className="label detail__block-title">Road</p>
          <dl className="kv">
            <div className="kv__row">
              <dt>Class</dt>
              <dd className="mono">{b.roadClass}</dd>
            </div>
            <div className="kv__row">
              <dt>Type</dt>
              <dd>{b.roadType}</dd>
            </div>
            <div className="kv__row">
              <dt>Posted limit</dt>
              <dd className="mono">{b.speedLimit} km/h</dd>
            </div>
          </dl>
        </div>

        <div className="detail__block detail__block--last">
          <p className="label detail__block-title">Nearest landmarks</p>
          <ul className="landmarks">
            {b.landmarks.map((l) => (
              <li key={l} className="landmarks__item">
                {l}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
