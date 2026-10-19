/*
  Test entry: renders real UI components to HTML on the server (react-dom/server), so tests can
  check what a user would read, and the accessibility semantics, without a browser.
  Built by tests/render.test.js with Vite.
*/
import { renderToStaticMarkup } from 'react-dom/server';
import { Explanation, RateBlock, StabilityBlock, singleEventText } from '../src/components/DetailPanel.jsx';
import FilterRail from '../src/components/FilterRail.jsx';
import PriorityBadge from '../src/components/PriorityBadge.jsx';
import ResultsPanel from '../src/components/ResultsPanel.jsx';
import { explanationView, normalizeRelease, normalizeSegment, rateView, singleEventView, stabilityView } from '../src/data/normalize.js';
import { EMPTY_FILTERS, filterOptions } from '../src/lib/filters.js';

export function render({ manifest, raw, explanation, stability, singleEvent }) {
  const release = normalizeRelease(manifest);
  const seg = normalizeSegment(raw, release);
  const se = singleEventView(seg, singleEvent);
  return {
    explanation: renderToStaticMarkup(<Explanation explanation={explanationView(explanation)} />),
    rate: renderToStaticMarkup(<RateBlock rate={rateView(seg)} />),
    stability: renderToStaticMarkup(
      <StabilityBlock seg={seg} stability={stabilityView(stability)} singleEvent={se} national={release.nationalSegments} />,
    ),
    badge: renderToStaticMarkup(<PriorityBadge segment={seg} />),
    badgeSmall: renderToStaticMarkup(<PriorityBadge segment={seg} size="sm" showRank={false} />),
    singleEventText: singleEventText(seg, se),
  };
}

export function renderLists({ manifest, segments, filters = EMPTY_FILTERS }) {
  const release = normalizeRelease(manifest);
  const segs = segments.map((r) => normalizeSegment(r, release)).map((s) => ({ ...s, ext: { hasExplanation: true } }));
  const noop = () => {};
  return {
    rail: renderToStaticMarkup(
      <FilterRail
        filters={filters}
        onChange={noop}
        options={filterOptions(segs, release.tiers)}
        tiers={release.tiers}
        resultCount={segs.length}
        totalCount={segs.length}
      />,
    ),
    results: renderToStaticMarkup(
      <ResultsPanel results={segs} selected={null} onSelect={noop} sortKey="rank" onSortChange={noop} loading={false} onResetFilters={noop} forecastPeriod="2026-2027" />,
    ),
  };
}
