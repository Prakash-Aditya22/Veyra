package com.veyra.blackspot.routing;

import java.net.URI;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.veyra.blackspot.config.OrsProperties;
import com.veyra.blackspot.domain.RouteRisk.Coord;
import com.veyra.blackspot.domain.RouteRisk.GeocodeCandidate;
import com.veyra.blackspot.domain.RouteRisk.RawRoute;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

/**
 * OpenRouteService. Called server-side only, so the key never reaches a browser.
 *
 * ORS returns alternatives only when the request carries no via points, which
 * is why this client takes exactly two coordinates.
 */
@Component
public class OrsRoutingClient implements RoutingClient {

    private final RestTemplate http;
    private final OrsProperties props;

    public OrsRoutingClient(OrsProperties props, RestTemplateBuilder builder) {
        this.props = props;
        // ORS is a synchronous dependency of an MVC request thread. Without
        // timeouts a hung upstream blocks that thread indefinitely and the
        // servlet thread pool drains, taking unrelated endpoints down with it.
        this.http = builder
            .connectTimeout(Duration.ofSeconds(5))
            .readTimeout(Duration.ofSeconds(20))
            .build();
    }

    @Override
    public List<RawRoute> route(Coord from, Coord to, int alternatives) {
        String url = props.getBaseUrl() + "/v2/directions/driving-car/geojson";

        OrsProperties.Alternatives alt = props.getAlternatives();
        Map<String, Object> body = alternatives > 1
            ? Map.of("coordinates", List.of(List.of(from.lon(), from.lat()),
                                            List.of(to.lon(), to.lat())),
                     "alternative_routes", Map.of("target_count", alt.getTargetCount(),
                                                  "share_factor", alt.getShareFactor(),
                                                  "weight_factor", alt.getWeightFactor()))
            : Map.of("coordinates", List.of(List.of(from.lon(), from.lat()),
                                            List.of(to.lon(), to.lat())));

        HttpHeaders h = new HttpHeaders();
        h.set(HttpHeaders.AUTHORIZATION, props.getApiKey());
        h.setContentType(MediaType.APPLICATION_JSON);

        JsonNode root;
        try {
            root = http.postForObject(URI.create(url), new HttpEntity<>(body, h), JsonNode.class);
        } catch (HttpStatusCodeException e) {
            // ORS reports "no route" as an HTTP error with a structured body,
            // not as a 200 with zero features. Verified live: an unroutable
            // coordinate returns 404 with error.code 2010.
            Integer code = orsErrorCode(e);
            if (code != null && (code == 2010 || code == 2009)) {
                throw new RoutingException(RoutingException.Kind.NO_ROUTE,
                    "no drivable route between those points", e);
            }
            throw new RoutingException(RoutingException.Kind.UNAVAILABLE,
                "routing service unavailable", e);
        } catch (RestClientException e) {
            throw new RoutingException(RoutingException.Kind.UNAVAILABLE,
                "routing service unavailable", e);
        }
        if (root == null || !root.has("features") || root.get("features").isEmpty()) {
            // Belt-and-braces: ORS has not been observed to return this shape
            // for "no route", but it costs nothing to also treat it as one.
            throw new RoutingException(RoutingException.Kind.NO_ROUTE,
                "no drivable route between those points");
        }

        List<RawRoute> out = new ArrayList<>();
        for (JsonNode f : root.get("features")) {
            JsonNode summary = f.path("properties").path("summary");
            List<Coord> line = new ArrayList<>();
            for (JsonNode c : f.path("geometry").path("coordinates")) {
                if (!c.isArray() || c.size() < 2) {
                    continue;
                }
                line.add(new Coord(c.get(0).asDouble(), c.get(1).asDouble()));
            }
            out.add(new RawRoute(line,
                summary.path("distance").asDouble(),
                summary.path("duration").asDouble()));
        }
        return out;
    }

    /**
     * Parses {@code error.code} from an ORS error response body. Never logs
     * or rethrows the body itself — it may echo request details.
     */
    private Integer orsErrorCode(HttpStatusCodeException e) {
        try {
            JsonNode n = new ObjectMapper()
                .readTree(e.getResponseBodyAsString()).path("error").path("code");
            return n.isInt() ? n.asInt() : null;
        } catch (Exception ignored) {
            return null;
        }
    }

    @Override
    public List<GeocodeCandidate> geocode(String query) {
        // A URI template with placeholders, expanded by RestTemplate's own
        // UriTemplateHandler, which percent-encodes each variable. Building
        // the URL as a string and passing it through URI.create(...) does
        // not encode it, so any multi-word query (e.g. "Trafalgar Square")
        // would throw IllegalArgumentException outside the catch below.
        String urlTemplate = props.getBaseUrl()
            + "/geocode/search?api_key={key}&text={text}&boundary.country=GB&size=5";

        JsonNode root;
        try {
            root = http.getForObject(urlTemplate, JsonNode.class, props.getApiKey(), query);
        } catch (RestClientException e) {
            throw new RoutingException(RoutingException.Kind.UNAVAILABLE,
                "geocoding service unavailable", e);
        }
        List<GeocodeCandidate> out = new ArrayList<>();
        if (root == null) {
            return out;
        }
        for (JsonNode f : root.path("features")) {
            JsonNode c = f.path("geometry").path("coordinates");
            if (!c.isArray() || c.size() < 2) {
                continue;
            }
            out.add(new GeocodeCandidate(
                f.path("properties").path("label").asText(),
                c.get(0).asDouble(), c.get(1).asDouble()));
        }
        return out;
    }
}
