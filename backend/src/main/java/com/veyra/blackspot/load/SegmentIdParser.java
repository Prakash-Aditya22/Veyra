package com.veyra.blackspot.load;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Segment ids encode road, stretch, and chainage: "A23_run3_km0.5".
 *
 * The exported CSV omits `run` as its own column, but it is not cosmetic —
 * one road number can cover geographically separate stretches (crashes tagged
 * A503 appear 543 km apart, though the A503 is a 10 km London road). Drawing a
 * road as one polyline requires it, so it is recovered here.
 *
 * A malformed id throws rather than defaulting run to 0, which would silently
 * merge distinct stretches into one line across open country.
 */
public final class SegmentIdParser {

    // Road id is greedy-free up to the literal "_run": it may contain
    // parentheses, as A(M) roads do.
    private static final Pattern ID = Pattern.compile("^(.+)_run(\\d+)_km([0-9]+(?:\\.[0-9]+)?)$");

    private SegmentIdParser() {
    }

    public record ParsedId(String roadId, int run, double kmFrom) {
    }

    public static ParsedId parse(String segmentId) {
        if (segmentId == null || segmentId.isBlank()) {
            throw new IllegalArgumentException("segment_id is null or blank");
        }
        Matcher m = ID.matcher(segmentId);
        if (!m.matches()) {
            throw new IllegalArgumentException(
                "segment_id does not match <road>_run<n>_km<d>: " + segmentId);
        }
        return new ParsedId(m.group(1), Integer.parseInt(m.group(2)), Double.parseDouble(m.group(3)));
    }
}
