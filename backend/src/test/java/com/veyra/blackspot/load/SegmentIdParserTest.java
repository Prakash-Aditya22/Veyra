package com.veyra.blackspot.load;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SegmentIdParserTest {

    @Test
    void parsesRoadRunAndKilometre() {
        var p = SegmentIdParser.parse("A23_run3_km0.5");
        assertThat(p.roadId()).isEqualTo("A23");
        assertThat(p.run()).isEqualTo(3);
        assertThat(p.kmFrom()).isEqualTo(0.5);
    }

    @Test
    void parsesRunZero() {
        assertThat(SegmentIdParser.parse("A3220_run0_km6.0").run()).isZero();
    }

    @Test
    void parsesMotorwayAndBRoadNumbers() {
        assertThat(SegmentIdParser.parse("M25_run2_km60.0").roadId()).isEqualTo("M25");
        assertThat(SegmentIdParser.parse("B1234_run0_km1.5").roadId()).isEqualTo("B1234");
    }

    @Test
    void parsesAMotorwayClassContainingParentheses() {
        // class 2 renders as "A(M)", e.g. A1(M)
        assertThat(SegmentIdParser.parse("A(M)1_run0_km2.0").roadId()).isEqualTo("A(M)1");
    }

    @Test
    void parsesLargeKilometreValues() {
        assertThat(SegmentIdParser.parse("A1_run0_km128.5").kmFrom()).isEqualTo(128.5);
    }

    @Test
    void rejectsMalformedIdRatherThanDefaultingRunToZero() {
        assertThatThrownBy(() -> SegmentIdParser.parse("A23_km0.5"))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("A23_km0.5");
    }

    @Test
    void rejectsNullAndBlank() {
        assertThatThrownBy(() -> SegmentIdParser.parse(null))
            .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> SegmentIdParser.parse("  "))
            .isInstanceOf(IllegalArgumentException.class);
    }
}
