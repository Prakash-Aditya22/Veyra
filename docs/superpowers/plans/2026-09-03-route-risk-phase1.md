# Route Risk — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A driver enters A and B and sees which blackspots lie on each candidate route, backed by a Spring Boot API over Supabase PostGIS.

**Architecture:** Spring Boot reads the 45,014-segment CSV into Supabase Postgres once, then serves two things: segment queries for the map, and route risk. Route risk calls OpenRouteService for 2–3 alternative routes, hands each route's LineString to PostGIS, and gets back the blackspots within a 50 m corridor ordered by distance along the route. The React app gains one screen and switches Explorer from its fixture to the live API.

**Tech Stack:** Java 21 (on JDK 22), Spring Boot 3.4.1, Maven wrapper, `JdbcTemplate` (not JPA — the corridor query is hand-written PostGIS), Supabase Postgres + PostGIS, OpenRouteService, React 18 + Leaflet + Vite, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-03-route-risk-design.md`

## Global Constraints

- Branch `integration`. Backend lives in `backend/`, nothing else moves.
- **No secret is ever written to a tracked file.** `DATABASE_URL` and `ORS_API_KEY` are read from the environment. `backend/.env` is gitignored before it exists; `backend/.env.example` carries key names with empty values.
- **`future_ksi` and `future_fatal` must not reach the database or any response.** There is no column for them. Enforced by a test.
- The API returns raw `blackspotScore` (0–9.67, expected KSI over two years). The 0–100 tier mapping lives only in `frontend/src/lib/riskScale.js`.
- **Docker's daemon is not running on this machine.** Tests requiring PostGIS are tagged `@Tag("postgis")` and excluded from the default `mvn test`. `mvn test` must pass green with no Docker and no database.
- Wording rule, from the spec: `expectedKsi` is casualties on a corridor over two years across all traffic — never a per-trip risk, never "predicted severity".
- Java target 21 (LTS), not 22 — a teammate on JDK 21 must be able to build.
- Commit after every task.

---

## File Structure

**`backend/`** — one responsibility per class:

| File | Responsibility |
|---|---|
| `pom.xml`, `mvnw`, `mvnw.cmd`, `.mvn/` | Build, wrapper so no global Maven needed |
| `.env.example`, `.gitignore` | Key names, secret exclusion |
| `src/main/resources/application.yml` | Config, env var binding |
| `src/main/resources/schema.sql` | Table + indexes, applied manually to Supabase |
| `…/BlackspotApplication.java` | Entry point |
| `…/config/WebConfig.java` | CORS for the Vite dev server |
| `…/config/OrsProperties.java` | `ORS_API_KEY` binding, fails fast when unset |
| `…/domain/Segment.java` | Segment record |
| `…/domain/RouteRisk.java` | `ScoredRoute`, `BlackspotOnRoute`, `RouteRiskResponse`, `GeocodeCandidate` |
| `…/load/SegmentIdParser.java` | `A23_run3_km0.5` → road / run / km |
| `…/load/SegmentLoader.java` | CSV → Postgres, behind `--load-data` |
| `…/repo/SegmentRepository.java` | All SQL, including the corridor query |
| `…/routing/RoutingClient.java` | Interface: `route()`, `geocode()` |
| `…/routing/OrsRoutingClient.java` | ORS implementation, HTTP only |
| `…/routing/RoutingException.java` | Typed failure: `UNAVAILABLE`, `NO_ROUTE` |
| `…/service/RouteRiskService.java` | Route → corridor → aggregate → labels |
| `…/web/SegmentController.java` | `/api/segments*` |
| `…/web/RouteController.java` | `/api/route/risk`, `/api/geocode` |
| `…/web/ApiExceptionHandler.java` | Maps exceptions to status codes |

**`frontend/src/`** — additions and edits:

| File | Responsibility |
|---|---|
| `lib/riskScale.js` (new) | `scoreToDisplay()` — the only home for the band cutoffs |
| `lib/api.js` (new) | `fetch` wrapper for the backend |
| `routes/Route.jsx` / `.css` (new) | The route screen |
| `components/RouteCompare.jsx` / `.css` (new) | Comparison cards |
| `App.jsx` (modify) | Add `/route` |
| `components/Nav.jsx` (modify) | Add the link |
| `routes/Explorer.jsx` (modify) | Fixture → live API |
| `lib/riskScale.test.js` (new) | Vitest |

---

### Task 1: Backend scaffold that starts and answers

Nothing can be built or tested until Maven, the wrapper, and a running app exist. This task ends with `./mvnw test` green and the app booting without a database.

**Files:**
- Create: `backend/pom.xml`, `backend/.gitignore`, `backend/.env.example`
- Create: `backend/src/main/java/com/veyra/blackspot/BlackspotApplication.java`
- Create: `backend/src/main/java/com/veyra/blackspot/web/HealthController.java`
- Create: `backend/src/main/resources/application.yml`
- Create: `backend/src/test/java/com/veyra/blackspot/web/HealthControllerTest.java`

**Interfaces:**
- Produces: `GET /api/health` → `{"status":"ok"}`

- [ ] **Step 1: Write the build file**

Create `backend/pom.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>

  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.4.1</version>
    <relativePath/>
  </parent>

  <groupId>com.veyra</groupId>
  <artifactId>blackspot-api</artifactId>
  <version>0.1.0</version>
  <name>blackspot-api</name>

  <properties>
    <!-- 21, not 22: a teammate on the LTS JDK must be able to build this. -->
    <java.version>21</java.version>
  </properties>

  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-jdbc</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-validation</artifactId>
    </dependency>
    <dependency>
      <groupId>org.postgresql</groupId>
      <artifactId>postgresql</artifactId>
      <scope>runtime</scope>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-test</artifactId>
      <scope>test</scope>
    </dependency>
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
      </plugin>
    </plugins>
  </build>

  <profiles>
    <!--
      PostGIS tests need a live database; Docker is not running on the dev
      machine. They carry @Tag("postgis") and are excluded by default.

      The exclusion MUST live in a profile that deactivates when -Dgroups is
      supplied. A plain <excludedGroups>postgis</excludedGroups> in <build>
      cannot be overridden from the command line, so `-Dgroups=postgis` would
      intersect "only postgis" with "never postgis" and silently run ZERO
      tests while reporting success.
    -->
    <profile>
      <id>exclude-postgis</id>
      <activation>
        <property><name>!groups</name></property>
      </activation>
      <build>
        <plugins>
          <plugin>
            <groupId>org.apache.maven.plugins</groupId>
            <artifactId>maven-surefire-plugin</artifactId>
            <configuration>
              <excludedGroups>postgis</excludedGroups>
            </configuration>
          </plugin>
        </plugins>
      </build>
    </profile>
  </profiles>
</project>
```

- [ ] **Step 2: Add the Maven wrapper** — *done by the controller, 2026-09-03*

No global Maven is installed. **Do not fetch `mvnw` from the maven-wrapper GitHub
repo** — those are unfiltered build sources with `@@project.version@@`
placeholders that are never substituted, producing a wrapper that fails with
`ClassNotFoundException: org.apache.maven.wrapper.MavenWrapperMain`. A first
attempt at this task hit exactly that.

The working sequence, already applied:

```bash
cd "C:/Major Project/frontend-v1" && curl -fsSL -o maven.zip https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.9/apache-maven-3.9.9-bin.zip && unzip -q maven.zip && rm maven.zip
```

then, with `JAVA_HOME` set (see below), from `backend/`:

```bash
mvn -N wrapper:wrapper "-Dmaven=3.9.9"
```

That unpacks the `only-script` wrapper and writes a correct
`.mvn/wrapper/maven-wrapper.properties`. The extracted `apache-maven-3.9.9/`
sits outside the repo and is not committed; the wrapper is.

**`JAVA_HOME` is not set on this machine**, and Maven refuses to start without
it. JDK 22 lives at `C:\Program Files\Java\jdk-22`. Every Maven invocation in
this plan needs it:

```bash
export JAVA_HOME="/c/Program Files/Java/jdk-22"     # Git Bash
```
```powershell
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-22'     # PowerShell
```

Task 5's `backend/README.md` must state this as a prerequisite — a teammate
cloning the repo hits it immediately.

Verify before continuing; a broken wrapper blocks every later task:

```bash
cd backend && ./mvnw -v
```

Expected: `Apache Maven 3.9.9`, `Java version: 22.0.1`.

- [ ] **Step 3: Write the secret exclusions**

Create `backend/.gitignore`:

```
target/
.env
```

Create `backend/.env.example`:

```
# Copy to .env and fill in. .env is gitignored and must never be committed.
# Supabase → Settings → Database → Connection string
DATABASE_URL=jdbc:postgresql://HOST:5432/postgres?user=USER&password=PASSWORD&sslmode=require
# https://openrouteservice.org/dev/#/signup
ORS_API_KEY=
```

- [ ] **Step 4: Write the config**

Create `backend/src/main/resources/application.yml`:

```yaml
spring:
  application:
    name: blackspot-api
  datasource:
    # Absent at startup is fine — health and unit tests do not touch the DB.
    url: ${DATABASE_URL:}
  sql:
    init:
      mode: never

ors:
  api-key: ${ORS_API_KEY:}
  base-url: https://api.openrouteservice.org

blackspot:
  corridor-metres: 50
  min-crashes: 6
  max-segments: 2000

server:
  # 8080 is taken by Oracle's TNS Listener on the development machine.
  port: 8081

logging:
  level:
    com.veyra.blackspot: INFO
```

- [ ] **Step 5: Write the failing test**

Create `backend/src/test/java/com/veyra/blackspot/web/HealthControllerTest.java`:

```java
package com.veyra.blackspot.web;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(HealthController.class)
class HealthControllerTest {

    @Autowired
    MockMvc mvc;

