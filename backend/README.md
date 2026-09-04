# blackspot-api

Spring Boot API over the blackspot segment data. Java 21+, no global Maven
needed — use the wrapper.

## Prerequisites

`JAVA_HOME` must point at a JDK 21+ install — the wrapper refuses to start
without it:

    export JAVA_HOME="/c/Program Files/Java/jdk-22"

PowerShell:

    $env:JAVA_HOME = 'C:\Program Files\Java\jdk-22'

## Configure

    cp .env.example .env

Fill in both values. `.env` is gitignored; never commit it.

- `DATABASE_URL` — Supabase → Settings → Database → Connection string.
  Use whichever mode the dashboard offers for your network.
- `ORS_API_KEY` — https://openrouteservice.org/dev/#/signup

Spring Boot does not read `.env` files on its own — `application.yml` binds
`${DATABASE_URL:}` and `${ORS_API_KEY:}` from the process environment, so
export them into the shell before any `./mvnw` command that talks to the
database.

**Don't just `source`/`. ./.env` it.** `DATABASE_URL` contains `&` between
its query parameters (`?user=...&password=...&sslmode=require`); a plain
`set -a; . ./.env; set +a` runs bash through the file as a script, and the
unescaped `&` is parsed as the background-job operator, silently truncating
the exported value at the first `&`. The app then fails to connect (or
connects with the wrong value) with no obvious cause. Load it line-by-line
instead, so the value is never re-parsed as shell syntax:

    while IFS= read -r line; do
      case "$line" in ''|'#'*) continue ;; esac
      export "${line%%=*}=${line#*=}"
    done < .env

**Do not set `IFS='='` for the `read`.** That was tried and is also wrong:
`IFS='='` makes `read -r key value` split on *every* `=` in the line, and if
the value's last character is itself `=` — which happens routinely, since
`ORS_API_KEY` is base64-shaped and base64 pads with trailing `=` — that
trailing character is dropped from `value` instead of being read as part of
it. The key silently loads one character short, ORS still parses it as a
string and returns `403 {"error": "Access to this API has been disallowed"}`
(the auth layer's generic reply for an invalid key), and nothing about that
response points back to a shell-quoting bug. `${line%%=*}` / `${line#*=}`
split on only the *first* `=`, so a trailing `=` in the value survives.

Verify without ever printing the value:

    [ -n "$DATABASE_URL" ] && echo "set"
    [ -n "$ORS_API_KEY" ] && echo "set"

PowerShell — the same thing, run from `backend/`:

    Get-Content .env | Where-Object { $_ -match '^\s*[^#\s]' } | ForEach-Object {
      $k, $v = $_ -split '=', 2
      Set-Item -Path "Env:$($k.Trim())" -Value $v
    }

`-split '=', 2` is the whole point: the `, 2` caps the split at two fields, so
only the *first* `=` separates key from value and a trailing `=` in the value
survives. `-split '='` without it truncates the ORS key exactly as `IFS='='`
does above, with the same unexplained 403. The `&`-in-value hazard does not
apply on this side — `Get-Content` never re-parses the line as syntax.

Verify without printing either value:

    if ($env:DATABASE_URL) { "DATABASE_URL set" }
    if ($env:ORS_API_KEY)  { "ORS_API_KEY set" }

## Create the schema

Run `src/main/resources/schema.sql` once, in the Supabase dashboard's SQL
editor. It is destructive: it drops `road_segment` before recreating it.

## Load the data

    ./mvnw spring-boot:run -Dspring-boot.run.arguments=--load-data

Reads `../data/road_segments_ranked.csv` (45,014 rows) and truncates before
inserting, so re-running after a data refresh is safe.

## Run

    ./mvnw spring-boot:run

Serves on `http://localhost:8081`. The default is 8081, not Spring Boot's
usual 8080 — 8080 is occupied by Oracle's TNS Listener on the development
machine.

## Test

    ./mvnw test                    # unit tests, no database, no Docker
    ./mvnw test -Dgroups=postgis   # adds live PostGIS tests, needs DATABASE_URL
