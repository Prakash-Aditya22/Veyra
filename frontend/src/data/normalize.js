/*
  Contract records -> what the interface shows. Pure functions, no React, no fetching.

  Field names, units and empty-value rules come from data/v2/INTEGRATION_CONTRACT.md (ML
  branch). The interface never computes a risk value of its own: it shows the ML forecast,
  the documented rank, and the optional extensions exactly as delivered, and says "Not
  available" (with the documented reason) whenever a value is absent.
*/

import { period } from '../lib/format.js';

export const MIN_RATE_LENGTH_M = 250; // contract section 5: no rate below this length

/** Fields a base segment record must carry (contract 2.1, required for this UI). */
export const REQUIRED_FIELDS = [
  'rank', 'segment_id', 'location', 'road_id', 'road_class', 'lat', 'lon', 'blackspot_score',
  'n_crashes', 'n_ksi', 'n_fatal', 'n_ksi_casualties_adjusted', 'length_m', 'exposure_available',
  'data_sufficiency', 'single_event_flag',
];

export const ROAD_CLASS_LABELS = {
  M: 'Motorway',
  A: 'A road',
  B: 'B road',
  C: 'Classified unnumbered (C)',
  U: 'Unclassified',
  N: 'Not classified',
};

export const SUFFICIENCY_LABELS = {
  sufficient: '6 or more collisions',
  sparse: '1 to 5 collisions',
  none: 'No collisions',
};

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const orNull = (v) => (v === undefined || v === '' || (typeof v === 'number' && Number.isNaN(v)) ? null : v);

/** Problems with a raw record; an empty list means it satisfies what this UI needs. */
export function validateSegment(raw) {
  const problems = [];
  for (const f of REQUIRED_FIELDS) {
    if (raw[f] === undefined || raw[f] === null) problems.push(`missing ${f}`);
  }
  if (raw.rank !== undefined && !(Number.isInteger(raw.rank) && raw.rank >= 1)) problems.push('rank is not a positive integer');
  if (raw.blackspot_score !== undefined && !(isNum(raw.blackspot_score) && raw.blackspot_score >= 0)) {
    problems.push('blackspot_score is not a non-negative number');
  }
  if (!raw.exposure_available && raw.ksi_per_100m_vkm_eb != null) problems.push('rate present without exposure');
  return problems;
}

/** Release metadata (local bundle manifest.json) -> what the interface states about coverage. */
export function normalizeRelease(m) {
  const fy = m.score.forecast_period;
  const hy = m.score.history_period;
  return {
    version: m.release.score_version,
    contractVersion: m.release.contract_version,
    frozenSpec: m.release.frozen_spec_sha256,
    forecastYears: fy,
    historyYears: hy,
    forecastPeriod: m.release_constants?.forecast_period ?? `${fy[0]}-${fy[fy.length - 1]}`,
    historyPeriod: m.release_constants?.history_period ?? `${hy[0]}-${hy[hy.length - 1]}`,
    scoreUnits: m.score.units,
    geography: m.coverage.geography,
    notCovered: m.coverage.not_covered,
    nationalSegments: m.coverage.national_segments_scored,
    releaseRows: m.coverage.release_rows,
    nationalExpectedKsi: m.coverage.national_expected_ksi_total,
    nationalKsiCoveragePct: m.coverage.national_ksi_on_scored_network_pct,
    subset: {
      n: m.selection.n_segments,
      nTop: m.selection.n_top,
      nReference: m.selection.n_reference_cases,
      rule: m.selection.rule,
      notRepresentative: m.selection.not_representative,
      withLines: m.selection.with_line_geometry,
      midpointOnly: m.selection.midpoint_only,
    },
    // `last` marks the open-ended final group (compact label "18,276+")
    tiers: m.tiers.map((t, i, all) => ({ ...t, last: i === all.length - 1 })),
    tierRules: m.tier_rules ?? null,
    generatedUtc: m.generated_utc,
    outputsGeneratedUtc: m.release.outputs_generated_utc,
  };
}

/** Priority tier by national rank. Tiers come from the release (published boundaries). */
export function tierOf(rank, tiers) {
  return tiers.find((t) => rank >= t.min_rank && rank <= t.max_rank) ?? null;
}