    @Test
    void healthReportsOk() throws Exception {
        mvc.perform(get("/api/health"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.status").value("ok"));
    }
}
```

- [ ] **Step 6: Run it to verify it fails**

```bash
cd backend && ./mvnw -q test
```

Expected: FAIL — compilation error, `HealthController` does not exist.

- [ ] **Step 7: Write the implementation**

Create `backend/src/main/java/com/veyra/blackspot/BlackspotApplication.java`:

```java
package com.veyra.blackspot;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;

/**
 * DataSource auto-configuration is excluded at the class level and enabled
 * only when DATABASE_URL is present, so the app boots for health checks and
 * unit tests without a database.
 */
@SpringBootApplication(exclude = DataSourceAutoConfiguration.class)
public class BlackspotApplication {
    public static void main(String[] args) {
        SpringApplication.run(BlackspotApplication.class, args);
    }
}
```

Create `backend/src/main/java/com/veyra/blackspot/web/HealthController.java`:

```java
package com.veyra.blackspot.web;

import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {

    @GetMapping("/api/health")
    public Map<String, String> health() {
        return Map.of("status", "ok");
    }
}
```

- [ ] **Step 8: Run it to verify it passes**

```bash
cd backend && ./mvnw -q test
```

Expected: BUILD SUCCESS, 1 test passing.

- [ ] **Step 9: Commit**

```bash
git add backend/ && git commit -m "feat(backend): Spring Boot scaffold with health endpoint"
```

---

### Task 2: Parse `run` out of the segment id

The CSV has no `run` column, but the schema needs it and a road number can cover geographically separate stretches — crashes tagged `A503` appear 543 km apart. The id encodes it. A pure function, so this is straight TDD with no infrastructure.

**Files:**
- Create: `backend/src/main/java/com/veyra/blackspot/load/SegmentIdParser.java`
- Create: `backend/src/test/java/com/veyra/blackspot/load/SegmentIdParserTest.java`

**Interfaces:**
- Produces: `record ParsedId(String roadId, int run, double kmFrom)` and `static ParsedId parse(String segmentId)`, throwing `IllegalArgumentException` on a malformed id.

- [ ] **Step 1: Write the failing test**

Create `backend/src/test/java/com/veyra/blackspot/load/SegmentIdParserTest.java`:

```java
package com.veyra.blackspot.load;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SegmentIdParserTest {

    @Test
    void parsesRoadRunAndKilometre() {
        var p = SegmentIdParser.parse("A23_run3_km0.5");
        assertThat(p.roadId()).isEqualTo("A23");
        assertThat(p.run()).isEqualTo(3);
        assertThat(p.kmFrom()).isEqualTo(0.5);
    }

    @Test
    void parsesRunZero() {
        assertThat(SegmentIdParser.parse("A3220_run0_km6.0").run()).isZero();
    }

    @Test
    void parsesMotorwayAndBRoadNumbers() {
        assertThat(SegmentIdParser.parse("M25_run2_km60.0").roadId()).isEqualTo("M25");
        assertThat(SegmentIdParser.parse("B1234_run0_km1.5").roadId()).isEqualTo("B1234");
    }

    @Test
    void parsesAMotorwayClassContainingParentheses() {
        // class 2 renders as "A(M)", e.g. A1(M)
        assertThat(SegmentIdParser.parse("A(M)1_run0_km2.0").roadId()).isEqualTo("A(M)1");
    }

    @Test
    void parsesLargeKilometreValues() {
        assertThat(SegmentIdParser.parse("A1_run0_km128.5").kmFrom()).isEqualTo(128.5);
    }

    @Test
    void rejectsMalformedIdRatherThanDefaultingRunToZero() {
        assertThatThrownBy(() -> SegmentIdParser.parse("A23_km0.5"))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("A23_km0.5");
    }

    @Test
    void rejectsNullAndBlank() {
        assertThatThrownBy(() -> SegmentIdParser.parse(null))
            .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> SegmentIdParser.parse("  "))
            .isInstanceOf(IllegalArgumentException.class);
    }
}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && ./mvnw -q test -Dtest=SegmentIdParserTest
```

Expected: FAIL — `SegmentIdParser` does not exist.

- [ ] **Step 3: Write the implementation**

Create `backend/src/main/java/com/veyra/blackspot/load/SegmentIdParser.java`:

```java
package com.veyra.blackspot.load;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Segment ids encode road, stretch, and chainage: "A23_run3_km0.5".
 *
 * The exported CSV omits `run` as its own column, but it is not cosmetic —
 * one road number can cover geographically separate stretches (crashes tagged
 * A503 appear 543 km apart, though the A503 is a 10 km London road). Drawing a
 * road as one polyline requires it, so it is recovered here.
 *
 * A malformed id throws rather than defaulting run to 0, which would silently
 * merge distinct stretches into one line across open country.
 */
public final class SegmentIdParser {

    // Road id is greedy-free up to the literal "_run": it may contain
    // parentheses, as A(M) roads do.
    private static final Pattern ID = Pattern.compile("^(.+)_run(\\d+)_km([0-9]+(?:\\.[0-9]+)?)$");

    private SegmentIdParser() {
    }

    public record ParsedId(String roadId, int run, double kmFrom) {
    }

    public static ParsedId parse(String segmentId) {
        if (segmentId == null || segmentId.isBlank()) {
            throw new IllegalArgumentException("segment_id is null or blank");
        }
        Matcher m = ID.matcher(segmentId);
        if (!m.matches()) {
            throw new IllegalArgumentException(
                "segment_id does not match <road>_run<n>_km<d>: " + segmentId);
        }
        return new ParsedId(m.group(1), Integer.parseInt(m.group(2)), Double.parseDouble(m.group(3)));
    }
}
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd backend && ./mvnw -q test -Dtest=SegmentIdParserTest
```

Expected: 7 tests passing.

- [ ] **Step 5: Verify against the real data**

The regex must match all 45,014 ids, not just the seven above:

```bash
cd "C:/Major Project/frontend-v1/Veyra" && python -c "
import csv,re
p=re.compile(r'^(.+)_run(\d+)_km([0-9]+(?:\.[0-9]+)?)\$')
rows=list(csv.DictReader(open('data/road_segments_ranked.csv')))
bad=[r['segment_id'] for r in rows if not p.match(r['segment_id'])]
print('rows',len(rows),'unmatched',len(bad))
print('sample unmatched:',bad[:5])
"
```

Expected: `unmatched 0`. If any fail, widen the regex and add them as test cases before continuing — the loader aborts on a malformed id, so an unmatched row blocks the whole load.

- [ ] **Step 6: Commit**

```bash
git add backend/ && git commit -m "feat(backend): parse road/run/km from segment_id"
```

---

### Task 3: Schema and the domain record

The table and the Java record that mirrors it. No database connection yet — that comes with the loader.

**Files:**
- Create: `backend/src/main/resources/schema.sql`
- Create: `backend/src/main/java/com/veyra/blackspot/domain/Segment.java`
- Create: `backend/src/test/java/com/veyra/blackspot/domain/SegmentTest.java`

**Interfaces:**
- Produces: `record Segment(String segmentId, String roadId, int run, String location, double kmFrom, double kmTo, double lat, double lon, double blackspotScore, int rank, int nCrashes, int nKsi, int nFatal, Double ksiRate, Double crashesPerYear, Double speedMax, Double pctNight, Double pctJunction)` with `int nSerious()` derived.

- [ ] **Step 1: Write the schema**

Create `backend/src/main/resources/schema.sql`:

```sql
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
```

- [ ] **Step 2: Write the failing test**

Create `backend/src/test/java/com/veyra/blackspot/domain/SegmentTest.java`:

```java
package com.veyra.blackspot.domain;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SegmentTest {

    private static Segment segment(int nCrashes, int nKsi, int nFatal) {
        return new Segment("A23_run3_km0.5", "A23", 3, "A23 km 0.5-1.0 (seg 3)",
            0.5, 1.0, 51.4607, -0.1160, 9.67, 1,
            nCrashes, nKsi, nFatal, 0.167, 20.0, 30.0, 0.233, 0.7);
    }

    @Test
    void seriousIsKsiMinusFatal() {
        assertThat(segment(60, 10, 2).nSerious()).isEqualTo(8);
    }

    @Test
    void seriousIsZeroWhenEveryKsiWasFatal() {
        assertThat(segment(60, 3, 3).nSerious()).isZero();
    }

    @Test
    void thinlyEvidencedBelowSixCrashes() {
        // 86% of segments rest on fewer than 6 crashes; their scores are noise.
        assertThat(segment(5, 1, 0).thinlyEvidenced()).isTrue();
        assertThat(segment(6, 1, 0).thinlyEvidenced()).isFalse();
    }
}
```

- [ ] **Step 3: Run it to verify it fails**

```bash
cd backend && ./mvnw -q test -Dtest=SegmentTest
```

Expected: FAIL — `Segment` does not exist.

- [ ] **Step 4: Write the record**

Create `backend/src/main/java/com/veyra/blackspot/domain/Segment.java`:

```java
package com.veyra.blackspot.domain;

/**
 * One 500 m stretch of road.
 *
 * blackspotScore is expected killed-or-seriously-injured casualties on this
 * stretch over two years, across all traffic. It is a model output, not a
 * per-journey probability, and must never be presented as one.
 *
 * There is deliberately no futureKsi field. See schema.sql.
 */
public record Segment(
    String segmentId,
    String roadId,
    int run,
    String location,
    double kmFrom,
    double kmTo,
    double lat,
    double lon,
    double blackspotScore,
    int rank,
    int nCrashes,
    int nKsi,
    int nFatal,
    Double ksiRate,
    Double crashesPerYear,
    Double speedMax,
    Double pctNight,
    Double pctJunction
) {
    /** The dataset stores fatal and KSI; serious is the difference. */
    public int nSerious() {
        return nKsi - nFatal;
    }

    /**
     * 86% of segments rest on fewer than six crashes and their scores are
     * noisy. Consumers filter or grey these out rather than ranking them
     * against well-evidenced segments.
     */
    public boolean thinlyEvidenced() {
        return nCrashes < 6;
    }
}
```

- [ ] **Step 5: Run it to verify it passes**

```bash
cd backend && ./mvnw -q test
```

Expected: all tests passing.

- [ ] **Step 6: Commit**

```bash
git add backend/ && git commit -m "feat(backend): road_segment schema and Segment record"
```

---

### Task 4: CSV loader

Reads `data/road_segments_ranked.csv`, drops the two outcome columns, derives `run`, and inserts in batches. Runs only when `--load-data` is passed, so normal startup never touches it.

**Files:**
- Create: `backend/src/main/java/com/veyra/blackspot/load/SegmentCsvReader.java`
- Create: `backend/src/main/java/com/veyra/blackspot/load/SegmentLoader.java`
- Create: `backend/src/test/java/com/veyra/blackspot/load/SegmentCsvReaderTest.java`
- Create: `backend/src/test/resources/segments-sample.csv`

**Interfaces:**
- Consumes: `SegmentIdParser.parse`, `Segment`
- Produces: `SegmentCsvReader.read(Reader) -> List<Segment>`; `SegmentLoader` as a `CommandLineRunner`

The reader is separated from the loader so the parsing logic is testable with no database at all.

- [ ] **Step 1: Write the test fixture**

Create `backend/src/test/resources/segments-sample.csv` — the real header, three real rows, `future_ksi`/`future_fatal` present exactly as in the export:

```csv
rank,segment_id,location,road_id,km_from,km_to,lat,lon,blackspot_score,n_crashes,n_ksi,n_fatal,ksi_rate,crashes_per_year,speed_max,pct_night,pct_junction,future_ksi,future_fatal
1,A23_run3_km0.5,A23 km 0.5-1.0 (seg 3),A23,0.5,1.0,51.460757316666665,-0.11601963333333334,9.665665498389384,60,10,0,0.16666666666666666,20.0,30.0,0.23333333333333334,0.7,13.0,2.0
2,A3220_run0_km6.0,A3220 km 6.0-6.5,A3220,6.0,6.5,51.48392441666667,-0.17779218333333333,9.138733476078558,60,10,1,0.16666666666666666,20.0,30.0,0.05,0.7333333333333333,11.0,2.0
3,A3_run2_km0.5,A3 km 0.5-1.0 (seg 2),A3,0.5,1.0,51.46387298850575,-0.13249029885057473,8.62357131979668,87,14,0,0.16091954022988506,29.0,30.0,0.1724137931034483,0.896551724137931,10.0,1.0
```

- [ ] **Step 2: Write the failing test**

Create `backend/src/test/java/com/veyra/blackspot/load/SegmentCsvReaderTest.java`:

```java
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
```

- [ ] **Step 3: Run it to verify it fails**

```bash
cd backend && ./mvnw -q test -Dtest=SegmentCsvReaderTest
```

Expected: FAIL — `SegmentCsvReader` does not exist.

- [ ] **Step 4: Write the reader**

Create `backend/src/main/java/com/veyra/blackspot/load/SegmentCsvReader.java`:

```java
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
```

- [ ] **Step 5: Run it to verify it passes**

```bash
cd backend && ./mvnw -q test -Dtest=SegmentCsvReaderTest
```

Expected: 5 tests passing.

- [ ] **Step 6: Write the loader**

Create `backend/src/main/java/com/veyra/blackspot/load/SegmentLoader.java`:

```java
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
```

- [ ] **Step 7: Verify the suite is still green**

```bash
cd backend && ./mvnw -q test
```

Expected: all tests passing. `SegmentLoader` has no unit test — it is thin glue over `SegmentCsvReader`, which is fully tested, and the SQL is exercised by the PostGIS-tagged tests in Task 6.

- [ ] **Step 8: Commit**

```bash
git add backend/ && git commit -m "feat(backend): CSV reader and segment loader, dropping future_* columns"
```

---

### Task 5: Enable the database and apply the schema

The first task that needs your Supabase credentials. Everything before this runs without them.

**Files:**
- Modify: `backend/src/main/java/com/veyra/blackspot/BlackspotApplication.java`
- Create: `backend/README.md`

**Human prerequisite:** `backend/.env` must exist with a rotated `DATABASE_URL`. The connection string pasted into chat on 2026-09-03 is compromised and must not be used.

- [ ] **Step 1: Restore DataSource auto-configuration**

Task 1 excluded it so the app could boot without a database. Now it is needed. In `BlackspotApplication.java`, change:

```java
@SpringBootApplication(exclude = DataSourceAutoConfiguration.class)
```

to:

```java
@SpringBootApplication
```

and drop the now-unused import. `application.yml` already binds `${DATABASE_URL:}`; startup fails fast with a clear message when it is unset, which is the intended behaviour from here on.

- [ ] **Step 2: Write the run instructions**

Create `backend/README.md`:

```markdown
# blackspot-api

Spring Boot API over the blackspot segment data. Java 21+, no global Maven
needed — use the wrapper.

## Configure

