package com.veyra.blackspot.repo;

import java.util.List;
import java.util.Optional;

import com.veyra.blackspot.domain.Segment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
public class SegmentRepository {

    /** ST_X/ST_Y need geometry; geom is stored as geography for metre distances. */
    private static final String COLS = """
        segment_id, road_id, run, location, km_from, km_to,
        ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon,
        blackspot_score, rank, n_crashes, n_ksi, n_fatal,
        ksi_rate, crashes_per_year, speed_max, pct_night, pct_junction
        """;

    private static final RowMapper<Segment> MAPPER = (rs, n) -> new Segment(
        rs.getString("segment_id"), rs.getString("road_id"), rs.getInt("run"),
        rs.getString("location"), rs.getDouble("km_from"), rs.getDouble("km_to"),
        rs.getDouble("lat"), rs.getDouble("lon"),
        rs.getDouble("blackspot_score"), rs.getInt("rank"),
        rs.getInt("n_crashes"), rs.getInt("n_ksi"), rs.getInt("n_fatal"),
        (Double) rs.getObject("ksi_rate"), (Double) rs.getObject("crashes_per_year"),
        (Double) rs.getObject("speed_max"), (Double) rs.getObject("pct_night"),
        (Double) rs.getObject("pct_junction"));

    /** A segment on a route, with its position along it as a 0-1 fraction. */
    public record CorridorHit(Segment segment, double fraction) {
    }

    private final JdbcTemplate jdbc;

    public SegmentRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<Segment> findById(String segmentId) {
        return jdbc.query("SELECT " + COLS + " FROM road_segment WHERE segment_id = ?",
                          MAPPER, segmentId).stream().findFirst();
    }

    public List<Segment> findInBbox(BoundingBox b, double minScore, int minCrashes, int limit) {
        return jdbc.query("""
            SELECT %s FROM road_segment
            WHERE geom && ST_MakeEnvelope(?,?,?,?,4326)::geography
              AND blackspot_score >= ? AND n_crashes >= ?
            ORDER BY blackspot_score DESC
            LIMIT ?
            """.formatted(COLS), MAPPER,
            b.minLon(), b.minLat(), b.maxLon(), b.maxLat(), minScore, minCrashes, limit);
    }

    public List<Segment> findTop(int limit) {
        return jdbc.query("SELECT " + COLS + " FROM road_segment ORDER BY rank ASC LIMIT ?",
                          MAPPER, limit);
    }

    /**
     * Segments within corridorMetres of the route, ordered as a driver meets them.
     *
     * ST_DWithin on geography gives true metre distances. ST_LineLocatePoint
     * needs geometry, hence the casts. Ordering by that fraction is what makes
     * the result a journey rather than a set.
     */
    public List<CorridorHit> findAlongRoute(String routeWkt, double corridorMetres, int minCrashes) {
        return jdbc.query("""
            SELECT %s, ST_LineLocatePoint(
                     ST_GeomFromText(?, 4326), geom::geometry) AS frac
            FROM road_segment
            WHERE ST_DWithin(geom, ST_GeomFromText(?, 4326)::geography, ?)
              AND n_crashes >= ?
            ORDER BY frac
            """.formatted(COLS),
            (rs, n) -> new CorridorHit(MAPPER.mapRow(rs, n), rs.getDouble("frac")),
            routeWkt, routeWkt, corridorMetres, minCrashes);
    }
}
