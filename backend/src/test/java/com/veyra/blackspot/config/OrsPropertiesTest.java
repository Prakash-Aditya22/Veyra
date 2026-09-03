package com.veyra.blackspot.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.context.ConfigDataApplicationContextInitializer;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;
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

    /**
     * Confirms ors.alternatives actually binds from application.yml, not just
     * that the field defaults happen to match it. A typo in a YAML key or a
     * getter name would silently fall back to the field defaults with every
     * other test still green -- this is the one that would catch it.
     */
    @Test
    void alternativesBindFromApplicationYml() {
        new ApplicationContextRunner()
            .withInitializer(new ConfigDataApplicationContextInitializer())
            .withUserConfiguration(TestConfig.class)
            .withPropertyValues("ors.api-key=test-key")
            .run(context -> {
                OrsProperties p = context.getBean(OrsProperties.class);
                assertThat(p.getAlternatives().getTargetCount()).isEqualTo(3);
                assertThat(p.getAlternatives().getShareFactor()).isEqualTo(0.2);
                assertThat(p.getAlternatives().getWeightFactor()).isEqualTo(2.0);
            });
    }

    @EnableConfigurationProperties(OrsProperties.class)
    static class TestConfig {
    }
}
