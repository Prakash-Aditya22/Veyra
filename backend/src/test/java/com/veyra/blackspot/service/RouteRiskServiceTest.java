package com.veyra.blackspot.service;

import java.util.List;

import com.veyra.blackspot.config.OrsProperties;
import com.veyra.blackspot.domain.RouteRisk.Coord;
import com.veyra.blackspot.domain.RouteRisk.GeocodeCandidate;
import com.veyra.blackspot.domain.RouteRisk.RawRoute;
import com.veyra.blackspot.domain.Segment;
import com.veyra.blackspot.repo.SegmentRepository;
import com.veyra.blackspot.repo.SegmentRepository.CorridorHit;
import com.veyra.blackspot.routing.RoutingClient;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class RouteRiskServiceTest {

    private static final Coord LONDON_S = new Coord(-0.0982, 51.3762);
    private static final Coord LONDON_N = new Coord(-0.1426, 51.5390);

    /** Default alternatives (target-count 3) are all these tests need. */
    private static final OrsProperties ORS_PROPS =
        new OrsProperties("test-key", "https://api.openrouteservice.org");

    private static Segment seg(String id, double score, int crashes) {
        return new Segment(id, "A23", 3, id, 0.5, 1.0, 51.46, -0.116,
            score, 1, crashes, 10, 1, 0.16, 20.0, 30.0, 0.2, 0.7);
    }

    private static RawRoute route(double metres, double seconds) {
        return new RawRoute(List.of(LONDON_S, LONDON_N), metres, seconds);
    }

    /** A RoutingClient that returns exactly what the test hands it. */
    private static RoutingClient fakeClient(List<RawRoute> routes) {
        return new RoutingClient() {
            @Override public List<RawRoute> route(Coord f, Coord t, int alternatives) {
                return routes;
            }
            @Override public List<GeocodeCandidate> geocode(String q) {
                return List.of();
            }
        };
    }

    @Test
    void blackspotsComeBackInTheOrderTheyAreDrivenPast() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt())).thenReturn(List.of(
            new CorridorHit(seg("far", 1.0, 10), 0.9),
            new CorridorHit(seg("near", 2.0, 10), 0.1),
            new CorridorHit(seg("mid", 3.0, 10), 0.5)));

        var svc = new RouteRiskService(fakeClient(List.of(route(10_000, 600))), repo, ORS_PROPS);
        var out = svc.assess(LONDON_S, LONDON_N, 6, 50);

        assertThat(out.routes().get(0).blackspots())
            .extracting("segmentId").containsExactly("near", "mid", "far");
    }

    @Test
    void metresAlongRouteScalesTheFractionByDistance() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt()))
            .thenReturn(List.of(new CorridorHit(seg("a", 1.0, 10), 0.25)));

        var svc = new RouteRiskService(fakeClient(List.of(route(10_000, 600))), repo, ORS_PROPS);
        var out = svc.assess(LONDON_S, LONDON_N, 6, 50);

        assertThat(out.routes().get(0).blackspots().get(0).metresAlongRoute()).isEqualTo(2500.0);
    }

    @Test
    void expectedKsiIsTheSumOfSegmentScores() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt())).thenReturn(List.of(
            new CorridorHit(seg("a", 1.5, 10), 0.1),
            new CorridorHit(seg("b", 2.5, 10), 0.6)));

        var svc = new RouteRiskService(fakeClient(List.of(route(10_000, 600))), repo, ORS_PROPS);
        var out = svc.assess(LONDON_S, LONDON_N, 6, 50);

        assertThat(out.routes().get(0).expectedKsi()).isEqualTo(4.0);
        assertThat(out.routes().get(0).blackspotCount()).isEqualTo(2);
        assertThat(out.routes().get(0).worstSegmentId()).isEqualTo("b");
    }

    @Test
    void fastestAndSafestAreLabelledAcrossAlternatives() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt()))
            .thenReturn(List.of(new CorridorHit(seg("a", 5.0, 10), 0.5)))
            .thenReturn(List.of(new CorridorHit(seg("b", 1.0, 10), 0.5)));

        var svc = new RouteRiskService(
            fakeClient(List.of(route(18_000, 2040), route(19_800, 2340))), repo, ORS_PROPS);
        var out = svc.assess(LONDON_S, LONDON_N, 6, 50);

        assertThat(out.routes().get(0).label()).isEqualTo("Fastest");
        assertThat(out.routes().get(1).label()).isEqualTo("Safest");
    }

    @Test
    void oneRouteCanBeBothFastestAndSafest() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt()))
            .thenReturn(List.of(new CorridorHit(seg("a", 1.0, 10), 0.5)))
            .thenReturn(List.of(new CorridorHit(seg("b", 9.0, 10), 0.5)));

        var svc = new RouteRiskService(
            fakeClient(List.of(route(18_000, 2040), route(19_800, 2340))), repo, ORS_PROPS);
        var out = svc.assess(LONDON_S, LONDON_N, 6, 50);

        assertThat(out.routes().get(0).label()).isEqualTo("Fastest and safest");
        assertThat(out.routes().get(1).label()).isEqualTo("Alternative");
    }

    @Test
    void aRouteWithNoBlackspotsIsAValidResultNotAnError() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt())).thenReturn(List.of());

        var svc = new RouteRiskService(fakeClient(List.of(route(10_000, 600))), repo, ORS_PROPS);
        var out = svc.assess(LONDON_S, LONDON_N, 6, 50);

        assertThat(out.routes()).hasSize(1);
        assertThat(out.routes().get(0).blackspots()).isEmpty();
        assertThat(out.routes().get(0).expectedKsi()).isZero();
        assertThat(out.routes().get(0).worstSegmentId()).isNull();
    }

    @Test
    void aRouteOutsideGreatBritainCarriesACoverageWarning() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt())).thenReturn(List.of());

        // Paris to Lyon
        var paris = new Coord(2.3522, 48.8566);
        var lyon = new Coord(4.8357, 45.7640);
        var svc = new RouteRiskService(
            fakeClient(List.of(new RawRoute(List.of(paris, lyon), 465_000, 16_000))), repo, ORS_PROPS);
        var out = svc.assess(paris, lyon, 6, 50);

        assertThat(out.coverageWarning()).contains("Great Britain");
    }

    @Test
    void thinlyEvidencedSegmentsAreFlaggedNotHidden() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt()))
            .thenReturn(List.of(new CorridorHit(seg("thin", 1.0, 3), 0.5)));

        var svc = new RouteRiskService(fakeClient(List.of(route(10_000, 600))), repo, ORS_PROPS);
        var out = svc.assess(LONDON_S, LONDON_N, 1, 50);

        assertThat(out.routes().get(0).blackspots().get(0).thinlyEvidenced()).isTrue();
    }
}
