package com.veyra.blackspot.load;

import java.io.InputStreamReader;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.util.List;

import com.veyra.blackspot.domain.Segment;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SegmentCsvReaderTest {

    private static Reader sample() {
        return new InputStreamReader(
            SegmentCsvReaderTest.class.getResourceAsStream("/segments-sample.csv"),
            StandardCharsets.UTF_8);
    }

    @Test
    void readsEveryRow() {
        assertThat(SegmentCsvReader.read(sample())).hasSize(3);
    }

    @Test
    void mapsColumnsOntoTheRecord() {
        Segment s = SegmentCsvReader.read(sample()).get(0);
        assertThat(s.segmentId()).isEqualTo("A23_run3_km0.5");
        assertThat(s.roadId()).isEqualTo("A23");
        assertThat(s.location()).isEqualTo("A23 km 0.5-1.0 (seg 3)");
        assertThat(s.lat()).isEqualTo(51.460757316666665);
        assertThat(s.lon()).isEqualTo(-0.11601963333333334);
        assertThat(s.blackspotScore()).isEqualTo(9.665665498389384);
        assertThat(s.nCrashes()).isEqualTo(60);
        assertThat(s.nKsi()).isEqualTo(10);
        assertThat(s.nFatal()).isZero();
        assertThat(s.rank()).isEqualTo(1);
    }

    @Test
    void derivesRunFromTheSegmentId() {
        List<Segment> rows = SegmentCsvReader.read(sample());
        assertThat(rows.get(0).run()).isEqualTo(3);
        assertThat(rows.get(1).run()).isZero();
        assertThat(rows.get(2).run()).isEqualTo(2);
    }

    @Test
    void commasInsideQuotedFieldsDoNotSplitTheRow() {
        String csv = """
            rank,segment_id,location,road_id,km_from,km_to,lat,lon,blackspot_score,n_crashes,n_ksi,n_fatal,ksi_rate,crashes_per_year,speed_max,pct_night,pct_junction,future_ksi,future_fatal
            1,A1_run0_km0.0,"A1 km 0.0-0.5, north",A1,0.0,0.5,51.5,-0.1,1.0,10,2,0,0.2,3.3,30.0,0.1,0.5,1.0,0.0
            """;
        Segment s = SegmentCsvReader.read(new java.io.StringReader(csv)).get(0);
        assertThat(s.location()).isEqualTo("A1 km 0.0-0.5, north");
        assertThat(s.roadId()).isEqualTo("A1");
    }

    @Test
    void aMalformedSegmentIdAbortsTheWholeRead() {
        String csv = """
            rank,segment_id,location,road_id,km_from,km_to,lat,lon,blackspot_score,n_crashes,n_ksi,n_fatal,ksi_rate,crashes_per_year,speed_max,pct_night,pct_junction,future_ksi,future_fatal
            1,BROKEN_ID,loc,A1,0.0,0.5,51.5,-0.1,1.0,10,2,0,0.2,3.3,30.0,0.1,0.5,1.0,0.0
            """;
        assertThatThrownBy(() -> SegmentCsvReader.read(new java.io.StringReader(csv)))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("BROKEN_ID");
    }
}
