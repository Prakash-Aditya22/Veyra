package com.veyra.blackspot.domain;

/**
 * One 500 m stretch of road.
 *
 * blackspotScore is expected killed-or-seriously-injured casualties on this
 * stretch over two years, across all traffic. It is a model output, not a
 * per-journey probability, and must never be presented as one.
 *
 * There is deliberately no futureKsi field. See schema.sql.
 */
public record Segment(
    String segmentId,
    String roadId,
    int run,
    String location,
    double kmFrom,
    double kmTo,
    double lat,
    double lon,
    double blackspotScore,
    int rank,
    int nCrashes,
    int nKsi,
    int nFatal,
    Double ksiRate,
    Double crashesPerYear,
    Double speedMax,
    Double pctNight,
    Double pctJunction
) {
    /** The dataset stores fatal and KSI; serious is the difference. */
    public int nSerious() {
        return nKsi - nFatal;
    }

    /**
     * 86% of segments rest on fewer than six crashes and their scores are
     * noisy. Consumers filter or grey these out rather than ranking them
     * against well-evidenced segments.
     */
    public boolean thinlyEvidenced() {
        return nCrashes < 6;
    }
}
