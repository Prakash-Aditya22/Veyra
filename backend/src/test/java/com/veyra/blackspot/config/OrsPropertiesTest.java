package com.veyra.blackspot.config;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class OrsPropertiesTest {

    @Test
    void aBlankKeyFailsFastWithANamedError() {
        var p = new OrsProperties("", "https://api.openrouteservice.org");
        assertThatThrownBy(p::validate)
            .isInstanceOf(IllegalStateException.class)
            .hasMessageContaining("ORS_API_KEY");
    }

    @Test
    void aPresentKeyValidates() {
        var p = new OrsProperties("abc123", "https://api.openrouteservice.org");
        assertThatCode(p::validate).doesNotThrowAnyException();
    }
}
