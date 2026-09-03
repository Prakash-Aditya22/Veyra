import { ArrowLeft } from '@phosphor-icons/react';
import { tierOf, TIERS } from '../lib/risk.js';
import { num, score as fmtScore, coords, pct } from '../lib/format.js';
import RiskBadge from './RiskBadge.jsx';
import SpringBar from './motion/SpringBar.jsx';
import './DetailPanel.css';

/*
  Four blocks the fixture carried are gone rather than filled in.

    lastIncident  no date survives segment aggregation - the counts cover
                  2019 to 2021 as a whole
    landmarks     no gazetteer exists; `location` ("A23 km 0.5-1.0") is the
                  human-readable handle
    factors       only dataset-wide SHAP exists, never per-segment attribution
    hourly        replaced by the segment's real pctNight, one figure

  A placeholder in any of those would be worse than the gap: an invented "last
  incident" date is a claim about when someone was hurt.
*/

const SEVERITY_ROWS = [
  { key: 'fatal', word: 'Fatal', color: 'var(--risk-4)' },
  { key: 'serious', word: 'Serious', color: 'var(--risk-3)' },
  { key: 'slight', word: 'Slight', color: 'var(--risk-2)' },
];

export default function DetailPanel({ blackspot, onBack, rank }) {
  const b = blackspot;
  const tier = tierOf(b.score);
  const hasScore = b.score !== null;
  const hasNight = b.pctNight !== null && b.pctNight !== undefined;

  return (
    <div className="detail">
      <div className="detail__head">
        <button className="btn-tertiary detail__back" onClick={onBack}>
          <ArrowLeft size={15} weight="bold" />
          Back to results
        </button>
        <p className="label detail__id">
          Segment <span className="mono">{b.id}</span>
        </p>
      </div>

      <div className="detail__scroll">
        <div className="detail__block">
          <h2 className="detail__name">{b.name}</h2>
          <p className="detail__coords mono">{coords(b.lat, b.lng)}</p>
        </div>

        {/* The score. The tier word sits beside the number, always. */}
        <div className="detail__block detail__score-block">
          <p className="label">Blackspot risk score</p>
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
              {/*
                The model's own output, beside the band it was mapped into, so
                the reader sees the number and not only its bucket. It is a
                Poisson regression's estimate for 2022-23 built from 2019-21
                features - a forecast, not a tally, and a property of the
                stretch across all traffic rather than of one journey.
              */}
              <p className="detail__raw">
                <span className="mono">{b.blackspotScore.toFixed(2)}</span> expected
                killed-or-seriously-injured casualties over two years, across all
                traffic on this 500 m.
              </p>
              <p className="detail__score-note">
                The 0 to 100 band ranks this stretch against the segments that
                clear the six-crash evidence floor, not against every road in
                Great Britain.
              </p>
              {b.thinlyEvidenced && (
                <p className="detail__caveat">
                  Fewer than 6 recorded crashes. This score rests on too little
                  evidence to be ranked against the rest, and is shown because
                  insufficient data is not evidence of low risk.
                </p>
              )}
            </>
          ) : (
            <p className="detail__score-note">
              No score for this stretch. Insufficient data is not evidence of
              low risk.
            </p>
          )}
        </div>

        <div className="detail__block detail__stats">
          <div className="stat">
            <p className="label">Rank in view</p>
            <p className="stat__value mono">{rank ? `${rank}` : '--'}</p>
          </div>
          <div className="stat">
            <p className="label">Crashes</p>
            <p className="stat__value mono">{num(b.incidents)}</p>
          </div>
          <div className="stat">
            <p className="label">KSI</p>
            <p className="stat__value mono">{num(b.ksi)}</p>
          </div>
          <div className="stat">
            <p className="label">Fatal</p>
            <p className="stat__value mono">{num(b.fatal)}</p>
          </div>
        </div>

        {/* Severity split. Ramp colours, each with its word beside it. */}
        <div className="detail__block">
          <p className="label detail__block-title">Recorded severity, 2019 to 2021</p>
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
          <p className="detail__score-note detail__note--spaced">
            Crashes actually recorded in STATS19 on this stretch, by their worst
            casualty. These are counts, not estimates.
          </p>
        </div>

        <div className={`detail__block${hasNight ? '' : ' detail__block--last'}`}>
          <p className="label detail__block-title">Road</p>
          <dl className="kv">
            <div className="kv__row">
              <dt>Road</dt>
              <dd className="mono">{b.roadClass}</dd>
            </div>
            <div className="kv__row">
              <dt>Chainage</dt>
              <dd className="mono">
                {b.kmFrom?.toFixed(1)} to {b.kmTo?.toFixed(1)} km
              </dd>
            </div>
            <div className="kv__row">
              <dt>Posted limit</dt>
              {/* STATS19 records speed limits in mph, the UK's own unit. */}
              <dd className="mono">
                {b.speedLimit === null || b.speedLimit === undefined
                  ? '--'
                  : `${Math.round(b.speedLimit)} mph`}
              </dd>
            </div>
          </dl>
        </div>

        {/*
          One figure, not a histogram. pctNight is the share of this segment's
          own recorded crashes that happened at night; the export carries that
          proportion and no per-hour breakdown, so there is nothing to plot.
        */}
        {hasNight && (
          <div className="detail__block detail__block--last">
            <p className="label detail__block-title">Time of day</p>
            <p className="detail__figure">
              <span className="mono">{Math.round(b.pctNight * 100)}%</span> of crashes
              here were at night
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