    cp .env.example .env

Fill in both values. `.env` is gitignored; never commit it.

- `DATABASE_URL` — Supabase → Settings → Database → Connection string.
  Use whichever mode the dashboard offers for your network.
- `ORS_API_KEY` — https://openrouteservice.org/dev/#/signup

## Create the schema

Run `src/main/resources/schema.sql` once, in the Supabase dashboard's SQL
editor. It is destructive: it drops `road_segment` before recreating it.

## Load the data

    ./mvnw spring-boot:run -Dspring-boot.run.arguments=--load-data

Reads `../data/road_segments_ranked.csv` (45,014 rows) and truncates before
inserting, so re-running after a data refresh is safe.

## Run

    ./mvnw spring-boot:run

## Test

    ./mvnw test                    # unit tests, no database, no Docker
    ./mvnw test -Dgroups=postgis   # adds live PostGIS tests, needs DATABASE_URL
```

- [ ] **Step 3: Apply the schema (human step)**

Paste `backend/src/main/resources/schema.sql` into the Supabase SQL editor and run it. Verify:

```sql
SELECT column_name FROM information_schema.columns WHERE table_name = 'road_segment';
```

Expected: 17 columns, and **no `future_ksi` or `future_fatal`**.

- [ ] **Step 4: Load the data**

```bash
cd backend && ./mvnw spring-boot:run -Dspring-boot.run.arguments=--load-data
```

Expected final log line: `load complete: 45014 rows in road_segment`

- [ ] **Step 5: Commit**

```bash
git add backend/ && git commit -m "feat(backend): enable datasource, add setup and run instructions"
```

---

### Task 6: Segment repository

All SQL lives here, including the corridor query used in Task 9. Tests that need PostGIS carry `@Tag("postgis")` and are excluded from the default run.

**Files:**
- Create: `backend/src/main/java/com/veyra/blackspot/repo/SegmentRepository.java`
- Create: `backend/src/main/java/com/veyra/blackspot/repo/BoundingBox.java`
- Create: `backend/src/test/java/com/veyra/blackspot/repo/BoundingBoxTest.java`
- Create: `backend/src/test/java/com/veyra/blackspot/repo/SegmentRepositoryPostgisTest.java`

**Interfaces:**
- Produces: `Optional<Segment> findById(String)`, `List<Segment> findInBbox(BoundingBox, double minScore, int minCrashes, int limit)`, `List<Segment> findTop(int limit)`, `List<CorridorHit> findAlongRoute(String routeWkt, double corridorMetres, int minCrashes)`
- Produces: `record CorridorHit(Segment segment, double fraction)` — `fraction` is position along the route, 0–1
- Produces: `record BoundingBox(double minLon, double minLat, double maxLon, double maxLat)` with `static BoundingBox parse(String)`

- [ ] **Step 1: Write the failing test for bbox parsing**

Create `backend/src/test/java/com/veyra/blackspot/repo/BoundingBoxTest.java`:

```java
package com.veyra.blackspot.repo;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class BoundingBoxTest {

    @Test
    void parsesFourCommaSeparatedNumbers() {
        BoundingBox b = BoundingBox.parse("-0.51,51.28,0.34,51.70");
        assertThat(b.minLon()).isEqualTo(-0.51);
        assertThat(b.minLat()).isEqualTo(51.28);
        assertThat(b.maxLon()).isEqualTo(0.34);
        assertThat(b.maxLat()).isEqualTo(51.70);
    }

    @Test
    void rejectsWrongCardinality() {
        assertThatThrownBy(() -> BoundingBox.parse("-0.51,51.28,0.34"))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("bbox");
    }

    @Test
    void rejectsInvertedBounds() {
        assertThatThrownBy(() -> BoundingBox.parse("0.34,51.70,-0.51,51.28"))
            .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsNonNumeric() {
        assertThatThrownBy(() -> BoundingBox.parse("a,b,c,d"))
            .isInstanceOf(IllegalArgumentException.class);
    }
}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && ./mvnw -q test -Dtest=BoundingBoxTest
```

Expected: FAIL — `BoundingBox` does not exist.

- [ ] **Step 3: Write BoundingBox**

Create `backend/src/main/java/com/veyra/blackspot/repo/BoundingBox.java`:

```java
package com.veyra.blackspot.repo;

public record BoundingBox(double minLon, double minLat, double maxLon, double maxLat) {

    /** Parses "minLon,minLat,maxLon,maxLat", the order Leaflet reports. */
    public static BoundingBox parse(String s) {
        if (s == null || s.isBlank()) {
            throw new IllegalArgumentException("bbox is required");
        }
        String[] p = s.split(",");
        if (p.length != 4) {
            throw new IllegalArgumentException(
                "bbox needs 4 comma-separated numbers (minLon,minLat,maxLon,maxLat), got: " + s);
        }
        double[] v = new double[4];
        for (int i = 0; i < 4; i++) {
            try {
                v[i] = Double.parseDouble(p[i].trim());
            } catch (NumberFormatException e) {
                throw new IllegalArgumentException("bbox value " + (i + 1) + " is not a number: " + p[i]);
            }
        }
        if (v[0] >= v[2] || v[1] >= v[3]) {
            throw new IllegalArgumentException("bbox min must be less than max: " + s);
        }
        return new BoundingBox(v[0], v[1], v[2], v[3]);
    }
}
```

- [ ] **Step 4: Write the repository**

Create `backend/src/main/java/com/veyra/blackspot/repo/SegmentRepository.java`:

```java
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
```

- [ ] **Step 5: Write the PostGIS-tagged test**

Create `backend/src/test/java/com/veyra/blackspot/repo/SegmentRepositoryPostgisTest.java`:

```java
package com.veyra.blackspot.repo;

import java.util.List;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Exercises the real PostGIS functions against the loaded Supabase database.
 * Excluded from the default build (no Docker, no credentials in CI):
 *
 *   ./mvnw test -Dgroups=postgis
 */
@Tag("postgis")
@SpringBootTest
class SegmentRepositoryPostgisTest {

    @Autowired
    SegmentRepository repo;

    @Test
    void findsTheKnownWorstSegment() {
        var s = repo.findById("A23_run3_km0.5");
        assertThat(s).isPresent();
        assertThat(s.get().roadId()).isEqualTo("A23");
        assertThat(s.get().run()).isEqualTo(3);
        assertThat(s.get().nCrashes()).isEqualTo(60);
    }

    @Test
    void bboxOverCentralLondonReturnsSegments() {
        var rows = repo.findInBbox(BoundingBox.parse("-0.51,51.28,0.34,51.70"), 0, 6, 100);
        assertThat(rows).isNotEmpty().hasSizeLessThanOrEqualTo(100);
        assertThat(rows).isSortedAccordingTo(
            (a, b) -> Double.compare(b.blackspotScore(), a.blackspotScore()));
    }

    @Test
    void corridorAlongTheA23ReturnsHitsOrderedByPosition() {
        // A short LineString down the A23 through Brixton
        String wkt = "LINESTRING(-0.1160 51.4607, -0.1150 51.4650, -0.1140 51.4700)";
        List<SegmentRepository.CorridorHit> hits = repo.findAlongRoute(wkt, 100, 1);
        assertThat(hits).isNotEmpty();
        assertThat(hits).isSortedAccordingTo(
            (a, b) -> Double.compare(a.fraction(), b.fraction()));
        assertThat(hits).allSatisfy(h ->
            assertThat(h.fraction()).isBetween(0.0, 1.0));
    }

    @Test
    void minCrashesFilterExcludesThinlyEvidencedSegments() {
        String wkt = "LINESTRING(-0.1160 51.4607, -0.1140 51.4700)";
        var strict = repo.findAlongRoute(wkt, 200, 6);
        var loose = repo.findAlongRoute(wkt, 200, 1);

        // The loose query must actually contain segments the strict one
        // filters out, otherwise the size comparison proves nothing: a filter
        // that did nothing would return identical sets and still pass <=.
        assertThat(loose).anySatisfy(h ->
            assertThat(h.segment().nCrashes()).isLessThan(6));
        assertThat(strict).allSatisfy(h ->
            assertThat(h.segment().nCrashes()).isGreaterThanOrEqualTo(6));
        assertThat(strict.size()).isLessThan(loose.size());
    }
}
```

- [ ] **Step 6: Run the unit tests, then the tagged ones**

```bash
cd backend && ./mvnw -q test
```

Expected: all pass, PostGIS tests skipped.

```bash
cd backend && ./mvnw test -Dgroups=postgis
```

Expected: 4 more passing. Requires Task 5's load to have completed.

- [ ] **Step 7: Commit**

```bash
git add backend/ && git commit -m "feat(backend): segment repository with PostGIS corridor query"
```

---

### Task 7: Segment endpoints

**Files:**
- Create: `backend/src/main/java/com/veyra/blackspot/web/SegmentController.java`
- Create: `backend/src/main/java/com/veyra/blackspot/web/ApiExceptionHandler.java`
- Create: `backend/src/main/java/com/veyra/blackspot/routing/RoutingException.java`
- Create: `backend/src/test/java/com/veyra/blackspot/web/SegmentControllerTest.java`

`RoutingException` is created here, not in Task 8, because `ApiExceptionHandler`
imports it and would not compile otherwise. Task 8 uses it; it does not create it.

**Interfaces:**
- Consumes: `SegmentRepository`, `BoundingBox`
- Produces: `GET /api/segments`, `GET /api/segments/{id}`

- [ ] **Step 1: Write the failing test**

Create `backend/src/test/java/com/veyra/blackspot/web/SegmentControllerTest.java`:

```java
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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && ./mvnw -q test -Dtest=SegmentControllerTest
```

Expected: FAIL — `SegmentController` does not exist.

- [ ] **Step 3: Write the exception handler**

First create the exception it maps, `backend/src/main/java/com/veyra/blackspot/routing/RoutingException.java`:

```java
package com.veyra.blackspot.routing;

public class RoutingException extends RuntimeException {

    public enum Kind { NO_ROUTE, UNAVAILABLE }

    private final Kind kind;

    public RoutingException(Kind kind, String message) {
        super(message);
        this.kind = kind;
    }

    public RoutingException(Kind kind, String message, Throwable cause) {
        super(message, cause);
        this.kind = kind;
    }

    public Kind kind() {
        return kind;
    }
}
```

Then create `backend/src/main/java/com/veyra/blackspot/web/ApiExceptionHandler.java`:

```java
package com.veyra.blackspot.web;

import java.util.Map;

import com.veyra.blackspot.routing.RoutingException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("message", e.getMessage()));
    }

    @ExceptionHandler(NotFoundException.class)
    public ResponseEntity<Map<String, String>> notFound(NotFoundException e) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("message", e.getMessage()));
    }

    @ExceptionHandler(RoutingException.class)
    public ResponseEntity<Map<String, String>> routing(RoutingException e) {
        HttpStatus status = switch (e.kind()) {
            case NO_ROUTE -> HttpStatus.UNPROCESSABLE_ENTITY;
            case UNAVAILABLE -> HttpStatus.SERVICE_UNAVAILABLE;
        };
        return ResponseEntity.status(status).body(Map.of("message", e.getMessage()));
    }

    public static class NotFoundException extends RuntimeException {
        public NotFoundException(String message) {
            super(message);
        }
    }
}
```

- [ ] **Step 4: Write the controller**

Create `backend/src/main/java/com/veyra/blackspot/web/SegmentController.java`:

```java
package com.veyra.blackspot.web;

