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
}
