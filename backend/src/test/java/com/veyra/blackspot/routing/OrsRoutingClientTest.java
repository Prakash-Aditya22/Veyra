package com.veyra.blackspot.routing;

import java.util.List;

import com.veyra.blackspot.config.OrsProperties;
import com.veyra.blackspot.domain.RouteRisk.Coord;
import com.veyra.blackspot.domain.RouteRisk.GeocodeCandidate;
import com.veyra.blackspot.domain.RouteRisk.RawRoute;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.web.client.MockServerRestTemplateCustomizer;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.queryParam;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withBadRequest;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * The client's outgoing request, asserted against the RestTemplate it actually
 * builds. No network, no key, no ORS quota.
 *
 * RouteControllerTest already checks that a multi-word query reaches the client
 * with its space intact, but the bug that regression guards was never in the
 * controller -- it was here, behind that mock. Building the geocode URL as a
 * string and handing it to URI.create() does not percent-encode it, so
 * "Trafalgar Square" threw IllegalArgumentException, which is not a
 * RestClientException and so escaped the catch as an unhandled 500. Only a test
 * that inspects the URI leaving this class can hold that fix in place.
 *
 * MockServerRestTemplateCustomizer is how the server binds to a RestTemplate
 * the class under test builds for itself: the customizer is handed to the
 * builder, so no test-only accessor has to be opened up in production code.
 */
class OrsRoutingClientTest {

    private static final String BASE = "https://ors.test";
    private static final String KEY = "test-key-not-a-real-credential";

    private MockRestServiceServer server;
    private OrsRoutingClient client;

    @BeforeEach
    void setUp() {
        MockServerRestTemplateCustomizer customizer = new MockServerRestTemplateCustomizer();
        client = new OrsRoutingClient(new OrsProperties(KEY, BASE),
                                      new RestTemplateBuilder(customizer));
        server = customizer.getServer();
    }

    @Test
    void aMultiWordGeocodeQueryLeavesPercentEncoded() {
        server.expect(requestTo(
                BASE + "/geocode/search?text=Trafalgar%20Square&boundary.country=GB&size=5"))
              .andRespond(withSuccess("""
                  {"features":[{"properties":{"label":"Trafalgar Square, London"},
                                "geometry":{"coordinates":[-0.1281,51.5080]}}]}
                  """, MediaType.APPLICATION_JSON));

        List<GeocodeCandidate> found = client.geocode("Trafalgar Square");

        server.verify();
        assertThat(found).singleElement()
            .extracting(GeocodeCandidate::label).isEqualTo("Trafalgar Square, London");
    }

    @Test
    void aQueryOfUriMetacharactersIsEncodedRatherThanInjectedIntoTheQueryString() {
        // "&size=1" inside the text must stay inside `text`, not become its own
        // parameter -- an unencoded ampersand would silently rewrite the request.
        //
        // The apostrophe is deliberately NOT expected as %27: it is a sub-delim
        // and legal unencoded in a query, so RestTemplate leaves it alone. What
        // has to be encoded is the delimiter pair, & and =, and it is.
        server.expect(requestTo(BASE + "/geocode/search"
                + "?text=King's%20Cross%20%26size%3D1&boundary.country=GB&size=5"))
              // And the request still carries exactly one `size`, ours. Had the
              // ampersand gone through raw, the query's first `size` would be
              // the 1 smuggled in through `text`.
              .andExpect(queryParam("size", "5"))
              .andRespond(withSuccess("{\"features\":[]}", MediaType.APPLICATION_JSON));

        assertThat(client.geocode("King's Cross &size=1")).isEmpty();

        server.verify();
    }

    @Test
    void aTripTooLongForAlternativesFallsBackToTheSingleBestRoute() {
        // ORS refuses alternative_routes when the approximated route exceeds
        // 100 km -- HTTP 400, error.code 2004. Verified live: Cheltenham ->
        // Camden (~150 km) got exactly this, and the same body without
        // alternative_routes returned 200. Before this fallback, every trip
        // over 100 km surfaced as "routing temporarily unavailable".
        server.expect(requestTo(BASE + "/v2/directions/driving-car/geojson"))
              .andExpect(jsonPath("$.alternative_routes").exists())
              .andRespond(withBadRequest().contentType(MediaType.APPLICATION_JSON).body("""
                  {"error":{"code":2004,
                            "message":"The approximated route distance must not be greater than 100000.0 meters for use with the alternative Routes algorithm."}}
                  """));
        server.expect(requestTo(BASE + "/v2/directions/driving-car/geojson"))
              .andExpect(jsonPath("$.alternative_routes").doesNotExist())
              .andRespond(withSuccess("""
                  {"features":[{"properties":{"summary":{"distance":152000,"duration":7200}},
                                "geometry":{"coordinates":[[-2.07,51.90],[-0.14,51.54]]}}]}
                  """, MediaType.APPLICATION_JSON));

        List<RawRoute> routes = client.route(new Coord(-2.07211, 51.900898),
                                             new Coord(-0.1426, 51.5390), 3);

        server.verify();
        assertThat(routes).singleElement()
            .extracting(RawRoute::distanceMetres).isEqualTo(152000.0);
    }

    @Test
    void theKeyTravelsAsAnAuthorizationHeaderAndNeverInTheUri() {
        // A credential in a URI reaches Spring's own DEBUG logger, any HTTP
        // wire log and any proxy access log. route() has always used a header;
        // this asserts geocode() does too, and that api_key= is gone for good.
        server.expect(requestTo(org.hamcrest.Matchers.not(
                  org.hamcrest.Matchers.containsString("api_key"))))
              .andExpect(header(HttpHeaders.AUTHORIZATION, KEY))
              .andRespond(withSuccess("{\"features\":[]}", MediaType.APPLICATION_JSON));

        client.geocode("Croydon");

        server.verify();
    }
}