import java.util.List;

import com.veyra.blackspot.domain.Segment;
import com.veyra.blackspot.repo.BoundingBox;
import com.veyra.blackspot.repo.SegmentRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class SegmentController {

    private final SegmentRepository repo;
    private final int maxSegments;

    public SegmentController(SegmentRepository repo,
                             @Value("${blackspot.max-segments}") int maxSegments) {
        this.repo = repo;
        this.maxSegments = maxSegments;
    }

    @GetMapping("/api/segments")
    public List<Segment> segments(
            @RequestParam(required = false) String bbox,
            @RequestParam(defaultValue = "0") double minScore,
            @RequestParam(defaultValue = "6") int minCrashes,
            @RequestParam(defaultValue = "500") int limit) {

        if (limit < 1 || limit > maxSegments) {
            throw new IllegalArgumentException("limit must be between 1 and " + maxSegments);
        }
        return bbox == null
            ? repo.findTop(limit)
            : repo.findInBbox(BoundingBox.parse(bbox), minScore, minCrashes, limit);
    }

    @GetMapping("/api/segments/{segmentId}")
    public Segment segment(@PathVariable String segmentId) {
        return repo.findById(segmentId).orElseThrow(
            () -> new ApiExceptionHandler.NotFoundException("no segment " + segmentId));
    }
}
```

- [ ] **Step 5: Run it to verify it passes**

```bash
cd backend && ./mvnw -q test
```

Expected: all tests passing.

- [ ] **Step 6: Commit**

```bash
git add backend/ && git commit -m "feat(backend): segment endpoints with bbox and limit validation"
```

---

### Task 8: Routing client

HTTP only, no domain logic. The interface is what makes `RouteRiskService` testable without a network.

**Files:**
- Create: `backend/src/main/java/com/veyra/blackspot/routing/RoutingClient.java`
- Create: `backend/src/main/java/com/veyra/blackspot/routing/OrsRoutingClient.java`
- Create: `backend/src/main/java/com/veyra/blackspot/config/OrsProperties.java`
- Create: `backend/src/main/java/com/veyra/blackspot/domain/RouteRisk.java`
- Create: `backend/src/test/java/com/veyra/blackspot/config/OrsPropertiesTest.java`

**Interfaces:**
- Produces: `record Coord(double lon, double lat)`, `record RawRoute(List<Coord> geometry, double distanceMetres, double durationSeconds)`, `record GeocodeCandidate(String label, double lon, double lat)`
- Produces: `RoutingClient.route(Coord from, Coord to, int alternatives) -> List<RawRoute>`, `RoutingClient.geocode(String query) -> List<GeocodeCandidate>`
- Produces: `RoutingException.Kind { NO_ROUTE, UNAVAILABLE }`

- [ ] **Step 1: Write the domain records**

Create `backend/src/main/java/com/veyra/blackspot/domain/RouteRisk.java`:

```java
package com.veyra.blackspot.domain;

import java.util.List;

/** Records exchanged by the routing and route-risk layers. */
public final class RouteRisk {

    private RouteRisk() {
    }

    /** Longitude first, matching GeoJSON and ORS. */
    public record Coord(double lon, double lat) {
    }

    /** A route as the routing provider returned it, before any scoring. */
    public record RawRoute(List<Coord> geometry, double distanceMetres, double durationSeconds) {
    }

    public record GeocodeCandidate(String label, double lon, double lat) {
    }

    /** A blackspot on a route, with how far along it sits. */
    public record BlackspotOnRoute(
        String segmentId, String location, double lat, double lon,
        double blackspotScore, int nCrashes, int nKsi, int nFatal,
        Double speedMax, double metresAlongRoute, boolean thinlyEvidenced) {
    }

    /**
     * expectedKsi is expected killed-or-seriously-injured casualties on this
     * corridor over two years, ACROSS ALL TRAFFIC. It is not a per-journey
     * risk and must never be presented as one.
     */
    public record ScoredRoute(
        int index, String label,
        double distanceMetres, double durationSeconds,
        List<Coord> geometry,
        double expectedKsi, int blackspotCount, String worstSegmentId,
        List<BlackspotOnRoute> blackspots) {
    }

