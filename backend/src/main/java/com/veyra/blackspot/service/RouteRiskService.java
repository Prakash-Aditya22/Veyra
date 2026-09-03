package com.veyra.blackspot.service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.StringJoiner;

import com.veyra.blackspot.domain.RouteRisk.BlackspotOnRoute;
import com.veyra.blackspot.domain.RouteRisk.Coord;
import com.veyra.blackspot.domain.RouteRisk.RawRoute;
import com.veyra.blackspot.domain.RouteRisk.RouteRiskResponse;
import com.veyra.blackspot.domain.RouteRisk.ScoredRoute;
import com.veyra.blackspot.repo.SegmentRepository;
import com.veyra.blackspot.repo.SegmentRepository.CorridorHit;
import com.veyra.blackspot.routing.RoutingClient;
import org.springframework.stereotype.Service;

/**
 * Route -> corridor match -> aggregate.
 *
 * expectedKsi is the sum of the matched segments' scores: expected
 * killed-or-seriously-injured casualties on that corridor over two years,
 * across all traffic. It is NOT a per-journey risk. The API returns the raw
 * number and the UI is responsible for saying so.
 */
@Service
public class RouteRiskService {

    private static final int ALTERNATIVES = 3;

    /** Generous bounds for Great Britain, the extent of the STATS19 data. */
    private static final double GB_MIN_LON = -8.7, GB_MAX_LON = 2.0;
    private static final double GB_MIN_LAT = 49.8, GB_MAX_LAT = 61.0;

    private final RoutingClient routing;
    private final SegmentRepository repo;

    public RouteRiskService(RoutingClient routing, SegmentRepository repo) {
        this.routing = routing;
        this.repo = repo;
    }

    public RouteRiskResponse assess(Coord from, Coord to, int minCrashes, double corridorMetres) {
        List<RawRoute> raw = routing.route(from, to, ALTERNATIVES);

        List<ScoredRoute> scored = new ArrayList<>();
        for (int i = 0; i < raw.size(); i++) {
            scored.add(score(i, raw.get(i), minCrashes, corridorMetres));
        }
        scored = label(scored);

        boolean covered = raw.stream().flatMap(r -> r.geometry().stream()).anyMatch(
            c -> c.lon() >= GB_MIN_LON && c.lon() <= GB_MAX_LON
              && c.lat() >= GB_MIN_LAT && c.lat() <= GB_MAX_LAT);

        return new RouteRiskResponse(scored, covered ? null
            : "Blackspot data covers Great Britain only; no coverage for this route.");
    }

    private ScoredRoute score(int index, RawRoute r, int minCrashes, double corridorMetres) {
        List<CorridorHit> hits = repo.findAlongRoute(toWkt(r.geometry()), corridorMetres, minCrashes);
        // The real query already orders by frac; sorting here too makes that
        // guarantee the service's own, not an accident of the SQL.
        hits = hits.stream()
            .sorted(Comparator.comparingDouble(CorridorHit::fraction))
            .toList();

        List<BlackspotOnRoute> blackspots = new ArrayList<>();
        double expectedKsi = 0;
        String worst = null;
        double worstScore = -1;

        for (CorridorHit h : hits) {
            var s = h.segment();
            expectedKsi += s.blackspotScore();
            if (s.blackspotScore() > worstScore) {
                worstScore = s.blackspotScore();
                worst = s.segmentId();
            }
            blackspots.add(new BlackspotOnRoute(
                s.segmentId(), s.location(), s.lat(), s.lon(),
                s.blackspotScore(), s.nCrashes(), s.nKsi(), s.nFatal(), s.speedMax(),
                h.fraction() * r.distanceMetres(), s.thinlyEvidenced()));
        }

        return new ScoredRoute(index, "Alternative", r.distanceMetres(), r.durationSeconds(),
            r.geometry(), round(expectedKsi), blackspots.size(), worst, blackspots);
    }

    /**
     * Labels are assigned across the set, not per route: the quickest is
     * "Fastest", the least risky is "Safest", and one route can be both.
     */
    private List<ScoredRoute> label(List<ScoredRoute> routes) {
        if (routes.isEmpty()) {
            return routes;
        }
        int fastest = 0, safest = 0;
        for (int i = 1; i < routes.size(); i++) {
            if (routes.get(i).durationSeconds() < routes.get(fastest).durationSeconds()) {
                fastest = i;
            }
            if (routes.get(i).expectedKsi() < routes.get(safest).expectedKsi()) {
                safest = i;
            }
        }
        List<ScoredRoute> out = new ArrayList<>(routes.size());
        for (int i = 0; i < routes.size(); i++) {
            String label = i == fastest && i == safest ? "Fastest and safest"
                         : i == fastest ? "Fastest"
                         : i == safest ? "Safest"
                         : "Alternative";
            var r = routes.get(i);
            out.add(new ScoredRoute(r.index(), label, r.distanceMetres(), r.durationSeconds(),
                r.geometry(), r.expectedKsi(), r.blackspotCount(), r.worstSegmentId(),
                r.blackspots()));
        }
        return out;
    }

    /** PostGIS WKT. Longitude first, matching the SRID 4326 axis order used here. */
    static String toWkt(List<Coord> line) {
        StringJoiner j = new StringJoiner(",", "LINESTRING(", ")");
        for (Coord c : line) {
            j.add(String.format(Locale.ROOT, "%.6f %.6f", c.lon(), c.lat()));
        }
        return j.toString();
    }

    private static double round(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
