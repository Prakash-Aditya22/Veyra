package com.veyra.blackspot.domain;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SegmentTest {

    private static Segment segment(int nCrashes, int nKsi, int nFatal) {
        return new Segment("A23_run3_km0.5", "A23", 3, "A23 km 0.5-1.0 (seg 3)",
            0.5, 1.0, 51.4607, -0.1160, 9.67, 1,
            nCrashes, nKsi, nFatal, 0.167, 20.0, 30.0, 0.233, 0.7);
    }

    @Test
    void seriousIsKsiMinusFatal() {
        assertThat(segment(60, 10, 2).nSerious()).isEqualTo(8);
    }

    @Test
    void seriousIsZeroWhenEveryKsiWasFatal() {
        assertThat(segment(60, 3, 3).nSerious()).isZero();
    }

    @Test
    void thinlyEvidencedBelowSixCrashes() {
        // 86% of segments rest on fewer than 6 crashes; their scores are noise.
        assertThat(segment(5, 1, 0).thinlyEvidenced()).isTrue();
        assertThat(segment(6, 1, 0).thinlyEvidenced()).isFalse();
    }
}
