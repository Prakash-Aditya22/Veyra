-- Applied manually to Supabase once. See backend/README.md.
-- Supabase ships PostGIS; the CREATE EXTENSION keeps this file self-contained.
CREATE EXTENSION IF NOT EXISTS postgis;

DROP TABLE IF EXISTS road_segment;

CREATE TABLE road_segment (
  segment_id       TEXT PRIMARY KEY,
  road_id          TEXT NOT NULL,
  run              INTEGER NOT NULL,
  location         TEXT NOT NULL,
  km_from          DOUBLE PRECISION,
  km_to            DOUBLE PRECISION,
  geom             GEOGRAPHY(POINT,4326) NOT NULL,
  blackspot_score  DOUBLE PRECISION NOT NULL,
  rank             INTEGER NOT NULL,
  n_crashes        INTEGER NOT NULL,
  n_ksi            INTEGER NOT NULL,
  n_fatal          INTEGER NOT NULL,
  ksi_rate         DOUBLE PRECISION,
  crashes_per_year DOUBLE PRECISION,
  speed_max        DOUBLE PRECISION,
  pct_night        DOUBLE PRECISION,
  pct_junction     DOUBLE PRECISION
);

-- No future_ksi / future_fatal column exists, by design. Those are the
-- 2022-23 outcome the model is validated against; serving them shows the
-- answer. The absence of the column is the enforcement.

CREATE INDEX idx_seg_geom  ON road_segment USING GIST (geom);
CREATE INDEX idx_seg_score ON road_segment (blackspot_score DESC);
CREATE INDEX idx_seg_road  ON road_segment (road_id, run, km_from);
