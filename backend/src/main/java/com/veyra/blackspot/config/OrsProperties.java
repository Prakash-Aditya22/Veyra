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
}
