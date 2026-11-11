"""Build the Statistics screen's summary from outputs already in the repo.

    python build_stats_summary.py          # from ml/, ~2 s, no internet

Reads:
    ../data/road_segments_ranked.csv        45,014 scored 500 m segments
    reports/blackspot_full_output.log       crash totals + held-out validation
    shap/subcategory_ranking.csv            severity-model SHAP spread per category
    shap/per_level/*.csv                    SHAP per level, for highest/lowest
Writes:
    ../frontend/src/data/gbStats.json

The crash-level file (stats19_recent.csv) is not shipped, so nothing here can be
broken down by month, hour or year. Everything below is either a per-segment
aggregate or a number the pipeline already printed.

Tier counts are NOT computed here. The tier cutoffs live only in
frontend/src/lib/riskScale.js; this script ships the evidenced segments' raw
scores and the screen bins them with the same function the map uses.
"""
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEGMENTS = HERE.parent / "data" / "road_segments_ranked.csv"
LOG = HERE / "reports" / "blackspot_full_output.log"
SHAP = HERE / "shap"
OUT = HERE.parent / "frontend" / "src" / "data" / "gbStats.json"

MIN_CRASHES = 6          # same evidence floor as the UI (lib/filters.js)
TOP_ROADS = 8
TOP_SEGMENTS = 300       # Overview map preview
# Administrative, not a road condition: recording differences between forces.
EXCLUDED_FACTORS = {"police_force"}

CATEGORY_LABELS = {
    "speed_limit": "Speed limit",
    "urban_or_rural_area": "Urban or rural",
    "light_conditions": "Light conditions",
    "weather_conditions": "Weather",
    "road_type": "Road type",
    "junction_control": "Junction control",
    "day_of_week": "Day of week",
    "road_surface_conditions": "Road surface",
    "junction_detail": "Junction layout",
    "first_road_class": "Road class",
}

# STATS19 code tables for categories whose per-level files store bare codes.
LEVEL_LABELS = {
    "road_type": {"1": "Roundabout", "2": "One-way street", "3": "Dual carriageway",
                  "6": "Single carriageway", "7": "Slip road"},
    "junction_control": {"1": "Authorised person", "2": "Traffic signals",
                         "3": "Stop sign", "4": "Give way or uncontrolled"},
    "day_of_week": {"1": "Sunday", "2": "Monday", "3": "Tuesday", "4": "Wednesday",
                    "5": "Thursday", "6": "Friday", "7": "Saturday"},
    "first_road_class": {"1": "Motorway", "2": "A(M)", "3": "A road", "4": "B road",
                         "5": "C road", "6": "Unclassified"},
}
# Levels that mean "not recorded"; never named as the highest or lowest.
UNKNOWN = {"unknown", "other", "dark-unknown", "-1", "9", "99"}


def read_segments():
    with SEGMENTS.open(newline="") as f:
        return list(csv.DictReader(f))


def parse_log():
    text = LOG.read_text()
    m = re.search(r"1,027 roads with >= 60 crashes -> ([\d,]+) crashes covered", text)
    numbered = re.search(r"([\d,]+) crashes on numbered roads", text)
    assert m and numbered, "crash totals not found in blackspot log"

    validation = []
    for key, label in [("blackspot score (model)", "Blackspot model"),
                       ("past crash count", "Past crash count"),
                       ("past KSI count", "Past KSI count")]:
        row = re.search(re.escape(key) + r"\s+([\d.]+)%\s+([\d.]+)%\s+([\d.]+)%\s+([\d.]+)%", text)
        assert row, f"validation row '{key}' not found"
        validation.append({"method": label, "values": [float(v) for v in row.groups()]})

    return {
        "crashesOnNumberedRoads": int(numbered.group(1).replace(",", "")),
        "crashesCovered": int(m.group(1).replace(",", "")),
        "validation": {"cutoffs": ["Top 1%", "Top 5%", "Top 10%", "Top 20%"],
                       "rows": validation},
    }


def level_label(category, level, label):
    if category == "speed_limit":
        return f"{int(float(level))} mph"
    mapped = LEVEL_LABELS.get(category, {}).get(level)
    if mapped:
        return mapped
    return None if label == level else label.replace("-", ", ").replace("+", " and ")


