package com.veyra.blackspot.web;

import java.util.List;
import java.util.Optional;

import com.veyra.blackspot.domain.Segment;
import com.veyra.blackspot.repo.BoundingBox;
import com.veyra.blackspot.repo.SegmentRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest({SegmentController.class, ApiExceptionHandler.class})
class SegmentControllerTest {

    // Empirically determined by running the response through Jackson and
    // printing its actual key set (see task-7-report.md, fix round). These
    // are exactly the record's 18 components, alphabetical order; the derived
    // accessors nSerious() and thinlyEvidenced() do NOT appear because
    // neither follows the getX/isX bean-accessor naming Jackson looks for.
    // Any field added to Segment must be added here deliberately — this is
    // what stops a future_ksi-shaped column reaching the wire under ANY name.
    private static final java.util.Set<String> EXPECTED_KEYS = java.util.Set.of(
        "blackspotScore", "crashesPerYear", "kmFrom", "kmTo", "ksiRate", "lat",
        "location", "lon", "nCrashes", "nFatal", "nKsi", "pctJunction",
        "pctNight", "rank", "roadId", "run", "segmentId", "speedMax");

    @Autowired MockMvc mvc;
    @MockitoBean SegmentRepository repo;

    private static Segment sample() {
        return new Segment("A23_run3_km0.5", "A23", 3, "A23 km 0.5-1.0 (seg 3)",
            0.5, 1.0, 51.4607, -0.1160, 9.67, 1, 60, 10, 0, 0.167, 20.0, 30.0, 0.233, 0.7);
    }

    @Test
    void returnsSegmentsInBbox() throws Exception {
        when(repo.findInBbox(any(BoundingBox.class), anyDouble(), anyInt(), anyInt()))
            .thenReturn(List.of(sample()));
        mvc.perform(get("/api/segments?bbox=-0.51,51.28,0.34,51.70"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0].segmentId").value("A23_run3_km0.5"))
           .andExpect(jsonPath("$[0].run").value(3))
           .andExpect(jsonPath("$[0].blackspotScore").value(9.67));
    }

    @Test
    void neverExposesFutureOutcomeFields() throws Exception {
        when(repo.findInBbox(any(BoundingBox.class), anyDouble(), anyInt(), anyInt()))
            .thenReturn(List.of(sample()));
        mvc.perform(get("/api/segments?bbox=-0.51,51.28,0.34,51.70"))
           .andExpect(jsonPath("$[0].futureKsi").doesNotExist())
           .andExpect(jsonPath("$[0].futureFatal").doesNotExist());
    }

    @Test
    void malformedBboxIsFourHundredNamingTheParameter() throws Exception {
        mvc.perform(get("/api/segments?bbox=nope"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.message").value(org.hamcrest.Matchers.containsString("bbox")));
    }

    @Test
    void limitAboveTheCapIsRejected() throws Exception {
        mvc.perform(get("/api/segments?bbox=-0.51,51.28,0.34,51.70&limit=99999"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.message").value(org.hamcrest.Matchers.containsString("limit")));
    }

    @Test
    void limitBelowOneIsRejected() throws Exception {
        mvc.perform(get("/api/segments?bbox=-0.51,51.28,0.34,51.70&limit=0"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.message").value(org.hamcrest.Matchers.containsString("limit")));
    }

    @Test
    void withoutBboxReturnsTopRanked() throws Exception {
        when(repo.findTop(anyInt())).thenReturn(List.of(sample()));
        mvc.perform(get("/api/segments"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0].rank").value(1));
    }

    @Test
    void unknownSegmentIsFourOhFour() throws Exception {
        when(repo.findById(anyString())).thenReturn(Optional.empty());
        mvc.perform(get("/api/segments/NOPE"))
           .andExpect(status().isNotFound());
    }

    @Test
    void responseExposesExactlyTheExpectedFields() throws Exception {
        when(repo.findInBbox(any(BoundingBox.class), anyDouble(), anyInt(), anyInt()))
            .thenReturn(List.of(sample()));

        String body = mvc.perform(get("/api/segments?bbox=-0.51,51.28,0.34,51.70"))
            .andReturn().getResponse().getContentAsString();

        var node = new com.fasterxml.jackson.databind.ObjectMapper().readTree(body).get(0);
        var keys = new java.util.TreeSet<String>();
        node.fieldNames().forEachRemaining(keys::add);

        // Any field added to Segment must be added here deliberately. This is what
        // stops a future_ksi-shaped column reaching the wire under ANY name.
        org.assertj.core.api.Assertions.assertThat(keys)
            .containsExactlyInAnyOrderElementsOf(EXPECTED_KEYS);
    }
}
