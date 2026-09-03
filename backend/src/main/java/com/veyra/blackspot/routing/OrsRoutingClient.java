package com.veyra.blackspot.routing;

import java.net.URI;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.veyra.blackspot.config.OrsProperties;
import com.veyra.blackspot.domain.RouteRisk.Coord;
import com.veyra.blackspot.domain.RouteRisk.GeocodeCandidate;
import com.veyra.blackspot.domain.RouteRisk.RawRoute;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * OpenRouteService. Called server-side only, so the key never reaches a browser.
 *
 * ORS returns alternatives only when the request carries no via points, which
 * is why this client takes exactly two coordinates.
 */
@Component
public class OrsRoutingClient implements RoutingClient {

    private final RestTemplate http = new RestTemplate();
    private final OrsProperties props;

    public OrsRoutingClient(OrsProperties props) {
        this.props = props;
    }

    @Override
    public List<RawRoute> route(Coord from, Coord to, int alternatives) {
        String url = props.getBaseUrl() + "/v2/directions/driving-car/geojson";

        Map<String, Object> body = alternatives > 1
            ? Map.of("coordinates", List.of(List.of(from.lon(), from.lat()),
                                            List.of(to.lon(), to.lat())),
                     "alternative_routes", Map.of("target_count", alternatives,
                                                  "share_factor", 0.6,
                                                  "weight_factor", 1.6))
            : Map.of("coordinates", List.of(List.of(from.lon(), from.lat()),
                                            List.of(to.lon(), to.lat())));

        HttpHeaders h = new HttpHeaders();
        h.set(HttpHeaders.AUTHORIZATION, props.getApiKey());
        h.setContentType(MediaType.APPLICATION_JSON);

        JsonNode root;
        try {
            root = http.postForObject(URI.create(url), new HttpEntity<>(body, h), JsonNode.class);
        } catch (RestClientException e) {
            throw new RoutingException(RoutingException.Kind.UNAVAILABLE,
                "routing service unavailable", e);
        }
        if (root == null || !root.has("features") || root.get("features").isEmpty()) {
            throw new RoutingException(RoutingException.Kind.NO_ROUTE,
                "no drivable route between those points");
        }

        List<RawRoute> out = new ArrayList<>();
        for (JsonNode f : root.get("features")) {
            JsonNode summary = f.path("properties").path("summary");
            List<Coord> line = new ArrayList<>();
            for (JsonNode c : f.path("geometry").path("coordinates")) {
                line.add(new Coord(c.get(0).asDouble(), c.get(1).asDouble()));
            }
            out.add(new RawRoute(line,
                summary.path("distance").asDouble(),
                summary.path("duration").asDouble()));
        }
        return out;
    }

    @Override
    public List<GeocodeCandidate> geocode(String query) {
        String url = UriComponentsBuilder.fromUriString(props.getBaseUrl() + "/geocode/search")
            .queryParam("api_key", props.getApiKey())
            .queryParam("text", query)
            .queryParam("boundary.country", "GB")
            .queryParam("size", 5)
            .toUriString();

        JsonNode root;
        try {
            root = http.getForObject(URI.create(url), JsonNode.class);
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
            out.add(new GeocodeCandidate(
                f.path("properties").path("label").asText(),
                c.get(0).asDouble(), c.get(1).asDouble()));
        }
        return out;
    }
}
