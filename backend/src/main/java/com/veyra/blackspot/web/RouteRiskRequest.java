package com.veyra.blackspot.web;

import com.veyra.blackspot.domain.RouteRisk.Coord;

/** from/to are [lon, lat], matching GeoJSON. */
public record RouteRiskRequest(double[] from, double[] to, Integer minCrashes,
                               Double corridorMetres) {

    public Coord fromCoord() {
        return coord(from, "from");
    }

    public Coord toCoord() {
        return coord(to, "to");
    }

    private static Coord coord(double[] v, String name) {
        if (v == null || v.length != 2) {
            throw new IllegalArgumentException(name + " must be [lon, lat]");
        }
        if (v[0] < -180 || v[0] > 180 || v[1] < -90 || v[1] > 90) {
            throw new IllegalArgumentException(name + " is not a valid [lon, lat] pair");
        }
        return new Coord(v[0], v[1]);
    }
}
