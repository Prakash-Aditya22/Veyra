package com.veyra.blackspot.routing;

import java.util.List;

import com.veyra.blackspot.domain.RouteRisk.Coord;
import com.veyra.blackspot.domain.RouteRisk.GeocodeCandidate;
import com.veyra.blackspot.domain.RouteRisk.RawRoute;

/**
 * Routing and geocoding, with no knowledge of blackspots.
 *
 * This boundary is what lets RouteRiskService be unit-tested against a fake
 * with no network and no API key.
 */
public interface RoutingClient {

    /** Returns 1..alternatives routes, fastest first. Never empty. */
    List<RawRoute> route(Coord from, Coord to, int alternatives);

    /** At most 5 candidates, restricted to Great Britain. Empty is valid. */
    List<GeocodeCandidate> geocode(String query);
}