    public record RouteRiskResponse(List<ScoredRoute> routes, String coverageWarning) {
    }
}
```

- [ ] **Step 2: Write the failing test for key validation**

Create `backend/src/test/java/com/veyra/blackspot/config/OrsPropertiesTest.java`:

```java
package com.veyra.blackspot.config;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class OrsPropertiesTest {

    @Test
    void aBlankKeyFailsFastWithANamedError() {
        var p = new OrsProperties("", "https://api.openrouteservice.org");
        assertThatThrownBy(p::validate)
            .isInstanceOf(IllegalStateException.class)
            .hasMessageContaining("ORS_API_KEY");
    }

    @Test
    void aPresentKeyValidates() {
        var p = new OrsProperties("abc123", "https://api.openrouteservice.org");
        assertThatCode(p::validate).doesNotThrowAnyException();
    }
}
```

- [ ] **Step 3: Run it to verify it fails**

```bash
cd backend && ./mvnw -q test -Dtest=OrsPropertiesTest
```

Expected: FAIL — `OrsProperties` does not exist.

- [ ] **Step 4: Write the config and client**

Create `backend/src/main/java/com/veyra/blackspot/config/OrsProperties.java`:

```java
package com.veyra.blackspot.config;

import jakarta.annotation.PostConstruct;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Fails at startup rather than at the first request, so a missing key is a
 * boot error with a name on it instead of a 500 during a demo.
 */
@Component
@ConfigurationProperties(prefix = "ors")
public class OrsProperties {

    private String apiKey;
    private String baseUrl;

    public OrsProperties() {
    }

    public OrsProperties(String apiKey, String baseUrl) {
        this.apiKey = apiKey;
        this.baseUrl = baseUrl;
    }

    @PostConstruct
    public void validate() {
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalStateException(
                "ORS_API_KEY is not set. Copy backend/.env.example to backend/.env "
                + "and add a key from https://openrouteservice.org/dev/#/signup");
        }
    }

    public String getApiKey() {
        return apiKey;
    }

    public void setApiKey(String apiKey) {
        this.apiKey = apiKey;
    }

    public String getBaseUrl() {
        return baseUrl;
    }

    public void setBaseUrl(String baseUrl) {
        this.baseUrl = baseUrl;
    }
}
```

`RoutingException` already exists from Task 7. Do not recreate it.

Create `backend/src/main/java/com/veyra/blackspot/routing/RoutingClient.java`:

```java
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
```

Create `backend/src/main/java/com/veyra/blackspot/routing/OrsRoutingClient.java`:

```java
package com.veyra.blackspot.routing;

import java.net.URI;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.veyra.blackspot.config.OrsProperties;
import com.veyra.blackspot.domain.RouteRisk.Coord;
import com.veyra.blackspot.domain.RouteRisk.GeocodeCandidate;
import com.veyra.blackspot.domain.RouteRisk.RawRoute;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * OpenRouteService. Called server-side only, so the key never reaches a browser.
 *
 * ORS returns alternatives only when the request carries no via points, which
 * is why this client takes exactly two coordinates.
 */
@Component
public class OrsRoutingClient implements RoutingClient {

    private final RestTemplate http = new RestTemplate();
    private final OrsProperties props;

    public OrsRoutingClient(OrsProperties props) {
        this.props = props;
    }

    @Override
    public List<RawRoute> route(Coord from, Coord to, int alternatives) {
        String url = props.getBaseUrl() + "/v2/directions/driving-car/geojson";

        Map<String, Object> body = alternatives > 1
            ? Map.of("coordinates", List.of(List.of(from.lon(), from.lat()),
                                            List.of(to.lon(), to.lat())),
                     "alternative_routes", Map.of("target_count", alternatives,
                                                  "share_factor", 0.6,
                                                  "weight_factor", 1.6))
            : Map.of("coordinates", List.of(List.of(from.lon(), from.lat()),
                                            List.of(to.lon(), to.lat())));

        HttpHeaders h = new HttpHeaders();
        h.set(HttpHeaders.AUTHORIZATION, props.getApiKey());
        h.setContentType(MediaType.APPLICATION_JSON);

        JsonNode root;
        try {
            root = http.postForObject(URI.create(url), new HttpEntity<>(body, h), JsonNode.class);
        } catch (RestClientException e) {
            throw new RoutingException(RoutingException.Kind.UNAVAILABLE,
                "routing service unavailable", e);
        }
        if (root == null || !root.has("features") || root.get("features").isEmpty()) {
            throw new RoutingException(RoutingException.Kind.NO_ROUTE,
                "no drivable route between those points");
        }

        List<RawRoute> out = new ArrayList<>();
        for (JsonNode f : root.get("features")) {
            JsonNode summary = f.path("properties").path("summary");
            List<Coord> line = new ArrayList<>();
            for (JsonNode c : f.path("geometry").path("coordinates")) {
                line.add(new Coord(c.get(0).asDouble(), c.get(1).asDouble()));
            }
            out.add(new RawRoute(line,
                summary.path("distance").asDouble(),
                summary.path("duration").asDouble()));
        }
        return out;
    }

    @Override
    public List<GeocodeCandidate> geocode(String query) {
        String url = UriComponentsBuilder.fromUriString(props.getBaseUrl() + "/geocode/search")
            .queryParam("api_key", props.getApiKey())
            .queryParam("text", query)
            .queryParam("boundary.country", "GB")
            .queryParam("size", 5)
            .toUriString();

        JsonNode root;
        try {
            root = http.getForObject(URI.create(url), JsonNode.class);
        } catch (RestClientException e) {
            throw new RoutingException(RoutingException.Kind.UNAVAILABLE,
                "geocoding service unavailable", e);
        }
        List<GeocodeCandidate> out = new ArrayList<>();
        if (root == null) {
            return out;
        }
        for (JsonNode f : root.path("features")) {
            JsonNode c = f.path("geometry").path("coordinates");
            out.add(new GeocodeCandidate(
                f.path("properties").path("label").asText(),
                c.get(0).asDouble(), c.get(1).asDouble()));
        }
        return out;
    }
}
```

- [ ] **Step 5: Run it to verify it passes**

```bash
cd backend && ./mvnw -q test
```

Expected: all tests passing.

- [ ] **Step 6: Commit**

```bash
git add backend/ && git commit -m "feat(backend): ORS routing client behind a testable interface"
```

---

### Task 9: Route risk service

Where routing meets blackspots. Fully unit-tested against a fake client and a stub repository — no network, no database.

**Files:**
- Create: `backend/src/main/java/com/veyra/blackspot/service/RouteRiskService.java`
- Create: `backend/src/test/java/com/veyra/blackspot/service/RouteRiskServiceTest.java`

**Interfaces:**
- Consumes: `RoutingClient`, `SegmentRepository`
- Produces: `RouteRiskResponse assess(Coord from, Coord to, int minCrashes, double corridorMetres)`

**Amendment — make the ORS alternative-route parameters configurable.**

I measured the actual geometric overlap between ORS alternatives for
Croydon → Camden (fraction of a route's coordinates lying within 50 m of the
fastest route):

| `share_factor` / `weight_factor` | overlap with route 0 | distance | time |
|---|---|---|---|
| 0.6 / 1.6 | **45.8%, 45.6%** | 22.3 km | 63 min |
| 0.4 / 1.6 | 28.6%, 34.1% | 24.7 km | 64 min |
| **0.2 / 2.0** | **1.9%, 7.0%** | 27.4 km | 67 min |

At 0.6 the alternatives share nearly half their geometry with the fastest
route, so they traverse many of the same segments and the fastest-vs-safest
comparison degenerates into near-identical cards — which removes the reason
this feature exists.

So: move `target_count`, `share_factor` and `weight_factor` out of
`OrsRoutingClient`'s hardcoded map and into `application.yml` under
`ors.alternatives`, defaulting to `target_count: 3`, `share_factor: 0.2`,
`weight_factor: 2.0`. Bind them on `OrsProperties`. This makes them tunable at
demo time without a rebuild, which matters because the right value depends on
the road network around whichever endpoints get demonstrated.

Then, as part of Step 4's verification, report the real blackspot counts per
route for one London pair. If all routes still return identical counts, say so
— that is the signal that the comparison needs different endpoints or further
tuning, and it is better known now than at Task 13.

- [ ] **Step 1: Write the failing test**

Create `backend/src/test/java/com/veyra/blackspot/service/RouteRiskServiceTest.java`:

```java
package com.veyra.blackspot.service;

import java.util.List;

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

        var svc = new RouteRiskService(fakeClient(List.of(route(10_000, 600))), repo);
        var out = svc.assess(LONDON_S, LONDON_N, 6, 50);

        assertThat(out.routes().get(0).blackspots())
            .extracting("segmentId").containsExactly("near", "mid", "far");
    }

    @Test
    void metresAlongRouteScalesTheFractionByDistance() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt()))
            .thenReturn(List.of(new CorridorHit(seg("a", 1.0, 10), 0.25)));

        var svc = new RouteRiskService(fakeClient(List.of(route(10_000, 600))), repo);
        var out = svc.assess(LONDON_S, LONDON_N, 6, 50);

        assertThat(out.routes().get(0).blackspots().get(0).metresAlongRoute()).isEqualTo(2500.0);
    }

    @Test
    void expectedKsiIsTheSumOfSegmentScores() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt())).thenReturn(List.of(
            new CorridorHit(seg("a", 1.5, 10), 0.1),
            new CorridorHit(seg("b", 2.5, 10), 0.6)));

        var svc = new RouteRiskService(fakeClient(List.of(route(10_000, 600))), repo);
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
            fakeClient(List.of(route(18_000, 2040), route(19_800, 2340))), repo);
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
            fakeClient(List.of(route(18_000, 2040), route(19_800, 2340))), repo);
        var out = svc.assess(LONDON_S, LONDON_N, 6, 50);

        assertThat(out.routes().get(0).label()).isEqualTo("Fastest and safest");
        assertThat(out.routes().get(1).label()).isEqualTo("Alternative");
    }

    @Test
    void aRouteWithNoBlackspotsIsAValidResultNotAnError() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt())).thenReturn(List.of());

        var svc = new RouteRiskService(fakeClient(List.of(route(10_000, 600))), repo);
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
            fakeClient(List.of(new RawRoute(List.of(paris, lyon), 465_000, 16_000))), repo);
        var out = svc.assess(paris, lyon, 6, 50);

        assertThat(out.coverageWarning()).contains("Great Britain");
    }

    @Test
    void thinlyEvidencedSegmentsAreFlaggedNotHidden() {
        var repo = mock(SegmentRepository.class);
        when(repo.findAlongRoute(anyString(), anyDouble(), anyInt()))
            .thenReturn(List.of(new CorridorHit(seg("thin", 1.0, 3), 0.5)));

        var svc = new RouteRiskService(fakeClient(List.of(route(10_000, 600))), repo);
        var out = svc.assess(LONDON_S, LONDON_N, 1, 50);

        assertThat(out.routes().get(0).blackspots().get(0).thinlyEvidenced()).isTrue();
    }
}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && ./mvnw -q test -Dtest=RouteRiskServiceTest
```

Expected: FAIL — `RouteRiskService` does not exist.

- [ ] **Step 3: Write the service**

Create `backend/src/main/java/com/veyra/blackspot/service/RouteRiskService.java`:

```java
package com.veyra.blackspot.service;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.StringJoiner;

