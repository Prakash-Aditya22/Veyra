import { useEffect, useRef } from 'react';
import { ArrowLeft, Warning } from '@phosphor-icons/react';
import { ROAD_CLASS_LABELS, rateView, recordWarnings } from '../data/normalize.js';
import { useData, useSegmentDetail } from '../data/DataContext.jsx';
import { coords, fixed, int, ksi, metres, period, rank as fmtRank, share } from '../lib/format.js';
import PriorityBadge from './PriorityBadge.jsx';
import SpringBar from './motion/SpringBar.jsx';
import './DetailPanel.css';

function Row({ term, children, mono = true }) {
  return (
    <div className="kv__row">
      <dt>{term}</dt>
      <dd className={mono ? 'mono' : undefined}>{children}</dd>
    </div>
  );
}

function Unavailable({ children, headline = 'Not available.' }) {
  return (
    <p className="detail__na">
      <span className="detail__na-word">{headline}</span> {children}
    </p>
  );
}

export function StabilityBlock({ seg, stability, singleEvent, national }) {
  return (
    <div className="detail__block">
      <p className="label detail__block-title">Rank and its stability</p>
      <dl className="kv">
        <Row term="National rank">
          {fmtRank(seg.rank)} of {int(national)}
        </Row>
        {stability.available ? (
          <>
            <Row term="Rank range across 20 model refits (5th–95th percentile)">
              {fmtRank(stability.p05)} – {fmtRank(stability.p95)}
            </Row>
            <Row term="Refits keeping it in the national top 1,000">{share(stability.freqTop1000)}</Row>
            <Row term="Refits keeping it in the top 100">{share(stability.freqTop100)}</Row>
            {stability.windowMin !== null && (
              <Row term="Rank range across history-window choices">
                {fmtRank(stability.windowMin)} – {fmtRank(stability.windowMax)}
              </Row>
            )}
            <Row term="Stability class" mono={false}>
              {stability.stabilityClass}
            </Row>
          </>
        ) : (
          <div className="kv__row">
            <dd>
              <Unavailable>{stability.reason}</Unavailable>
            </dd>
          </div>
        )}
        {singleEvent.sensitivity.available && (
          <Row term="Without its largest 2023–25 collision (only this segment changed)">
            {fmtRank(singleEvent.sensitivity.rankWithout)}, forecast {ksi(singleEvent.sensitivity.forecastWithout)}
          </Row>
        )}
      </dl>
      <p className="detail__note">
        Spread from refitting the model on resampled data; not a confidence interval for future casualties.
        Neighbouring ranks are not meaningfully different: compare tiers or ranges, not positions.
        {!singleEvent.sensitivity.available && ` ${singleEvent.sensitivity.reason.replace('Computed', 'One-collision sensitivity was computed')}`}
      </p>
    </div>
  );
}

export function singleEventText(seg, se) {
  const s = se.sensitivity;
  if (se.flagged) {
    const head = `One collision supplied ${share(se.share)} of this segment's serious or fatal history (${ksi(se.maxCollisionKsi, 1)} of ${ksi(seg.history.ksiCasualtiesAdjusted, 1)} adjusted casualties), so its history, excess and per-vehicle figures describe that incident more than the road's design.`;
    if (!s.available) return head;
    if (s.direction !== 'falls') {
      return `${head} Removing that collision does not lower the model's forecast (${ksi(s.forecastWithout)} instead of ${ksi(seg.score)}; rank ${fmtRank(s.rankWithout)} with only this segment changed). The segment's priority does not require the event, but its forecast is sensitive to it: the model treats an isolated spike as partly noise.`;
    }
    return `${head} Without that collision the forecast would be ${ksi(s.forecastWithout)} (rank ${fmtRank(s.rankWithout)}).`;
  }
  if (s.available && s.leavesTop1000) {
    return `Sensitive to one collision: without its largest 2023–25 collision this segment would rank ${fmtRank(s.rankWithout)} (forecast ${ksi(s.forecastWithout)}), outside the top 1,000.`;
  }
  return null;
}

