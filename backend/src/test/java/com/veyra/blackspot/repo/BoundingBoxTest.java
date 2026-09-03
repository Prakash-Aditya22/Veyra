package com.veyra.blackspot.repo;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class BoundingBoxTest {

    @Test
    void parsesFourCommaSeparatedNumbers() {
        BoundingBox b = BoundingBox.parse("-0.51,51.28,0.34,51.70");
        assertThat(b.minLon()).isEqualTo(-0.51);
        assertThat(b.minLat()).isEqualTo(51.28);
        assertThat(b.maxLon()).isEqualTo(0.34);
        assertThat(b.maxLat()).isEqualTo(51.70);
    }

    @Test
    void rejectsWrongCardinality() {
        assertThatThrownBy(() -> BoundingBox.parse("-0.51,51.28,0.34"))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("bbox");
    }

    @Test
    void rejectsInvertedBounds() {
        assertThatThrownBy(() -> BoundingBox.parse("0.34,51.70,-0.51,51.28"))
            .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsNonNumeric() {
        assertThatThrownBy(() -> BoundingBox.parse("a,b,c,d"))
            .isInstanceOf(IllegalArgumentException.class);
    }
}
