package com.veyra.blackspot.repo;

import java.util.List;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Exercises the real PostGIS functions against the loaded Supabase database.
 * Excluded from the default build (no Docker, no credentials in CI):
 *
 *   ./mvnw test -Dgroups=postgis
 */
@Tag("postgis")
@SpringBootTest
class SegmentRepositoryPostgisTest {

    @Autowired
    SegmentRepository repo;

    @Test
    void findsTheKnownWorstSegment() {
        var s = repo.findById("A23_run3_km0.5");
        assertThat(s).isPresent();
        assertThat(s.get().roadId()).isEqualTo("A23");
        assertThat(s.get().run()).isEqualTo(3);
        assertThat(s.get().nCrashes()).isEqualTo(60);
    }

    @Test
    void bboxOverCentralLondonReturnsSegments() {
        var rows = repo.findInBbox(BoundingBox.parse("-0.51,51.28,0.34,51.70"), 0, 6, 100);
        assertThat(rows).isNotEmpty().hasSizeLessThanOrEqualTo(100);
        assertThat(rows).isSortedAccordingTo(
            (a, b) -> Double.compare(b.blackspotScore(), a.blackspotScore()));
    }

    @Test
    void corridorAlongTheA23ReturnsHitsOrderedByPosition() {
        // A short LineString down the A23 through Brixton
        String wkt = "LINESTRING(-0.1160 51.4607, -0.1150 51.4650, -0.1140 51.4700)";
        List<SegmentRepository.CorridorHit> hits = repo.findAlongRoute(wkt, 100, 1);
        assertThat(hits).isNotEmpty();
        assertThat(hits).isSortedAccordingTo(
            (a, b) -> Double.compare(a.fraction(), b.fraction()));
        assertThat(hits).allSatisfy(h ->
            assertThat(h.fraction()).isBetween(0.0, 1.0));
    }

    @Test
    void minCrashesFilterExcludesThinlyEvidencedSegments() {
        String wkt = "LINESTRING(-0.1160 51.4607, -0.1140 51.4700)";
        var strict = repo.findAlongRoute(wkt, 200, 6);
        var loose = repo.findAlongRoute(wkt, 200, 1);
        assertThat(strict.size()).isLessThanOrEqualTo(loose.size());
        assertThat(strict).allSatisfy(h ->
            assertThat(h.segment().nCrashes()).isGreaterThanOrEqualTo(6));
    }
}