import com.veyra.blackspot.domain.RouteRisk.BlackspotOnRoute;
import com.veyra.blackspot.domain.RouteRisk.Coord;
import com.veyra.blackspot.domain.RouteRisk.RawRoute;
import com.veyra.blackspot.domain.RouteRisk.RouteRiskResponse;
import com.veyra.blackspot.domain.RouteRisk.ScoredRoute;
import com.veyra.blackspot.repo.SegmentRepository;
import com.veyra.blackspot.repo.SegmentRepository.CorridorHit;
import com.veyra.blackspot.routing.RoutingClient;
import org.springframework.stereotype.Service;

/**
 * Route -> corridor match -> aggregate.
 *
 * expectedKsi is the sum of the matched segments' scores: expected
 * killed-or-seriously-injured casualties on that corridor over two years,
 * across all traffic. It is NOT a per-journey risk. The API returns the raw
 * number and the UI is responsible for saying so.
 */
@Service
public class RouteRiskService {

    private static final int ALTERNATIVES = 3;

    /** Generous bounds for Great Britain, the extent of the STATS19 data. */
    private static final double GB_MIN_LON = -8.7, GB_MAX_LON = 2.0;
    private static final double GB_MIN_LAT = 49.8, GB_MAX_LAT = 61.0;

    private final RoutingClient routing;
    private final SegmentRepository repo;

    public RouteRiskService(RoutingClient routing, SegmentRepository repo) {
        this.routing = routing;
        this.repo = repo;
    }

    public RouteRiskResponse assess(Coord from, Coord to, int minCrashes, double corridorMetres) {
        List<RawRoute> raw = routing.route(from, to, ALTERNATIVES);

        List<ScoredRoute> scored = new ArrayList<>();
        for (int i = 0; i < raw.size(); i++) {
            scored.add(score(i, raw.get(i), minCrashes, corridorMetres));
        }
        scored = label(scored);

        boolean covered = raw.stream().flatMap(r -> r.geometry().stream()).anyMatch(
            c -> c.lon() >= GB_MIN_LON && c.lon() <= GB_MAX_LON
              && c.lat() >= GB_MIN_LAT && c.lat() <= GB_MAX_LAT);

        return new RouteRiskResponse(scored, covered ? null
            : "Blackspot data covers Great Britain only; no coverage for this route.");
    }

    private ScoredRoute score(int index, RawRoute r, int minCrashes, double corridorMetres) {
        List<CorridorHit> hits = repo.findAlongRoute(toWkt(r.geometry()), corridorMetres, minCrashes);

        List<BlackspotOnRoute> blackspots = new ArrayList<>();
        double expectedKsi = 0;
        String worst = null;
        double worstScore = -1;

        for (CorridorHit h : hits) {
            var s = h.segment();
            expectedKsi += s.blackspotScore();
            if (s.blackspotScore() > worstScore) {
                worstScore = s.blackspotScore();
                worst = s.segmentId();
            }
            blackspots.add(new BlackspotOnRoute(
                s.segmentId(), s.location(), s.lat(), s.lon(),
                s.blackspotScore(), s.nCrashes(), s.nKsi(), s.nFatal(), s.speedMax(),
                h.fraction() * r.distanceMetres(), s.thinlyEvidenced()));
        }

        return new ScoredRoute(index, "Alternative", r.distanceMetres(), r.durationSeconds(),
            r.geometry(), round(expectedKsi), blackspots.size(), worst, blackspots);
    }

    /**
     * Labels are assigned across the set, not per route: the quickest is
     * "Fastest", the least risky is "Safest", and one route can be both.
     */
    private List<ScoredRoute> label(List<ScoredRoute> routes) {
        if (routes.isEmpty()) {
            return routes;
        }
        int fastest = 0, safest = 0;
        for (int i = 1; i < routes.size(); i++) {
            if (routes.get(i).durationSeconds() < routes.get(fastest).durationSeconds()) {
                fastest = i;
            }
            if (routes.get(i).expectedKsi() < routes.get(safest).expectedKsi()) {
                safest = i;
            }
        }
        List<ScoredRoute> out = new ArrayList<>(routes.size());
        for (int i = 0; i < routes.size(); i++) {
            String label = i == fastest && i == safest ? "Fastest and safest"
                         : i == fastest ? "Fastest"
                         : i == safest ? "Safest"
                         : "Alternative";
            var r = routes.get(i);
            out.add(new ScoredRoute(r.index(), label, r.distanceMetres(), r.durationSeconds(),
                r.geometry(), r.expectedKsi(), r.blackspotCount(), r.worstSegmentId(),
                r.blackspots()));
        }
        return out;
    }

    /** PostGIS WKT. Longitude first, matching the SRID 4326 axis order used here. */
    static String toWkt(List<Coord> line) {
        StringJoiner j = new StringJoiner(",", "LINESTRING(", ")");
        for (Coord c : line) {
            j.add(String.format(Locale.ROOT, "%.6f %.6f", c.lon(), c.lat()));
        }
        return j.toString();
    }

    private static double round(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
```

- [ ] **Step 4: Run it to verify it passes**

```bash
cd backend && ./mvnw -q test -Dtest=RouteRiskServiceTest
```

Expected: 8 tests passing.

- [ ] **Step 5: Commit**

```bash
git add backend/ && git commit -m "feat(backend): route risk service with corridor matching and route labels"
```

---

### Task 10: Route and geocode endpoints

**Files:**
- Create: `backend/src/main/java/com/veyra/blackspot/web/RouteController.java`
- Create: `backend/src/main/java/com/veyra/blackspot/web/RouteRiskRequest.java`
- Create: `backend/src/main/java/com/veyra/blackspot/config/WebConfig.java`
- Create: `backend/src/test/java/com/veyra/blackspot/web/RouteControllerTest.java`

**Interfaces:**
- Consumes: `RouteRiskService`, `RoutingClient`
- Produces: `POST /api/route/risk`, `GET /api/geocode?q=`

- [ ] **Step 1: Write the failing test**

Create `backend/src/test/java/com/veyra/blackspot/web/RouteControllerTest.java`:

```java
package com.veyra.blackspot.web;

import java.util.List;

import com.veyra.blackspot.domain.RouteRisk.Coord;
import com.veyra.blackspot.domain.RouteRisk.GeocodeCandidate;
import com.veyra.blackspot.domain.RouteRisk.RouteRiskResponse;
import com.veyra.blackspot.domain.RouteRisk.ScoredRoute;
import com.veyra.blackspot.routing.RoutingClient;
import com.veyra.blackspot.routing.RoutingException;
import com.veyra.blackspot.service.RouteRiskService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest({RouteController.class, ApiExceptionHandler.class})
class RouteControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean RouteRiskService service;
    @MockitoBean RoutingClient routing;

    private static final String BODY = """
        {"from":[-0.0982,51.3762],"to":[-0.1426,51.5390],"minCrashes":6}
        """;

    @Test
    void returnsScoredRoutes() throws Exception {
        when(service.assess(any(), any(), anyInt(), anyDouble())).thenReturn(
            new RouteRiskResponse(List.of(new ScoredRoute(
                0, "Fastest", 18240, 2040, List.of(new Coord(-0.098, 51.376)),
                4.23, 6, "A23_run3_km0.5", List.of())), null));

        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON).content(BODY))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.routes[0].label").value("Fastest"))
           .andExpect(jsonPath("$.routes[0].expectedKsi").value(4.23))
           .andExpect(jsonPath("$.routes[0].blackspotCount").value(6));
    }

    @Test
    void routingUnavailableIsFiveOhThree() throws Exception {
        when(service.assess(any(), any(), anyInt(), anyDouble())).thenThrow(
            new RoutingException(RoutingException.Kind.UNAVAILABLE, "routing service unavailable"));

        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON).content(BODY))
           .andExpect(status().isServiceUnavailable());
    }

    @Test
    void noRouteIsFourTwentyTwo() throws Exception {
        when(service.assess(any(), any(), anyInt(), anyDouble())).thenThrow(
            new RoutingException(RoutingException.Kind.NO_ROUTE, "no drivable route"));

        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON).content(BODY))
           .andExpect(status().isUnprocessableEntity());
    }

    @Test
    void aMalformedCoordinatePairIsFourHundred() throws Exception {
        mvc.perform(post("/api/route/risk").contentType(MediaType.APPLICATION_JSON)
                    .content("""
                        {"from":[-0.0982],"to":[-0.1426,51.5390]}
                        """))
           .andExpect(status().isBadRequest());
    }

    @Test
    void geocodeReturnsCandidates() throws Exception {
        when(routing.geocode(anyString())).thenReturn(
            List.of(new GeocodeCandidate("Croydon, England", -0.0982, 51.3762)));

        mvc.perform(get("/api/geocode?q=croydon"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0].label").value("Croydon, England"));
    }

    @Test
    void geocodeWithNoMatchIsAnEmptyListNotAnError() throws Exception {
        when(routing.geocode(anyString())).thenReturn(List.of());
        mvc.perform(get("/api/geocode?q=zzzzzz"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isEmpty());
    }
}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && ./mvnw -q test -Dtest=RouteControllerTest
```

Expected: FAIL — `RouteController` does not exist.

- [ ] **Step 3: Write the request record**

Create `backend/src/main/java/com/veyra/blackspot/web/RouteRiskRequest.java`:

```java
package com.veyra.blackspot.web;

import com.veyra.blackspot.domain.RouteRisk.Coord;

/** from/to are [lon, lat], matching GeoJSON. */
public record RouteRiskRequest(double[] from, double[] to, Integer minCrashes,
                               Double corridorMetres) {

    public Coord fromCoord() {
        return coord(from, "from");
    }

    public Coord toCoord() {
        return coord(to, "to");
    }

    private static Coord coord(double[] v, String name) {
        if (v == null || v.length != 2) {
            throw new IllegalArgumentException(name + " must be [lon, lat]");
        }
        if (v[0] < -180 || v[0] > 180 || v[1] < -90 || v[1] > 90) {
            throw new IllegalArgumentException(name + " is not a valid [lon, lat] pair");
        }
        return new Coord(v[0], v[1]);
    }
}
```

- [ ] **Step 4: Write the controller and CORS config**

Create `backend/src/main/java/com/veyra/blackspot/web/RouteController.java`:

```java
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
```

Create `backend/src/main/java/com/veyra/blackspot/config/WebConfig.java`:

```java
package com.veyra.blackspot.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/** The Vite dev server runs on a different port, so it needs CORS in development. */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**")
                .allowedOrigins("http://localhost:5173", "http://127.0.0.1:5173")
                .allowedMethods("GET", "POST");
    }
}
```

- [ ] **Step 5: Run the whole suite**

```bash
cd backend && ./mvnw -q test
```

Expected: all tests passing.

- [ ] **Step 6: Smoke-test against the real services**

Requires `.env` with both values, and the Task 5 load complete.

```bash
cd backend && ./mvnw spring-boot:run
```

Then in another shell:

```bash
curl -s -X POST localhost:8081/api/route/risk -H 'Content-Type: application/json' -d '{"from":[-0.0982,51.3762],"to":[-0.1426,51.5390]}' | head -40
```

Expected: JSON with a `routes` array, each entry carrying `label`, `expectedKsi`, and a `blackspots` list. **Verify no `futureKsi` appears anywhere in the output.**

- [ ] **Step 7: Commit**

```bash
git add backend/ && git commit -m "feat(backend): route risk and geocode endpoints with CORS"
```

---

### Task 11: Frontend risk scale

The one place the score-to-tier mapping lives. Pure function, so it is tested first and separately.

**Files:**
- Create: `frontend/src/lib/riskScale.js`
- Create: `frontend/src/lib/riskScale.test.js`
- Modify: `frontend/package.json`
- Create: `frontend/vitest.config.js`

**Interfaces:**
- Produces: `scoreToDisplay(blackspotScore) -> number` (0–100), `formatExpectedKsi(value) -> string`

- [ ] **Step 1: Add Vitest**

```bash
cd frontend && npm install --save-dev vitest@^2.1.8
```

Add to `frontend/package.json` scripts: `"test": "vitest run"`.

Create `frontend/vitest.config.js`:

```js
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: { environment: 'node', include: ['src/**/*.test.js'] },
});
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/lib/riskScale.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { scoreToDisplay, formatExpectedKsi } from './riskScale.js';
import { tierOf } from './risk.js';