export function Explanation({ explanation }) {
  if (!explanation.available) {
    return <Unavailable headline={explanation.headline}>{explanation.reason}</Unavailable>;
  }
  const max = Math.max(...explanation.factors.map((f) => Math.abs(Math.log(f.factor))), 0.01);
  return (
    <>
      {explanation.base !== null && (
        <dl className="kv">
          <Row term="Model baseline (a typical segment, not the average forecast)">{ksi(explanation.base, 4)}</Row>
        </dl>
      )}
      <ul className="factors" aria-label="Largest model attributions">
        {explanation.factors.map((f, i) => (
          <li key={f.feature} className="factors__row factors__row--expl">
            <span className="factors__label">
              {f.label}
              {f.display !== null && <span className="mono factors__value"> ({f.display})</span>}
            </span>
            <span className="factors__track" aria-hidden="true">
              <SpringBar
                className={`factors__fill${f.raises ? '' : ' factors__fill--down'}`}
                percent={Math.round((100 * Math.abs(Math.log(f.factor))) / max)}
                index={i}
              />
            </span>
            <span className="factors__weight mono" title={f.raises ? 'raises the forecast' : 'lowers the forecast'}>
              ×{fixed(f.factor, 2)}
              <span className="sr-only">{f.raises ? ' raises' : ' lowers'} the forecast</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="detail__note">
        Top 5 of 45 TreeSHAP attributions of the production model that produced the forecast. Factors multiply the
        baseline to give the forecast. They show what the model associates with a high casualty count, not causes,
        and not what would reduce casualties if changed.
      </p>
    </>
  );
}

export function RateBlock({ rate }) {
  if (!rate.available) return <Unavailable>{rate.reason}</Unavailable>;
  return (
    <>
      <dl className="kv">
        <Row term="Serious or fatal casualties per 100 million vehicle-km, 2023–25">{fixed(rate.value, 1)}</Row>
        <Row term="Average daily traffic (DfT count point)">{int(rate.aadf)}</Row>
      </dl>
      <p className="detail__note">
        Per-vehicle risk answers a different question from the forecast burden above: a busy road can carry a high burden
        with an ordinary rate.
      </p>
    </>
  );
}

export default function DetailPanel({ segment: seg, onBack, focusOnOpen = false }) {
  const data = useData();
  const headingRef = useRef(null);
  // Opened from the list or map by the user: move focus to the heading so the panel is read next.
  useEffect(() => {
    if (focusOnOpen) headingRef.current?.focus();
  }, [focusOnOpen, seg.id]);
  const detail = useSegmentDetail(seg);
  const rate = rateView(seg);
  const warnings = recordWarnings(seg);
  const ready = detail.status === 'ready';
  const seText = ready ? singleEventText(seg, detail.singleEvent) : null;

  return (
    <div className="detail">
      <div className="detail__head">
        <button className="btn-tertiary detail__back" onClick={onBack} aria-label="Back to the segment list">
          <ArrowLeft size={15} weight="bold" aria-hidden="true" />
          Back to results
        </button>
        <p className="label detail__id">
          Segment <span className="mono">{seg.id}</span>
        </p>
      </div>

      <div className="detail__scroll">
        <div className="detail__block">
          <h2 className="detail__name" ref={headingRef} tabIndex={-1}>
            {seg.location}
          </h2>
          <p className="detail__sub">
            {ROAD_CLASS_LABELS[seg.roadClass] ?? seg.roadClass}
            {seg.formOfWay ? ` · ${seg.formOfWay}` : ''} · {metres(seg.lengthM)}
          </p>
          <p className="detail__coords mono">{coords(seg.lat, seg.lon)}</p>
          {seg.stratum === 'reference_case' && (
            <p className="detail__note">Reference case below the national top 1,000, included in this demo as a test case.</p>
          )}
        </div>

        <div className="detail__block detail__score-block">
          <p className="label">ML forecast, {period(seg.forecastPeriod)}</p>
          <div className="detail__score-row">
            <span className="detail__score mono">{ksi(seg.score)}</span>
            <PriorityBadge segment={seg} size="lg" />
          </div>
          <p className="detail__score-note">
            Expected killed-or-seriously-injured casualties on this segment over {seg.forecastPeriod.replace('-', ' and ')} combined
            (DfT severity-adjusted). An expected count from the ML forecast: not the probability of a collision and not a
            per-vehicle risk.
          </p>
        </div>

        {(warnings.length > 0 || seText) && (
          <div className="detail__block detail__warnings" role="note" aria-label="Warnings for this segment">
            {warnings.map((w) => (
              <p key={w.key} className="detail__warn">
                <Warning size={14} weight="bold" aria-hidden="true" />
                <span>
                  <strong>{w.title}.</strong> {w.text}
                </span>
              </p>
            ))}
            {seText && (
              <p className="detail__warn">
                <Warning size={14} weight="bold" aria-hidden="true" />
                <span>
                  {seg.singleEvent.flag && <strong>Single-event concentration. </strong>}
                  {seText}
                </span>
              </p>
            )}
          </div>
        )}

        {ready ? (
          <StabilityBlock seg={seg} stability={detail.stability} singleEvent={detail.singleEvent} national={data.release.nationalSegments} />
        ) : (
          <div className="detail__block">
            <p className="label">Loading rank stability and explanation</p>
          </div>
        )}

        <div className="detail__block">
          <p className="label detail__block-title">Recorded history, {period(seg.historyPeriod)}</p>
          <dl className="kv">
            <Row term="Collisions (all severities)">{int(seg.history.collisions)}</Row>
            <Row term="Serious or fatal collisions">{int(seg.history.ksiCollisions)}</Row>
            <Row term="Fatal collisions">{int(seg.history.fatalCollisions)}</Row>
            <Row term="Serious or fatal casualties (DfT-adjusted)">{ksi(seg.history.ksiCasualtiesAdjusted, 1)}</Row>
            <Row term="Share at junctions">{share(seg.history.shareJunction)}</Row>
            <Row term="Share at night (22:00–05:59)">{share(seg.history.shareNight)}</Row>
            <Row term="Highest speed limit at these collisions">
              {seg.history.speedMax === null ? 'Not available' : `${seg.history.speedMax} mph`}
            </Row>
            <Row term="Above or below similar roads (Empirical Bayes excess)">{ksi(seg.eb.excessHistory)}</Row>
          </dl>
          <p className="detail__note">
            Counts of police-reported injury collisions (DfT STATS19) snapped to this segment. The excess compares the
            segment with roads of the same class, layout and junctions; it is a screening signal, not a cause.
          </p>
        </div>

        <div className="detail__block">
          <p className="label detail__block-title">Why the model ranks it here</p>
          {ready ? <Explanation explanation={detail.explanation} /> : <p className="detail__note">Loading…</p>}
        </div>

        <div className="detail__block detail__block--last">
          <p className="label detail__block-title">Per-vehicle rate (a separate measure)</p>
          <RateBlock rate={rate} />
        </div>
      </div>
    </div>
  );
}