def factors():
    out = []
    with (SHAP / "subcategory_ranking.csv").open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["category"] not in EXCLUDED_FACTORS]
    top_spread = max(float(r["spread"]) for r in rows)

    for r in sorted(rows, key=lambda r: -float(r["spread"])):
        cat = r["category"]
        levels = []
        per_level = SHAP / "per_level" / f"{cat}.csv"
        if per_level.exists():
            with per_level.open(newline="") as f:
                for lv in csv.DictReader(f):
                    name = level_label(cat, lv["level"], lv["label"])
                    if (name and lv["low_sample"] == "False"
                            and lv["label"].lower() not in UNKNOWN
                            and lv["level"] not in UNKNOWN):
                        levels.append((float(lv["mean_shap"]), name))
        levels.sort()
        out.append({
            "key": cat,
            "label": CATEGORY_LABELS.get(cat, cat),
            "share": round(float(r["spread"]) / top_spread * 100),
            "highest": levels[-1][1] if len(levels) >= 2 else None,
            "lowest": levels[0][1] if len(levels) >= 2 else None,
        })
    return out


def main():
    segs = read_segments()
    log = parse_log()

    # Segment counts are the 2019-2021 build years only. The log's
    # "crashes covered" spans every year road_segments.py loaded, so it is
    # larger and is not what the scores were built from; it is not shipped.
    crashes = sum(int(s["n_crashes"]) for s in segs)
    ksi = sum(int(s["n_ksi"]) for s in segs)
    fatal = sum(int(s["n_fatal"]) for s in segs)

    evidenced = sorted(round(float(s["blackspot_score"]), 3)
                       for s in segs if int(s["n_crashes"]) >= MIN_CRASHES)

    by_speed = defaultdict(lambda: [0, 0, 0])
    for s in segs:
        if not s["speed_max"]:
            continue
        b = by_speed[int(float(s["speed_max"]))]
        b[0] += int(s["n_crashes"])
        b[1] += int(s["n_ksi"])
        b[2] += 1
    speed = [{"speed": f"{k} mph", "crashes": c, "ksi": k_, "segments": n,
              "ksiShare": round(k_ / c * 100, 1)}
             for k, (c, k_, n) in sorted(by_speed.items()) if c >= 500]

    by_road = defaultdict(lambda: [0, 0, 0])
    for s in segs:
        b = by_road[s["road_id"]]
        b[0] += int(s["n_ksi"])
        b[1] += int(s["n_crashes"])
        b[2] += int(s["n_fatal"])
    roads = [{"road": r, "ksi": k, "crashes": c, "fatal": f}
             for r, (k, c, f) in sorted(by_road.items(), key=lambda x: -x[1][0])[:TOP_ROADS]]

    # The Overview's map preview and headline crops. Same field names as
    # /api/segments, so the frontend's toView() reads them unchanged.
    top = sorted((s for s in segs if int(s["n_crashes"]) >= MIN_CRASHES),
                 key=lambda s: int(s["rank"]))[:TOP_SEGMENTS]
    top_segments = [{
        "segmentId": s["segment_id"], "location": s["location"], "roadId": s["road_id"],
        "rank": int(s["rank"]), "lat": round(float(s["lat"]), 5), "lon": round(float(s["lon"]), 5),
        "kmFrom": float(s["km_from"]), "kmTo": float(s["km_to"]),
        "blackspotScore": round(float(s["blackspot_score"]), 3),
        "nCrashes": int(s["n_crashes"]), "nKsi": int(s["n_ksi"]), "nFatal": int(s["n_fatal"]),
        "speedMax": float(s["speed_max"]) if s["speed_max"] else None,
        "pctNight": round(float(s["pct_night"]), 3), "pctJunction": round(float(s["pct_junction"]), 3),
    } for s in top]

    models = json.loads((HERE / "models" / "deployable_vs_explanatory.json").read_text())
    severity = {k.lower(): {"features": v["n_features"], "rocAuc": round(v["roc_auc"], 3)}
                for k, v in models.items()}

    summary = {
        "generatedFrom": "data/road_segments_ranked.csv, ml/reports, ml/shap",
        "crashYears": [2019, 2021],
        "forecastYears": [2022, 2023],
        "minCrashes": MIN_CRASHES,
        "totals": {
            "crashes": crashes,
            "ksi": ksi,
            "fatal": fatal,
            "segments": len(segs),
            "evidencedSegments": len(evidenced),
            "roads": len(by_road),
        },
        "validation": log["validation"],
        "evidencedScores": evidenced,
        "bySpeed": speed,
        "topRoads": roads,
        "factors": factors(),
        "severityModels": severity,
        "topSegments": top_segments,
    }
    OUT.write_text(json.dumps(summary, separators=(",", ":")))
    print(f"wrote {OUT.relative_to(HERE.parent)} ({OUT.stat().st_size // 1024} KB)")
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("evidencedScores", "topSegments")}, indent=1)[:3000])


if __name__ == "__main__":
    main()