describe('scoreToDisplay', () => {
  it('maps the band cutoffs onto the published tiers', () => {
    expect(tierOf(scoreToDisplay(0.5)).key).toBe('watch');
    expect(tierOf(scoreToDisplay(1.2)).key).toBe('elevated');
    expect(tierOf(scoreToDisplay(2.0)).key).toBe('severe');
    expect(tierOf(scoreToDisplay(5.0)).key).toBe('critical');
    expect(tierOf(scoreToDisplay(9.67)).key).toBe('critical');
  });

  it('keeps Critical to roughly the worst 5% of displayed segments', () => {
    // Measured on the 6,213 segments with n_crashes >= 6: median 0.94,
    // p80 1.57, p95 3.09. Just below a cutoff must not reach the next tier.
    expect(tierOf(scoreToDisplay(0.93)).key).toBe('watch');
    expect(tierOf(scoreToDisplay(3.09)).key).toBe('critical');
    expect(tierOf(scoreToDisplay(3.08)).key).toBe('severe');
  });

  it('is monotonic', () => {
    const scores = [0, 0.5, 0.94, 1.57, 3.09, 5, 9.67];
    const display = scores.map(scoreToDisplay);
    for (let i = 1; i < display.length; i += 1) {
      expect(display[i]).toBeGreaterThanOrEqual(display[i - 1]);
    }
  });

  it('clamps to 0 and 100 rather than falling through', () => {
    expect(scoreToDisplay(0)).toBe(0);
    expect(scoreToDisplay(-1)).toBe(0);
    expect(scoreToDisplay(1000)).toBe(100);
    expect(tierOf(scoreToDisplay(1000)).key).toBe('critical');
  });

  it('returns null for a missing score so the No-data tier applies', () => {
    expect(scoreToDisplay(null)).toBeNull();
    expect(tierOf(scoreToDisplay(null)).key).toBe('nodata');
  });
});

