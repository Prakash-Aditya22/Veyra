package com.veyra.blackspot.load;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.Reader;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.veyra.blackspot.domain.Segment;

/**
 * Reads the exported segment CSV into Segment records.
 *
 * Two columns in the export are NOT read: future_ksi and future_fatal. They
 * are the 2022-23 outcome the model is validated against. There is no field
 * for them on Segment and no column in the schema.
 */
public final class SegmentCsvReader {

    private SegmentCsvReader() {
    }

    public static List<Segment> read(Reader in) {
        List<Segment> out = new ArrayList<>();
        try (BufferedReader r = new BufferedReader(in)) {
            String header = r.readLine();
            if (header == null) {
                throw new IllegalArgumentException("CSV is empty");
            }
            Map<String, Integer> col = index(splitCsv(header));

            String line;
            while ((line = r.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                String[] f = splitCsv(line);
                String segmentId = f[col.get("segment_id")];
                // Throws on a malformed id rather than defaulting run to 0.
                int run = SegmentIdParser.parse(segmentId).run();

                out.add(new Segment(
                    segmentId,
                    f[col.get("road_id")],
                    run,
                    f[col.get("location")],
                    d(f, col, "km_from"), d(f, col, "km_to"),
                    d(f, col, "lat"), d(f, col, "lon"),
                    d(f, col, "blackspot_score"),
                    (int) d(f, col, "rank"),
                    (int) d(f, col, "n_crashes"),
                    (int) d(f, col, "n_ksi"),
                    (int) d(f, col, "n_fatal"),
                    nullable(f, col, "ksi_rate"),
                    nullable(f, col, "crashes_per_year"),
                    nullable(f, col, "speed_max"),
                    nullable(f, col, "pct_night"),
                    nullable(f, col, "pct_junction")));
            }
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        return out;
    }

    private static Map<String, Integer> index(String[] header) {
        Map<String, Integer> m = new HashMap<>();
        for (int i = 0; i < header.length; i++) {
            m.put(header[i].trim(), i);
        }
        for (String required : List.of("segment_id", "road_id", "location", "lat", "lon",
                                       "blackspot_score", "n_crashes", "n_ksi", "n_fatal", "rank")) {
            if (!m.containsKey(required)) {
                throw new IllegalArgumentException("CSV is missing column: " + required);
            }
        }
        return m;
    }

    private static double d(String[] f, Map<String, Integer> col, String name) {
        Double v = nullable(f, col, name);
        if (v == null) {
            throw new IllegalArgumentException("column " + name + " is empty and not nullable");
        }
        return v;
    }

    private static Double nullable(String[] f, Map<String, Integer> col, String name) {
        Integer i = col.get(name);
        if (i == null || i >= f.length || f[i].isBlank()) {
            return null;
        }
        return Double.parseDouble(f[i]);
    }

    /** Minimal RFC-4180 split: honours double quotes and doubled quotes inside them. */
    static String[] splitCsv(String line) {
        List<String> out = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        boolean quoted = false;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (quoted) {
                if (c == '"') {
                    if (i + 1 < line.length() && line.charAt(i + 1) == '"') {
                        cur.append('"');
                        i++;
                    } else {
                        quoted = false;
                    }
                } else {
                    cur.append(c);
                }
            } else if (c == '"') {
                quoted = true;
            } else if (c == ',') {
                out.add(cur.toString());
                cur.setLength(0);
            } else {
                cur.append(c);
            }
        }
        out.add(cur.toString());
        return out.toArray(new String[0]);
    }
}
