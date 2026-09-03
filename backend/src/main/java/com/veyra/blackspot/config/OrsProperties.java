package com.veyra.blackspot.config;

import jakarta.annotation.PostConstruct;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Fails at startup rather than at the first request, so a missing key is a
 * boot error with a name on it instead of a 500 during a demo.
 */
@Component
@ConfigurationProperties(prefix = "ors")
public class OrsProperties {

    private String apiKey;
    private String baseUrl;
    private Alternatives alternatives = new Alternatives();

    public OrsProperties() {
    }

    public OrsProperties(String apiKey, String baseUrl) {
        this.apiKey = apiKey;
        this.baseUrl = baseUrl;
    }

    @PostConstruct
    public void validate() {
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalStateException(
                "ORS_API_KEY is not set. Copy backend/.env.example to backend/.env "
                + "and add a key from https://openrouteservice.org/dev/#/signup");
        }
    }

    public String getApiKey() {
        return apiKey;
    }

    public void setApiKey(String apiKey) {
        this.apiKey = apiKey;
    }

    public String getBaseUrl() {
        return baseUrl;
    }

    public void setBaseUrl(String baseUrl) {
        this.baseUrl = baseUrl;
    }

    public Alternatives getAlternatives() {
        return alternatives;
    }

    public void setAlternatives(Alternatives alternatives) {
        this.alternatives = alternatives;
    }

    /**
     * ORS alternative-route tuning. Measured live for Croydon -> Camden: at
     * share_factor 0.6 the "alternatives" overlap the fastest route's geometry
     * by ~46%, so fastest-vs-safest collapses into near-identical cards. At
     * 0.2 / 2.0 overlap drops to 2-7%. Kept configurable (not hardcoded) so it
     * can be retuned at demo time for whatever endpoints get shown, without a
     * rebuild.
     */
    public static class Alternatives {
        private int targetCount = 3;
        private double shareFactor = 0.2;
        private double weightFactor = 2.0;

        public int getTargetCount() {
            return targetCount;
        }

        public void setTargetCount(int targetCount) {
            this.targetCount = targetCount;
        }

        public double getShareFactor() {
            return shareFactor;
        }

        public void setShareFactor(double shareFactor) {
            this.shareFactor = shareFactor;
        }

        public double getWeightFactor() {
            return weightFactor;
        }

        public void setWeightFactor(double weightFactor) {
            this.weightFactor = weightFactor;
        }
    }
}
