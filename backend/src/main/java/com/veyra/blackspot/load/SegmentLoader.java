package com.veyra.blackspot.load;

import java.io.FileReader;
import java.nio.file.Path;
import java.util.List;

import com.veyra.blackspot.domain.Segment;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * One-off CSV load, triggered by --load-data. Idempotent: it truncates first,
 * so re-running after a data refresh is safe.
 */
@Component
public class SegmentLoader implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(SegmentLoader.class);
    private static final int BATCH = 1000;

    private static final String INSERT = """
        INSERT INTO road_segment (
          segment_id, road_id, run, location, km_from, km_to, geom,
          blackspot_score, rank, n_crashes, n_ksi, n_fatal,
          ksi_rate, crashes_per_year, speed_max, pct_night, pct_junction)
        VALUES (?,?,?,?,?,?, ST_SetSRID(ST_MakePoint(?,?),4326)::geography,
                ?,?,?,?,?,?,?,?,?,?)
        """;

    private final JdbcTemplate jdbc;

    public SegmentLoader(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public void run(ApplicationArguments args) throws Exception {
        if (!args.containsOption("load-data")) {
            return;
        }
        Path csv = args.containsOption("csv")
            ? Path.of(args.getOptionValues("csv").get(0))
            : Path.of("..", "data", "road_segments_ranked.csv");

        log.info("loading segments from {}", csv.toAbsolutePath());
        List<Segment> rows;
        try (var r = new FileReader(csv.toFile())) {
            rows = SegmentCsvReader.read(r);
        }
        log.info("parsed {} segments", rows.size());

        jdbc.update("TRUNCATE TABLE road_segment");
        for (int i = 0; i < rows.size(); i += BATCH) {
            List<Segment> chunk = rows.subList(i, Math.min(i + BATCH, rows.size()));
            jdbc.batchUpdate(INSERT, chunk, chunk.size(), (ps, s) -> {
                ps.setString(1, s.segmentId());
                ps.setString(2, s.roadId());
                ps.setInt(3, s.run());
                ps.setString(4, s.location());
                ps.setDouble(5, s.kmFrom());
                ps.setDouble(6, s.kmTo());
                ps.setDouble(7, s.lon());   // ST_MakePoint takes lon first
                ps.setDouble(8, s.lat());
                ps.setDouble(9, s.blackspotScore());
                ps.setInt(10, s.rank());
                ps.setInt(11, s.nCrashes());
                ps.setInt(12, s.nKsi());
                ps.setInt(13, s.nFatal());
                setNullable(ps, 14, s.ksiRate());
                setNullable(ps, 15, s.crashesPerYear());
                setNullable(ps, 16, s.speedMax());
                setNullable(ps, 17, s.pctNight());
                setNullable(ps, 18, s.pctJunction());
            });
            log.info("  inserted {}/{}", Math.min(i + BATCH, rows.size()), rows.size());
        }
        Integer n = jdbc.queryForObject("SELECT count(*) FROM road_segment", Integer.class);
        log.info("load complete: {} rows in road_segment", n);
    }

    private static void setNullable(java.sql.PreparedStatement ps, int i, Double v)
            throws java.sql.SQLException {
        if (v == null) {
            ps.setNull(i, java.sql.Types.DOUBLE);
        } else {
            ps.setDouble(i, v);
        }
    }
}