/** One segment as the interface uses it. Every value is copied, never derived from the score. */
export function normalizeSegment(raw, release) {
  return {
    id: raw.segment_id,
    rank: raw.rank,
    location: raw.location,
    roadId: raw.road_id,
    roadClass: raw.road_class,
    roadNumber: orNull(raw.road_number),
    roadName: orNull(raw.road_name),
    formOfWay: orNull(raw.form_of_way),
    lengthM: raw.length_m,
    lat: raw.lat,
    lon: raw.lon,
    score: raw.blackspot_score,
    forecastPeriod: raw.forecast_period ?? release.forecastPeriod,
    historyPeriod: raw.history_period ?? release.historyPeriod,
    tier: tierOf(raw.rank, release.tiers),
    history: {
      collisions: raw.n_crashes,
      ksiCollisions: raw.n_ksi,
      fatalCollisions: raw.n_fatal,
      ksiCasualties: orNull(raw.n_ksi_casualties),
      ksiCasualtiesAdjusted: raw.n_ksi_casualties_adjusted,
      speedMax: orNull(raw.speed_max),
      shareNight: orNull(raw.pct_night),
      shareJunction: orNull(raw.pct_junction_v2),
      sufficiency: raw.data_sufficiency,
    },
    eb: {
      expectedKsi: orNull(raw.eb_expected_ksi),
      excessHistory: orNull(raw.eb_excess_ksi_history),
    },
    exposure: {
      available: raw.exposure_available === true,
      aadf: orNull(raw.aadf),
      shareCounted: orNull(raw.aadf_share_counted),
      rate: orNull(raw.ksi_per_100m_vkm_eb),
    },
    singleEvent: {
      flag: raw.single_event_flag === true,
      share: orNull(raw.single_event_share),
      maxCollisionKsi: orNull(raw.max_single_collision_ksi),
    },
    stratum: raw.demo_stratum ?? null,
    referenceCases: raw.reference_cases ?? [],
  };
}

/** Authoritative order is `rank` (the CSV score is rounded, so never re-rank by score). */
export function byRank(a, b) {
  return a.rank - b.rank;
}

/** The per-vehicle rate, or why it is not shown. Never substitutes zero or a proxy. */
export function rateView(seg) {
  const units = 'serious or fatal casualties per 100 million vehicle-km, 2023-25 (Empirical Bayes)';
  if (!seg.exposure.available || seg.exposure.rate === null) {
    return {
      available: false,
      reason: 'No DfT traffic count is matched to this road. Counts exist for motorways and A roads only, so no per-vehicle rate is shown.',
    };
  }
  if (seg.lengthM < MIN_RATE_LENGTH_M) {
    return {
      available: false,
      reason: `The segment is shorter than ${MIN_RATE_LENGTH_M} m, so its traffic denominator is too small for a reliable rate.`,
    };
  }
  return { available: true, value: seg.exposure.rate, aadf: seg.exposure.aadf, units };
}

/** Model attributions for one segment, or "not available". Never invents factors. */
export function explanationView(expl) {
  if (!expl || !Array.isArray(expl.top) || expl.top.length === 0) {
    return {
      available: false,
      headline: 'Explanation not available.',
      reason: 'The current data source provides no model attribution for this segment. Nothing is shown in its place.',
    };
  }
  return {
    available: true,
    base: isNum(expl.base) ? expl.base : null,
    groups: expl.groups ?? null,
    factors: [...expl.top]
      .sort((a, b) => a.contrib_rank - b.contrib_rank)
      .map((f) => ({
        feature: f.feature,
        label: f.label,
        group: f.group,
        display: f.display_value ?? null,
        factor: f.factor,
        raises: f.factor >= 1,
      })),
  };
}

/** Rank spread across refits. Shown as a range so neighbouring ranks are not over-read. */
export function stabilityView(stab) {
  if (!stab) return { available: false, reason: 'Rank stability not available for this segment.' };
  return {
    available: true,
    p05: stab.rank_p05,
    p95: stab.rank_p95,
    median: stab.rank_median,
    freqTop100: stab.freq_top100,
    freqTop1000: stab.freq_top1000,
    freqTop5pct: stab.freq_top5pct,
    stabilityClass: stab.stability_class,
    windowMin: stab.window_rank_min ?? null,
    windowMax: stab.window_rank_max ?? null,
  };
}

/**
 * Single-event concentration (base flag) and sensitivity to the largest collision (top 1,000).
 * Uses the one-at-a-time rank, the definition meant for per-segment wording.
 */
export function singleEventView(seg, se) {
  const sensitivity = se
    ? {
        available: true,
        forecastWithout: se.forecast_without_largest_collision,
        rankWithout: se.rank_without_largest_collision_one_at_a_time,
        removedAdjKsi: se.largest_collision_adj_ksi,
        direction:
          se.forecast_without_largest_collision > seg.score
            ? 'rises'
            : se.forecast_without_largest_collision < seg.score
              ? 'falls'
              : 'unchanged',
        leavesTop1000: seg.rank <= 1000 && se.rank_without_largest_collision_one_at_a_time > 1000,
      }
    : { available: false, reason: 'Computed for the national top 1,000 only.' };
  return {
    flagged: seg.singleEvent.flag,
    share: seg.singleEvent.share,
    maxCollisionKsi: seg.singleEvent.maxCollisionKsi,
    sensitivity,
  };
}

/** Data-coverage warnings for the record. Single events have their own wording (singleEventView). */
export function recordWarnings(seg) {
  const w = [];
  if (seg.history.sufficiency !== 'sufficient') {
    w.push({
      key: 'low-history',
      title: 'Low recent history',
      text:
        seg.history.collisions === 0
          ? `No recorded collisions in ${period(seg.historyPeriod)}. The forecast leans on road type, junctions and neighbouring roads.`
          : `Only ${seg.history.collisions} collision${seg.history.collisions === 1 ? '' : 's'} in ${period(seg.historyPeriod)}. The forecast leans on road type and neighbouring roads.`,
    });
  }
  return w;
}
