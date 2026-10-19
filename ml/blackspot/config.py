"""Paths, periods and constants for the v2 blackspot pipeline.

Every path is anchored on this file, so the pipeline behaves the same whatever
directory it is launched from. Nothing here creates directories on import;
`ensure_dirs()` does that explicitly at the start of each entry point.
"""
from __future__ import annotations

from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
REPO = ML_DIR.parent

RAW = ML_DIR / "raw"                 # downloads, gitignored, provenance in RAW/manifest.json
INTERIM = ML_DIR / "interim"         # derived parquet, gitignored, regenerable
REPORTS = ML_DIR / "reports"         # research reports (markdown + csv), committed
OUTPUTS = ML_DIR / "outputs"         # v2 model outputs and artefacts, committed if small
BACKEND_DATA = REPO / "data"         # backend contract: road_segments_ranked.csv etc.

LEGACY_CSV = REPO / "stats19_recent.csv"   # v1 extract (2015-2023, collision grain)

SEED = 42

# ---------------------------------------------------------------- periods
# Collision-level history exists 2015-2025. Casualty-level severity (needed for
# a KSI *casualty* target) comes from the casualty table.
FIRST_YEAR, LAST_YEAR = 2015, 2025
HISTORY_YEARS = 3                    # feature window length
TARGET_YEARS = 2                     # forecast horizon: "expected KSI over two years"

# ---------------------------------------------------------------- geometry
SEGMENT_TARGET_M = 500.0
SNAP_MAX_M = 50.0                    # max crash-to-centreline distance for assignment
EPSG_BNG = 27700

# STATS19 first_road_class codes
ROAD_CLASS = {1: "M", 2: "A(M)", 3: "A", 4: "B", 5: "C", 6: "U"}

# Severity codes (collision_severity / casualty_severity)
FATAL, SERIOUS, SLIGHT = 1, 2, 3


def ensure_dirs(*dirs: Path) -> None:
    for d in dirs or (RAW, INTERIM, REPORTS, OUTPUTS):
        d.mkdir(parents=True, exist_ok=True)
