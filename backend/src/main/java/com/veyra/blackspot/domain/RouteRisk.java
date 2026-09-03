package com.veyra.blackspot.domain;

import java.util.List;

/** Records exchanged by the routing and route-risk layers. */
public final class RouteRisk {

    private RouteRisk() {
    }

    /** Longitude first, matching GeoJSON and ORS. */
    public record Coord(double lon, double lat) {
    }

    /** A route as the routing provider returned it, before any scoring. */
    public record RawRoute(List<Coord> geometry, double distanceMetres, double durationSeconds) {
    }

    public record GeocodeCandidate(String label, double lon, double lat) {
    }

    /** A blackspot on a route, with how far along it sits. */
    public record BlackspotOnRoute(
        String segmentId, String location, double lat, double lon,
        double blackspotScore, int nCrashes, int nKsi, int nFatal,
        Double speedMax, double metresAlongRoute, boolean thinlyEvidenced) {
    }

    /**
     * expectedKsi is expected killed-or-seriously-injured casualties on this
     * corridor over two years, ACROSS ALL TRAFFIC. It is not a per-journey
     * risk and must never be presented as one.
     */
    public record ScoredRoute(
        int index, String label,
        double distanceMetres, double durationSeconds,
        List<Coord> geometry,
        double expectedKsi, int blackspotCount, String worstSegmentId,
        List<BlackspotOnRoute> blackspots) {
    }

    public record RouteRiskResponse(List<ScoredRoute> routes, String coverageWarning) {
    }
}
