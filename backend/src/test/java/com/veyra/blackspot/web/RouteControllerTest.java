package com.veyra.blackspot.web;

import java.util.List;

import com.veyra.blackspot.domain.RouteRisk.Coord;
import com.veyra.blackspot.domain.RouteRisk.GeocodeCandidate;
import com.veyra.blackspot.domain.RouteRisk.RouteRiskResponse;
import com.veyra.blackspot.domain.RouteRisk.ScoredRoute;
import com.veyra.blackspot.routing.RoutingClient;
import com.veyra.blackspot.routing.RoutingException;
import com.veyra.blackspot.service.RouteRiskService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest({RouteController.class, ApiExceptionHandler.class})
class RouteControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean RouteRiskService service;
    @MockitoBean RoutingClient routing;

    private static final String BODY = """
        {"from":[-0.0982,51.3762],"to":[-0.1426,51.5390],"minCrashes":6}
        """;

    @Test
    void returnsScoredRoutes() throws Exception {
        when(service.assess(any(), any(), anyInt(), anyDouble())).thenReturn(
            new RouteRiskResponse(List.of(new ScoredRoute(
                0, "Fastest", 18240, 2040, List.of(new Coord(-0.098, 51.376)),
                4.23, 6, "A23_run3_km0.5", List.of())), null));

        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON).content(BODY))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.routes[0].label").value("Fastest"))
           .andExpect(jsonPath("$.routes[0].expectedKsi").value(4.23))
           .andExpect(jsonPath("$.routes[0].blackspotCount").value(6));
    }

    @Test
    void routingUnavailableIsFiveOhThree() throws Exception {
        when(service.assess(any(), any(), anyInt(), anyDouble())).thenThrow(
            new RoutingException(RoutingException.Kind.UNAVAILABLE, "routing service unavailable"));

        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON).content(BODY))
           .andExpect(status().isServiceUnavailable());
    }

    @Test
    void noRouteIsFourTwentyTwo() throws Exception {
        when(service.assess(any(), any(), anyInt(), anyDouble())).thenThrow(
            new RoutingException(RoutingException.Kind.NO_ROUTE, "no drivable route"));

        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON).content(BODY))
           .andExpect(status().isUnprocessableEntity());
    }

    @Test
    void aMalformedCoordinatePairIsFourHundred() throws Exception {
        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON)
                    .content("""
                        {"from":[-0.0982],"to":[-0.1426,51.5390]}
                        """))
           .andExpect(status().isBadRequest());
    }

    /*
     * Named for what it asserts, not for the premise it was written under. The
     * original name claimed a literal `null` body had been a 500; it never
     * was. Spring's AbstractMessageConverterMethodArgumentResolver refuses to
     * bind a null-deserialized value to a required @RequestBody and throws
     * HttpMessageNotReadableException before the method body runs, so the
     * status was already 400. What this test actually holds in place is that
     * the reply carries this API's own {"message": ...} contract rather than
     * Spring's default error page.
     */
    @Test
    void aNullBodyIsRejectedWithThisApisOwnErrorBody() throws Exception {
        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON).content("null"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.message").value(containsString("request body")));
    }

    @Test
    void anOutOfRangeCoordinateIsRejected() throws Exception {
        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON)
                    .content("""
                        {"from":[-0.0982,51.3762],"to":[999.0,51.5390]}
                        """))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.message").value(containsString("to")));
    }

    @Test
    void minCrashesBelowOneIsRejected() throws Exception {
        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON)
                    .content("""
                        {"from":[-0.0982,51.3762],"to":[-0.1426,51.5390],"minCrashes":0}
                        """))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.message").value(containsString("minCrashes")));
    }

    @Test
    void corridorMetresOutsideBoundsIsRejected() throws Exception {
        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON)
                    .content("""
                        {"from":[-0.0982,51.3762],"to":[-0.1426,51.5390],"corridorMetres":5000}
                        """))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.message").value(containsString("corridorMetres")));
    }

    @Test
    void geocodeReturnsCandidates() throws Exception {
        when(routing.geocode(anyString())).thenReturn(
            List.of(new GeocodeCandidate("Croydon, England", -0.0982, 51.3762)));

        mvc.perform(get("/api/geocode?q=croydon"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0].label").value("Croydon, England"));
    }

    @Test
    void geocodeWithNoMatchIsAnEmptyListNotAnError() throws Exception {
        when(routing.geocode(anyString())).thenReturn(List.of());
        mvc.perform(get("/api/geocode?q=zzzzzz"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isEmpty());
    }

    @Test
    void aBlankQIsRejected() throws Exception {
        mvc.perform(get("/api/geocode?q="))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.message").value(containsString("q")));
    }

    @Test
    void aMultiWordQueryReachesTheClientWithItsSpaceIntact() throws Exception {
        when(routing.geocode("Trafalgar Square")).thenReturn(
            List.of(new GeocodeCandidate("Trafalgar Square, London", -0.1281, 51.5080)));

        mvc.perform(get("/api/geocode").param("q", "Trafalgar Square"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0].label").value("Trafalgar Square, London"));

        verify(routing).geocode("Trafalgar Square");
    }
}
