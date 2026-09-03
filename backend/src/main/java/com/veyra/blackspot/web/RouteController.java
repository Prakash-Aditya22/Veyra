package com.veyra.blackspot.web;

import java.util.List;

import com.veyra.blackspot.domain.RouteRisk.GeocodeCandidate;
import com.veyra.blackspot.domain.RouteRisk.RouteRiskResponse;
import com.veyra.blackspot.routing.RoutingClient;
import com.veyra.blackspot.service.RouteRiskService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class RouteController {

    private final RouteRiskService service;
    private final RoutingClient routing;
    private final int defaultMinCrashes;
    private final double defaultCorridor;

    public RouteController(RouteRiskService service, RoutingClient routing,
                           @Value("${blackspot.min-crashes}") int defaultMinCrashes,
                           @Value("${blackspot.corridor-metres}") double defaultCorridor) {
        this.service = service;
        this.routing = routing;
        this.defaultMinCrashes = defaultMinCrashes;
        this.defaultCorridor = defaultCorridor;
    }

    @PostMapping("/api/route/risk")
    public RouteRiskResponse risk(@RequestBody RouteRiskRequest req) {
        int minCrashes = req.minCrashes() == null ? defaultMinCrashes : req.minCrashes();
        double corridor = req.corridorMetres() == null ? defaultCorridor : req.corridorMetres();
        if (minCrashes < 1) {
            throw new IllegalArgumentException("minCrashes must be at least 1");
        }
        if (corridor < 10 || corridor > 500) {
            throw new IllegalArgumentException("corridorMetres must be between 10 and 500");
        }
        return service.assess(req.fromCoord(), req.toCoord(), minCrashes, corridor);
    }

    @GetMapping("/api/geocode")
    public List<GeocodeCandidate> geocode(@RequestParam String q) {
        if (q == null || q.isBlank()) {
            throw new IllegalArgumentException("q is required");
        }
        return routing.geocode(q);
    }
}