describe('formatExpectedKsi', () => {
  it('names the unit and the window, never a per-trip risk', () => {
    expect(formatExpectedKsi(4.23)).toBe('4.2 KSI over 2 years');
  });

  it('handles a clean route', () => {
    expect(formatExpectedKsi(0)).toBe('no recorded blackspots');
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

```bash
cd frontend && npm test
```

Expected: FAIL — cannot resolve `./riskScale.js`.

- [ ] **Step 4: Write the implementation**

Create `frontend/src/lib/riskScale.js`:

```js
/*
  blackspot_score -> the published 0-100 tier scale in risk.js.

  The score is expected killed-or-seriously-injured casualties on a 500m
  stretch over two years, and runs 0 to 9.67. The UI's tiers are 0-100.

  CUTOFFS ARE CALIBRATED TO THE POPULATION USERS ACTUALLY SEE, not to all
  45,014 segments. The UI filters to n_crashes >= 6, because 86% of segments
  rest on fewer than six crashes and their scores are noise. That filter
  removes overwhelmingly low-scoring rows, so what is displayed is far riskier
  than the whole:

                     all 45,014     shown (n_crashes>=6, 6,213)
      median               0.25                       0.94
      p90                  0.81                       2.24

  The earlier cutoffs (0.45/0.85/1.45), derived from the full population, put
  23.3% of DISPLAYED segments in "Critical" and 60% in Severe-or-worse: a red
  screen that distinguishes nothing. These cutoffs are the 50th, 80th and 95th
  percentiles of the displayed population, giving roughly 50/30/15/5%.

  THE LEGEND MUST SAY SO. A segment labelled "Watch" at 0.90 is still above
  the national median of 0.25. The tiers rank segments that have enough
  evidence to be ranked; they are not absolute national bands. Saying that
  plainly is the condition on which this calibration is honest.

  This is the only place these constants live.
*/

const BANDS = [
  { from: 0, to: 0.94, out: [0, 24] },      // Watch
  { from: 0.94, to: 1.57, out: [25, 49] },  // Elevated
  { from: 1.57, to: 3.09, out: [50, 74] },  // Severe
  { from: 3.09, to: 9.67, out: [75, 100] }, // Critical
];

/** Returns 0-100, or null when there is no score, so tierOf gives No data. */
export function scoreToDisplay(blackspotScore) {
  if (blackspotScore === null || blackspotScore === undefined
      || Number.isNaN(blackspotScore)) {
    return null;
  }
  if (blackspotScore <= 0) return 0;

  for (const b of BANDS) {
    if (blackspotScore < b.to) {
      const t = (blackspotScore - b.from) / (b.to - b.from);
      const [lo, hi] = b.out;
      return Math.round(lo + t * (hi - lo));
    }
  }
  return 100;
}

/*
  The number is casualties on a corridor over two years, across all traffic --
  not the reader's risk on one trip. The unit and window are part of the
  string so a caller cannot render it bare.
*/
export function formatExpectedKsi(value) {
  if (!value) return 'no recorded blackspots';
  return `${value.toFixed(1)} KSI over 2 years`;
}
```

- [ ] **Step 5: Run it to verify it passes**

```bash
cd frontend && npm test
```

Expected: 7 tests passing.

- [ ] **Step 6: Commit**

```bash
git add frontend/ && git commit -m "feat(frontend): map blackspot score onto the published risk tiers"
```

---

### Task 12: Frontend API client

**Files:**
- Create: `frontend/src/lib/api.js`
- Create: `frontend/.env.development`
- Modify: `frontend/vite.config.js`

**Interfaces:**
- Produces: `getSegments({ bbox, minScore, minCrashes, limit })`, `getSegment(id)`, `geocode(q)`, `routeRisk({ from, to, minCrashes })`, `ApiError`

- [ ] **Step 1: Write the client**

Create `frontend/src/lib/api.js`:

```js
/*
  The backend is the only service this app talks to. Routing and geocoding go
  through it so the OpenRouteService key stays server-side.
*/

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8081';

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(path, options) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, options);
  } catch (cause) {
    throw new ApiError(0, 'Cannot reach the API. Is the backend running?');
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.message) message = body.message;
    } catch {
      /* a non-JSON error body is not worth surfacing */
    }
    throw new ApiError(res.status, message);
  }
  return res.json();
}

export function getSegments({ bbox, minScore = 0, minCrashes = 6, limit = 500 } = {}) {
  const q = new URLSearchParams({ minScore, minCrashes, limit });
  if (bbox) q.set('bbox', bbox);
  return request(`/api/segments?${q}`);
}

export function getSegment(segmentId) {
  return request(`/api/segments/${encodeURIComponent(segmentId)}`);
}

export function geocode(q) {
  return request(`/api/geocode?q=${encodeURIComponent(q)}`);
}

export function routeRisk({ from, to, minCrashes }) {
  return request('/api/route/risk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from, to, minCrashes }),
  });
}
```

Create `frontend/.env.development`:

```
VITE_API_BASE=http://localhost:8081
```

- [ ] **Step 2: Verify the app still builds**

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/ && git commit -m "feat(frontend): API client for the blackspot backend"
```

---

### Task 13: The Route screen

**Files:**
- Create: `frontend/src/routes/Route.jsx`, `frontend/src/routes/Route.css`
- Create: `frontend/src/components/RouteCompare.jsx`, `frontend/src/components/RouteCompare.css`
- Modify: `frontend/src/App.jsx`, `frontend/src/components/Nav.jsx`

**Interfaces:**
- Consumes: `api.js`, `riskScale.js`, `risk.js`, existing `RiskBadge`, `States`

- [ ] **Step 1: Read the components being reused**

Before writing, read these so the new screen matches existing conventions rather than inventing its own:

```bash
cd frontend && cat src/components/RiskBadge.jsx src/components/States.jsx src/components/MapCanvas.jsx src/routes/Explorer.jsx
```

Match the file's existing import order, CSS-module-free class naming, and the motion primitives in `src/lib/motion.js`. Do not introduce a new styling approach.

- [ ] **Step 2: Write the comparison card**

Create `frontend/src/components/RouteCompare.jsx`:

```jsx
import { formatExpectedKsi } from '../lib/riskScale.js';
import './RouteCompare.css';

function minutes(seconds) {
  return `${Math.round(seconds / 60)} min`;
}

function kilometres(metres) {
  return `${(metres / 1000).toFixed(1)} km`;
}

/*
  One card per candidate route. The risk figure is deliberately phrased as a
  property of the corridor over two years, not of the reader's journey - the
  score is expected casualties across all traffic, and the difference between
  those two readings is three orders of magnitude.
*/
export default function RouteCompare({ routes, selectedIndex, onSelect }) {
  return (
    <ul className="route-compare">
      {routes.map((r) => (
        <li key={r.index}>
          <button
            type="button"
            className={`route-compare__card${r.index === selectedIndex ? ' is-selected' : ''}`}
            aria-pressed={r.index === selectedIndex}
            onClick={() => onSelect(r.index)}
          >
            <span className="route-compare__label">{r.label}</span>
            <span className="route-compare__stats">
              {minutes(r.durationSeconds)} · {kilometres(r.distanceMetres)}
            </span>
            <span className="route-compare__risk">
              {r.blackspotCount} blackspot{r.blackspotCount === 1 ? '' : 's'}
              {' · '}
              {formatExpectedKsi(r.expectedKsi)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
```

Create `frontend/src/components/RouteCompare.css` following the token names already in `src/styles/tokens.css` — read that file first and use its variables rather than literal colours.

- [ ] **Step 3: Write the screen**

Create `frontend/src/routes/Route.jsx` implementing:

- Two text inputs, each debounced 300 ms into `geocode(q)`, rendering up to 5 candidates in a listbox. Selecting one stores `[lon, lat]`.
- A "Find route" button, disabled until both endpoints are set. On click, `routeRisk({ from, to, minCrashes })`.
- A `minCrashes` checkbox: unchecked sends 6, checked sends 1, labelled "Include thinly-evidenced segments (fewer than 6 recorded crashes)".
- A Leaflet `MapContainer` with OpenStreetMap tiles. Each route as a `Polyline`: selected one at weight 6, others weight 3 at 0.5 opacity. Blackspots on the selected route as `CircleMarker`s using `markerRadius(nCrashes, max)` and `tierOf(scoreToDisplay(blackspotScore)).color`, with `thinlyEvidenced` markers at 0.45 opacity.
- `RouteCompare` for the route cards.
- An ordered list of the selected route's blackspots: position (`(metresAlongRoute / 1000).toFixed(1)` km in), `location`, a `RiskBadge`, `nCrashes`/`nKsi`, and a link to `/explorer?segment=${segmentId}`.
- A banner when `coverageWarning` is non-null.
- Empty state when a route returns zero blackspots: "No recorded blackspots on this route." — presented as a good outcome, not an error.
- `ApiError` handling: `status === 503` → "Routing is temporarily unavailable. Try again shortly."; `422` → "No drivable route between those points."; `0` → "Cannot reach the API. Is the backend running?"; otherwise the error's message.

- [ ] **Step 4: Register the route**

In `frontend/src/App.jsx`, add the import and the route:

```jsx
import RouteScreen from './routes/Route.jsx';
```

```jsx
<Route path="/route" element={<RouteScreen />} />
```

In `frontend/src/components/Nav.jsx`, add a link to `/route` labelled "Route" following the existing link markup exactly.

- [ ] **Step 5: Verify build and manual check**

```bash
cd frontend && npm run build && npm run dev
```

With the backend running, open http://localhost:5173/route, enter "Croydon" and "Camden", and confirm: routes draw, cards show differing blackspot counts, the list is ordered by distance, and a card click reselects the map polyline.

- [ ] **Step 6: Commit**

```bash
git add frontend/ && git commit -m "feat(frontend): route risk screen with scored alternatives"
```

---

### Task 14: Explorer on live data

The last piece of "the blackspot feature": Explorer stops reading the hand-authored fixture.

**Files:**
- Modify: `frontend/src/routes/Explorer.jsx`
- Modify: `frontend/src/components/DetailPanel.jsx`
- Modify: `frontend/src/data/blackspots.js`

- [ ] **Step 1: Read what Explorer consumes today**

```bash
cd frontend && cat src/routes/Explorer.jsx src/components/DetailPanel.jsx src/lib/filters.js
```

Note every field of the fixture shape the components read. The four with no real counterpart — `lastIncident`, `factors`, `landmarks`, `hourlyProfile` — must be removed from the JSX, not fed placeholder values.

- [ ] **Step 2: Switch the data source**

In `Explorer.jsx`, replace the fixture import with a `useEffect` that calls `getSegments({ bbox, minCrashes })` on map move (debounced 400 ms), holding `loading` / `error` / `data` state and rendering the existing `States` components for the first two.

Map API fields onto what the components expect:

| Component expects | Comes from |
|---|---|
| `id` | `segmentId` |
| `name` | `location` |
| `lat`, `lng` | `lat`, `lon` |
| `score` | `scoreToDisplay(blackspotScore)` |
| `incidents` | `nCrashes` |
| `fatal` | `nFatal` |
| `serious` | `nKsi - nFatal` |
| `roadClass` | `roadId` |
| `speedLimit` | `speedMax` |

- [ ] **Step 3: Remove the fields with no real counterpart**

In `DetailPanel.jsx`, delete the `lastIncident`, `landmarks`, `factors`, and `hourlyProfile` blocks. Replace the hourly histogram with the segment's real `pctNight`, rendered as one figure: `${Math.round(pctNight * 100)}% of crashes here were at night`.

Add the raw score beside the tier, so the model output is visible rather than only its band:

```jsx
<p className="detail-panel__raw">
  {blackspotScore.toFixed(2)} expected KSI casualties over two years,
  across all traffic on this 500 m.
</p>
```

- [ ] **Step 4: Retire the fixture**

`Rankings.jsx` and `Statistics.jsx` still import `blackspots.js` and are Phase 2. Leave the file in place, and replace its header comment so the next reader is not misled:

```js
/*
  DEMONSTRATION FIXTURE - Bhubaneswar/Cuttack/Puri, hand-authored, NOT real data.

  Explorer and Route now read the live API (src/lib/api.js). Rankings and
  Statistics still read this file; moving them is Phase 2 of
  docs/superpowers/specs/2026-09-03-route-risk-design.md.

  Do not add to this file. New work reads the API.
*/
```

- [ ] **Step 5: Verify**

```bash
cd frontend && npm run build && npm test
```

Then with the backend running, open `/explorer`, pan the map, and confirm segments load from the API and the detail panel shows real UK locations.

- [ ] **Step 6: Commit**

```bash
git add frontend/ && git commit -m "feat(frontend): Explorer reads the live segment API"
```

---

### Task 15: Root README and run instructions

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document the whole stack**

Add to the root `README.md` a "Running the full stack" section: prerequisites (Java 21+, Node 20+, a Supabase project, an ORS key), then the four commands in order — schema in the Supabase SQL editor, `./mvnw spring-boot:run -Dspring-boot.run.arguments=--load-data`, `./mvnw spring-boot:run`, `npm run dev`. State that `backend/.env` is required and gitignored.

- [ ] **Step 2: Correct CLAUDE.md**

Its layout section describes an ML-only repo. Add `backend/` and `frontend/`, and correct the claim that `build_recent.py` "downloads ~4GB STATS19" — it does not download anything; it reads three pre-downloaded DfT CSVs from `ml/stats19_raw/`.

- [ ] **Step 3: Full verification**

```bash
cd backend && ./mvnw -q test && cd ../frontend && npm test && npm run build
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md && git commit -m "docs: full-stack run instructions"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Supabase schema, PostGIS, no `future_*` column | 3 |
| Loader drops `future_*`, derives `run` | 2, 4 |
| `GET /api/segments`, `/api/segments/{id}` | 7 |
| `GET /api/geocode` | 10 |
| `POST /api/route/risk` with alternatives | 9, 10 |
| Corridor query, 50 m, ordered along route | 6, 9 |
| `minCrashes` default 6, toggle to 1 | 6, 10, 13 |
| Score → 0–100 tier mapping, frontend only | 11 |
| Route screen with comparison cards | 13 |
| Explorer on live data | 14 |
| Four fixture fields removed | 14 |
| Error handling table | 7, 10, 13 |
| Wording rule enforced | 9 (record docs), 11 (`formatExpectedKsi`), 13 |
| Key never in browser | 8, 12 |

**Placeholder scan:** none — Task 13 Step 3 describes UI behaviour rather than pasting a large component verbatim, but every field, threshold, and error string it must produce is named explicitly.

**Type consistency:** `Segment` (Task 3) → `SegmentCsvReader` (4) → `SegmentRepository` (6) → `CorridorHit` (6) → `RouteRiskService` (9) → `ScoredRoute`/`BlackspotOnRoute` (8) → `api.js` (12) → `Route.jsx` (13). Coordinates are `[lon, lat]` everywhere, matching GeoJSON, ORS, and `ST_MakePoint`. The one place they invert is `SegmentLoader` (`ps.setDouble(7, s.lon())`), commented at the call site.

## Sequencing

Tasks 1–4 need no credentials and no network. **Task 5 is the first that needs your Supabase `.env`**, and Tasks 6, 10 Step 6, and 13 Step 5 need it too. Task 8 onward needs `ORS_API_KEY`. Tasks 11–12 are frontend-only and can run in parallel with any backend task.

**Before Task 5, rotate the Supabase password** pasted into chat on 2026-09-03.
