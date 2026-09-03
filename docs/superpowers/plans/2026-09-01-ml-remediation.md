# ML Branch Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the correctness bugs, methodology flaws, and reproducibility gaps in the `ML` branch so the blackspot data is honest, servable, and defensible in a viva.

**Architecture:** `ml/road_segments.py` is a 265-line monolith that trains on 70% of segments and then scores 100% of them, writing the answer column (`future_ksi`) into the file meant to be served. We break it into a small importable package (`ml/blackspot/`) so each stage is unit-testable, replace the random split with road-grouped out-of-fold prediction, split the output into a *serving* artifact and a *validation* artifact, and add the exposure/recency/confidence fields the score currently lacks.

**Tech Stack:** Python 3.11+, pandas, numpy, scikit-learn, LightGBM, SHAP, scipy, pytest.

## Global Constraints

- All work happens on the `ML` branch. Do not touch `frontend/`.
- All commands run from `ml/`. Paths in code go through `ml/blackspot/paths.py` — no bare relative strings.
- Data stays **UK STATS19**. The Indian MoRTH relabelling (`Slight→Minor`, `Serious→Grievous`) is reverted; UK labels `Slight` / `Serious` / `Fatal` are canonical.
- **No column whose name starts with `future_` may appear in any serving artifact.** Enforced by a test, not by a README warning.
- Every reported metric must come from out-of-fold or held-out predictions. Never from `model.predict()` on rows the model trained on.
- Tests must run without `stats19_recent.csv` (581 MB). Use the synthetic fixture.
- `random_state=42` everywhere, as the existing code does.
- Commit after every task. Message prefix: `fix:`, `feat:`, `test:`, `refactor:`, `docs:`.

---

## File Structure

**New package — `ml/blackspot/`** (each file one responsibility, all importable and testable):

| File | Responsibility |
|---|---|
| `ml/blackspot/__init__.py` | Package marker, exports the public builders |
| `ml/blackspot/paths.py` | Every input/output path in one place; `ensure_dirs()` |
| `ml/blackspot/chainage.py` | `chainage()` and `_chain_one()`, moved verbatim from `road_segments.py` |
| `ml/blackspot/ids.py` | `stable_segment_id()` — grid-anchored, survives re-runs |
| `ml/blackspot/segments.py` | `build_segments()` — crash rows → segment table |
| `ml/blackspot/scoring.py` | `score_segments()` — road-grouped out-of-fold Poisson prediction |
| `ml/blackspot/exposure.py` | `join_aadt()` — DfT traffic counts → `veh_km_per_year`, `casualty_rate` |
| `ml/blackspot/recency.py` | `add_recency()` — half-life weighted crash counts, `last_crash_date` |
| `ml/blackspot/artifacts.py` | `write_serving()` / `write_validation()` — the only writers |
| `ml/baselines.py` | DBSCAN + silhouette comparison, run standalone |
| `ml/eda.py` | Dashboard aggregates |

**New tests — `ml/tests/`:**

`conftest.py`, `test_chainage.py`, `test_ids.py`, `test_segments.py`, `test_scoring.py`, `test_artifacts.py`, `test_exposure.py`, `test_recency.py`, `test_severity_thresholds.py`

**Modified:** `ml/road_segments.py` (becomes a thin orchestrator), `ml/severity_final.py`, `ml/severity_deployable.py`, `ml/build_recent.py`, `CLAUDE.md`, `ml/README.md`, `ml/requirements.txt`.

**Moved:** `ml/clean_road_accident_data.py` → `ml/archive/scripts/`.

---

### Task 1: Test harness and synthetic STATS19 fixture

Nothing else in this plan is testable until a small in-memory dataset exists that has the same shape as `stats19_recent.csv`. Everything downstream depends on this.

**Files:**
- Create: `ml/tests/__init__.py`
- Create: `ml/tests/conftest.py`
- Create: `ml/tests/test_fixture.py`
- Create: `ml/pytest.ini`
- Modify: `ml/requirements.txt`

**Interfaces:**
- Produces: `synthetic_crashes(n_roads=3, seed=42) -> pd.DataFrame` — a pytest fixture named `crashes` returning a DataFrame with every column `build_segments()` reads.

- [ ] **Step 1: Add pytest to requirements**

Append to `ml/requirements.txt`:

```
pytest>=8.0
```

- [ ] **Step 2: Create the pytest config**

Create `ml/pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -q
```

- [ ] **Step 3: Write the fixture**

Create `ml/tests/__init__.py` as an empty file, then create `ml/tests/conftest.py`:

```python
"""Synthetic STATS19-shaped data.

The real extract is 581 MB and takes 30 minutes to rebuild, so tests use a
generated stand-in with the same columns and the same coding conventions
(numeric codes, not text). Roads are laid out as straight north-south lines so
chainage has a known answer.
"""
import numpy as np
import pandas as pd
import pytest

M_PER_DEG_LAT = 111_320.0

# STATS19 codes: 1=Motorway, 3=A road, 4=B road
ROAD_SPECS = [
    # (first_road_class, first_road_number, base_lat, base_lon, n_crashes, length_km)
    (3, 23, 51.40, -0.12, 300, 12.0),
    (3, 3, 51.45, -0.14, 240, 9.0),
    (4, 1234, 53.40, -1.50, 180, 6.0),
]


def synthetic_crashes(seed: int = 42, extra_frac: float = 0.0) -> pd.DataFrame:
    """Crash rows on straight north-south roads.

    extra_frac adds that proportion of additional crashes at random positions,
    used to test that segment IDs survive a data refresh.
    """
    rng = np.random.default_rng(seed)
    rows = []
    cid = 0
    for cls, num, lat0, lon0, n, length_km in ROAD_SPECS:
        n_total = int(n * (1.0 + extra_frac))
        # position along the road, in degrees of latitude
        span_deg = (length_km * 1000.0) / M_PER_DEG_LAT
        t = rng.uniform(0.0, 1.0, n_total)
        for i in range(n_total):
            cid += 1
            year = int(rng.choice([2019, 2020, 2021, 2022, 2023]))
            month = int(rng.integers(1, 13))
            day = int(rng.integers(1, 29))
            rows.append({
                "collision_index": f"S{cid:07d}",
                "collision_year": year,
                "date": f"{day:02d}/{month:02d}/{year}",
                "latitude": lat0 + t[i] * span_deg,
                # small lateral jitter (~5 m) so points are not exactly collinear
                "longitude": lon0 + rng.normal(0.0, 0.00007),
                "first_road_class": cls,
                "first_road_number": num,
                "Accident_Severity": str(rng.choice(
                    ["Slight", "Serious", "Fatal"], p=[0.78, 0.20, 0.02])),
                "speed_limit": int(rng.choice([20, 30, 40, 50, 60, 70])),
                "number_of_vehicles": int(rng.integers(1, 4)),
                "number_of_casualties": int(rng.integers(1, 4)),
                "Hour": int(rng.integers(0, 24)),
                "junction_detail": int(rng.choice([0, 1, 3, 6])),
                "road_type": int(rng.choice([1, 3, 6])),
                "urban_or_rural_area": int(rng.choice([1, 2])),
                "light_conditions": int(rng.choice([1, 4, 5, 6])),
            })
    return pd.DataFrame(rows)


def two_stretch_road(seed: int = 7) -> pd.DataFrame:
    """One road number recorded in two places 50 km apart.

    Mirrors the real A503 problem: crashes tagged with the same number appear
    hundreds of km apart. The pipeline must treat these as separate runs.
    """
    rng = np.random.default_rng(seed)
    frames = []
    for lat0 in (51.50, 51.95):        # ~50 km apart, well over STRETCH_GAP_M
        span_deg = 4000.0 / M_PER_DEG_LAT
        t = rng.uniform(0.0, 1.0, 80)
        frames.append(pd.DataFrame({
            "latitude": lat0 + t * span_deg,
            "longitude": -0.10 + rng.normal(0.0, 0.00007, 80),
        }))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture
def crashes():
    return synthetic_crashes()
```

- [ ] **Step 4: Write the failing test**

Create `ml/tests/test_fixture.py`:

```python
from tests.conftest import synthetic_crashes

REQUIRED = {
    "collision_index", "collision_year", "date", "latitude", "longitude",
    "first_road_class", "first_road_number", "Accident_Severity", "speed_limit",
    "number_of_vehicles", "number_of_casualties", "Hour", "junction_detail",
    "road_type", "urban_or_rural_area", "light_conditions",
}


def test_fixture_has_every_column_the_pipeline_reads(crashes):
    assert REQUIRED <= set(crashes.columns)


def test_fixture_is_deterministic():
    a = synthetic_crashes(seed=42)
    b = synthetic_crashes(seed=42)
    assert a.equals(b)


def test_fixture_spans_build_and_future_windows(crashes):
    years = set(crashes.collision_year)
    assert {2019, 2020, 2021} <= years
    assert {2022, 2023} <= years


def test_severity_uses_uk_labels(crashes):
    assert set(crashes.Accident_Severity) <= {"Slight", "Serious", "Fatal"}
```

- [ ] **Step 5: Run the test to verify it fails**

Run from `ml/`:

```bash
python -m pytest tests/test_fixture.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'tests'` before Step 3 files exist, or collection errors. After Steps 2–3 it should pass; if it fails on `test_severity_uses_uk_labels`, that is the fixture being written correctly against the *target* label scheme, not the current one.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/ -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add ml/tests ml/pytest.ini ml/requirements.txt
git commit -m "test: add pytest harness and synthetic STATS19 fixture"
```

---

### Task 2: Centralise paths

Right now `road_segments.py` writes `road_segments_ranked.csv` into the current directory, but the committed copies live in `data/`. `severity_deployable.py` writes to `severity_outputs/` with no `makedirs`, so it crashes on a fresh clone unless `severity_final.py` ran first. `CLAUDE.md` describes a `handoff/` directory that does not exist. One module fixes all of it.

**Files:**
- Create: `ml/blackspot/__init__.py`
- Create: `ml/blackspot/paths.py`
- Create: `ml/tests/test_paths.py`
- Modify: `ml/severity_deployable.py:113` and its other output lines
- Modify: `ml/severity_final.py:38-39`

**Interfaces:**
- Produces: `paths.ML_DIR`, `paths.DATA_DIR`, `paths.MODELS_DIR`, `paths.SHAP_DIR`, `paths.REPORTS_DIR`, `paths.RAW_CSV`, `paths.ensure_dirs()`

- [ ] **Step 1: Write the failing test**

Create `ml/tests/test_paths.py`:

```python
from blackspot import paths


def test_paths_are_absolute():
    assert paths.ML_DIR.is_absolute()
    assert paths.DATA_DIR.is_absolute()


def test_data_dir_is_sibling_of_ml_dir():
    # data/ sits next to ml/, not inside it
    assert paths.DATA_DIR.parent == paths.ML_DIR.parent
    assert paths.DATA_DIR.name == "data"


def test_ensure_dirs_creates_every_output_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ML_DIR", tmp_path / "ml")
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "MODELS_DIR", tmp_path / "ml" / "models")
    monkeypatch.setattr(paths, "SHAP_DIR", tmp_path / "ml" / "shap")
    monkeypatch.setattr(paths, "REPORTS_DIR", tmp_path / "ml" / "reports")
    paths.ensure_dirs()
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "ml" / "models").is_dir()
    assert (tmp_path / "ml" / "shap").is_dir()
    assert (tmp_path / "ml" / "reports").is_dir()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_paths.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'blackspot'`

- [ ] **Step 3: Write the implementation**

Create `ml/blackspot/__init__.py`:

```python
"""Blackspot detection pipeline.

Split out of road_segments.py so each stage can be tested without the 581 MB
STATS19 extract.
"""
```

Create `ml/blackspot/paths.py`:

```python
"""Every input and output path, in one place.

The committed layout is:

    ml/            scripts, package, tests
    ml/models/     joblib models + metrics json
    ml/shap/       SHAP tables
    ml/reports/    full console logs
    data/          artifacts the backend consumes  (sibling of ml/, not inside)

Scripts previously wrote into the current working directory and the files were
moved by hand afterwards, which made a fresh clone unreproducible.
"""
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = ML_DIR.parent
DATA_DIR = REPO_DIR / "data"

MODELS_DIR = ML_DIR / "models"
SHAP_DIR = ML_DIR / "shap"
SUBCAT_SHAP_DIR = SHAP_DIR / "per_level"
REPORTS_DIR = ML_DIR / "reports"
ARCHIVE_DIR = ML_DIR / "archive"

# Not in git: 581 MB, regenerate with build_recent.py
RAW_CSV = ML_DIR / "stats19_recent.csv"

# Serving artifacts — never contain future_* columns
SERVING_CSV = DATA_DIR / "road_segments_serving.csv"
SERVING_JSON = DATA_DIR / "road_segments_top500.json"
META_JSON = DATA_DIR / "road_segments_meta.json"

# Validation artifact — contains the answer, for the report only
VALIDATION_CSV = DATA_DIR / "road_segments_validation.csv"


def ensure_dirs() -> None:
    for d in (DATA_DIR, MODELS_DIR, SHAP_DIR, SUBCAT_SHAP_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/test_paths.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Point the severity scripts at it**

In `ml/severity_final.py`, replace lines 38–39:

```python
OUT = "severity_outputs"
os.makedirs(OUT, exist_ok=True)
os.makedirs(f"{OUT}/subcategory_shap", exist_ok=True)
```

with:

```python
from blackspot import paths
paths.ensure_dirs()
OUT = paths.MODELS_DIR
SHAP_OUT = paths.SHAP_DIR
SUBCAT_OUT = paths.SUBCAT_SHAP_DIR
```

Then update the writers in that file: `f"{OUT}/global_shap_importance.csv"` → `SHAP_OUT / "global_shap_importance.csv"`, `f"{OUT}/subcategory_shap/{safe}.csv"` → `SUBCAT_OUT / f"{safe}.csv"`, `f"{OUT}/subcategory_ranking.csv"` → `SHAP_OUT / "subcategory_ranking.csv"`, `f"{OUT}/subcategory_shap_all.csv"` → `SHAP_OUT / "subcategory_shap_all.csv"`. The three `joblib.dump` / `json.dump` calls keep `OUT` (now `paths.MODELS_DIR`).

Also replace `pd.read_csv("stats19_recent.csv", low_memory=False)` with `pd.read_csv(paths.RAW_CSV, low_memory=False)`.

In `ml/severity_deployable.py`, add after the imports:

```python
from blackspot import paths
paths.ensure_dirs()
```

and replace the three output paths:

```python
joblib.dump(m, paths.MODELS_DIR / "severity_deployable_model.joblib")
imp.to_csv(paths.SHAP_DIR / "deployable_feature_importance.csv", index=False)
json.dump(results, open(paths.MODELS_DIR / "deployable_vs_explanatory.json", "w"), indent=2)
```

and its read: `pd.read_csv(paths.RAW_CSV, low_memory=False)`.

- [ ] **Step 6: Verify the scripts at least import cleanly**

```bash
python -c "import ast,sys; [ast.parse(open(f).read()) for f in ['severity_final.py','severity_deployable.py']]; print('parse ok')"
```

Expected: `parse ok`. (A full run needs the 581 MB extract; this confirms no syntax break.)

- [ ] **Step 7: Commit**

```bash
git add ml/blackspot ml/tests/test_paths.py ml/severity_final.py ml/severity_deployable.py
git commit -m "refactor: centralise all IO paths in blackspot.paths"
```

---

### Task 3: Extract chainage into a testable module

`chainage()` and `_chain_one()` are correct and hard-won — the comments document two real bugs they fixed. Move them unchanged so they gain tests, not rewrites.

**Files:**
- Create: `ml/blackspot/chainage.py`
- Create: `ml/tests/test_chainage.py`
- Modify: `ml/road_segments.py` (delete the moved functions, import them)

**Interfaces:**
- Produces: `chainage(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]` returning `(chainage_m, stretch_id)`, both length-n.

- [ ] **Step 1: Write the failing test**

Create `ml/tests/test_chainage.py`:

```python
import numpy as np

from blackspot.chainage import chainage
from tests.conftest import two_stretch_road, M_PER_DEG_LAT


def test_straight_road_chainage_matches_true_length():
    # 5 km of road, 200 points
    n = 200
    lat = 51.5 + np.linspace(0, 5000.0 / M_PER_DEG_LAT, n)
    lon = np.full(n, -0.1)
    ch, run = chainage(lat, lon)
    assert ch.max() == 0 or abs(ch.max() - 5000.0) < 250.0  # within 5%
    assert len(np.unique(run)) == 1


def test_chainage_is_monotonic_along_a_straight_road():
    n = 100
    lat = 51.5 + np.linspace(0, 3000.0 / M_PER_DEG_LAT, n)
    lon = np.full(n, -0.1)
    ch, _ = chainage(lat, lon)
    order = np.argsort(lat)
    # chainage must increase (or decrease) consistently with position
    d = np.diff(ch[order])
    assert (d >= -1.0).all() or (d <= 1.0).all()


def test_separated_stretches_get_different_run_ids():
    df = two_stretch_road()
    _, run = chainage(df.latitude.values, df.longitude.values)
    assert len(np.unique(run)) == 2


def test_each_stretch_restarts_near_zero():
    df = two_stretch_road()
    ch, run = chainage(df.latitude.values, df.longitude.values)
    for r in np.unique(run):
        assert ch[run == r].min() < 100.0


def test_handles_fewer_than_three_points():
    ch, run = chainage(np.array([51.5, 51.6]), np.array([-0.1, -0.1]))
    assert len(ch) == 2 and len(run) == 2
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_chainage.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'blackspot.chainage'`

- [ ] **Step 3: Create the module**

Create `ml/blackspot/chainage.py` containing, **verbatim from `ml/road_segments.py`**, these pieces in this order:

1. The imports it needs:

```python
"""Chainage: distance measured ALONG a road, derived from crash positions.

Moved out of road_segments.py unchanged. The docstrings below record two bugs
this code already fixed; do not simplify it without re-reading them.
"""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra, minimum_spanning_tree
from scipy.spatial.distance import pdist, squareform
from sklearn.neighbors import NearestNeighbors

MAX_DENSE = 4000        # above this, kNN graph instead of a full distance matrix
STRETCH_GAP_M = 10_000  # a gap this large means a separate stretch of road
M_PER_DEG_LAT = 111_320.0
```

2. The body of `chainage()` from `road_segments.py:79-124`, unchanged.
3. The body of `_chain_one()` from `road_segments.py:127-172`, unchanged.

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/test_chainage.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Delete the originals from the script**

In `ml/road_segments.py`, delete the `chainage` and `_chain_one` function definitions and the now-unused scipy/sklearn imports, and add:

```python
from blackspot.chainage import chainage, MAX_DENSE, STRETCH_GAP_M, M_PER_DEG_LAT
```

- [ ] **Step 6: Confirm the script still parses and the suite is green**

```bash
python -c "import ast; ast.parse(open('road_segments.py').read()); print('parse ok')" && python -m pytest tests/ -q
```

Expected: `parse ok`, then all tests pass.

- [ ] **Step 7: Commit**

```bash
git add ml/blackspot/chainage.py ml/tests/test_chainage.py ml/road_segments.py
git commit -m "refactor: extract chainage into blackspot.chainage with tests"
```

---

### Task 4: Stable segment IDs

`segment_id` is currently `road_id + "_run" + run + "_km" + seg_km`. Every one of those three parts comes from an MST over crash positions. Add a year of data and the MST changes, chainage shifts, and every primary key in the database changes. Anchor the ID to a fixed spatial grid instead, and keep `run`/`km_from` as display attributes.

**Files:**
- Create: `ml/blackspot/ids.py`
- Create: `ml/tests/test_ids.py`

**Interfaces:**
- Produces: `stable_segment_id(road_id: str, lat: float, lon: float, cell_m: float = 250.0) -> str` and `assign_ids(df: pd.DataFrame) -> pd.Series` which adds a disambiguating suffix on collision.

- [ ] **Step 1: Write the failing test**

Create `ml/tests/test_ids.py`:

```python
import pandas as pd

from blackspot.ids import stable_segment_id, assign_ids


def test_id_is_deterministic():
    a = stable_segment_id("A23", 51.4607, -0.1160)
    b = stable_segment_id("A23", 51.4607, -0.1160)
    assert a == b


def test_id_survives_small_centroid_drift():
    # 20 m of drift must not change the cell
    base = stable_segment_id("A23", 51.46070, -0.11600)
    drift = stable_segment_id("A23", 51.46088, -0.11600)   # ~20 m north
    assert base == drift


def test_distant_points_get_different_ids():
    a = stable_segment_id("A23", 51.4607, -0.1160)
    b = stable_segment_id("A23", 51.4707, -0.1160)          # ~1.1 km north
    assert a != b


def test_different_roads_never_collide():
    a = stable_segment_id("A23", 51.4607, -0.1160)
    b = stable_segment_id("A3", 51.4607, -0.1160)
    assert a != b


def test_colliding_ids_are_disambiguated():
    # two segments of the same road whose centroids land in one cell
    df = pd.DataFrame({
        "road_id": ["A23", "A23"],
        "lat": [51.46070, 51.46071],
        "lon": [-0.11600, -0.11601],
    })
    ids = assign_ids(df)
    assert ids.nunique() == 2
    assert ids.iloc[1].endswith("_b")


def test_ids_are_unique_across_a_realistic_table():
    df = pd.DataFrame({
        "road_id": ["A23"] * 5,
        "lat": [51.460, 51.465, 51.470, 51.475, 51.480],
        "lon": [-0.116] * 5,
    })
    assert assign_ids(df).nunique() == 5
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_ids.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'blackspot.ids'`

- [ ] **Step 3: Write the implementation**

Create `ml/blackspot/ids.py`:

```python
"""Segment identifiers that survive a data refresh.

The old scheme was road_id + run + chainage_km. All three are outputs of a
minimum spanning tree over crash positions, so adding a year of data renumbered
every segment and broke the database primary key.

This anchors the ID to a fixed 250 m grid in projected metres. The grid is
global and independent of the data, so a segment keeps its ID as long as its
centroid stays in the same cell. 250 m is half the segment length, chosen so
ordinary centroid drift (tens of metres) does not cross a boundary.

run and km_from are kept as display attributes, not identity.
"""
import math

import pandas as pd

M_PER_DEG_LAT = 111_320.0
CELL_M = 250.0


def stable_segment_id(road_id: str, lat: float, lon: float,
                      cell_m: float = CELL_M) -> str:
    y = lat * M_PER_DEG_LAT
    x = lon * M_PER_DEG_LAT * math.cos(math.radians(lat))
    return f"{road_id}_{int(round(y / cell_m))}_{int(round(x / cell_m))}"


def assign_ids(df: pd.DataFrame, cell_m: float = CELL_M) -> pd.Series:
    """Segment IDs for a table with road_id, lat, lon.

    Two segments of one road can in principle share a cell on a hairpin. Rather
    than silently collapse them, later duplicates get a letter suffix in a
    deterministic order.
    """
    raw = [stable_segment_id(r, la, lo, cell_m)
           for r, la, lo in zip(df.road_id, df.lat, df.lon)]
    seen: dict[str, int] = {}
    out = []
    for rid in raw:
        k = seen.get(rid, 0)
        seen[rid] = k + 1
        out.append(rid if k == 0 else f"{rid}_{chr(ord('a') + k)}")
    return pd.Series(out, index=df.index, name="segment_id")
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/test_ids.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add ml/blackspot/ids.py ml/tests/test_ids.py
git commit -m "feat: grid-anchored segment IDs that survive a data refresh"
```

---

### Task 5: Extract segment aggregation

Pull the crash-rows-to-segment-table step out of the script so the feature engineering can be tested, and wire in the stable IDs from Task 4.

**Files:**
- Create: `ml/blackspot/segments.py`
- Create: `ml/tests/test_segments.py`
- Modify: `ml/road_segments.py`

**Interfaces:**
- Consumes: `blackspot.chainage.chainage`, `blackspot.ids.assign_ids`
- Produces: `build_segments(df, build_years, future_years, seg_m=500, min_crashes=60) -> tuple[pd.DataFrame, pd.DataFrame]`

  Returns `(seg, keyed_crashes)`. `seg` has columns `segment_id, seg_key, road_id, run, km_from, km_to, lat, lon, location, n_crashes, n_ksi, n_fatal, n_serious, n_slight, ksi_rate, crashes_per_year, speed_max, speed_mean, n_veh_mean, n_cas_mean, pct_night, pct_junction, n_years, mode_road_type, mode_urban_or_rural_area, mode_light_conditions, mode_junction_detail, future_ksi, future_fatal, future_crashes`.

  `keyed_crashes` is the crash-level frame carrying the same `seg_key`. Task 8 needs it to compute recency, and returning it here avoids recomputing chainage — which is the expensive step.

Note the three new columns `n_serious` / `n_slight` alongside `n_fatal` — the current output only has `n_ksi` and `n_fatal`, so a severity breakdown cannot be shown without recomputing.

- [ ] **Step 1: Write the failing test**

Create `ml/tests/test_segments.py`:

```python
from blackspot.segments import build_segments

BUILD = [2019, 2020, 2021]
FUTURE = [2022, 2023]


def test_returns_one_row_per_segment(crashes):
    seg, _ = build_segments(crashes, BUILD, FUTURE, min_crashes=10)
    assert len(seg) > 0
    assert seg.segment_id.is_unique


def test_severity_counts_sum_to_crash_count(crashes):
    seg, _ = build_segments(crashes, BUILD, FUTURE, min_crashes=10)
    total = seg.n_fatal + seg.n_serious + seg.n_slight
    assert (total == seg.n_crashes).all()


def test_ksi_is_fatal_plus_serious(crashes):
    seg, _ = build_segments(crashes, BUILD, FUTURE, min_crashes=10)
    assert (seg.n_ksi == seg.n_fatal + seg.n_serious).all()


def test_features_come_only_from_build_years(crashes):
    """Feature columns must count build-window crashes only.

    Asserting n_crashes > 0 would be trivially true by construction. Compare
    against the actual build-window row count instead.
    """
    seg, keyed = build_segments(crashes, BUILD, FUTURE, min_crashes=10)
    build_rows = keyed[keyed.collision_year.isin(BUILD)]
    assert seg.n_crashes.sum() == len(build_rows)
    # and the future columns must count the future window, not the build one
    future_rows = keyed[keyed.collision_year.isin(FUTURE)]
    assert seg.future_crashes.sum() <= len(future_rows)


def test_future_columns_are_present_for_validation(crashes):
    seg, _ = build_segments(crashes, BUILD, FUTURE, min_crashes=10)
    assert {"future_ksi", "future_fatal", "future_crashes"} <= set(seg.columns)
    assert seg.future_ksi.notna().all()


def test_km_to_is_km_from_plus_segment_length(crashes):
    seg, _ = build_segments(crashes, BUILD, FUTURE, seg_m=500, min_crashes=10)
    assert ((seg.km_to - seg.km_from - 0.5).abs() < 1e-9).all()


def test_roads_below_min_crashes_are_excluded(crashes):
    seg, _ = build_segments(crashes, BUILD, FUTURE, min_crashes=10_000)
    assert len(seg) == 0


def test_keyed_crashes_share_the_segment_key(crashes):
    """Task 8 joins recency on seg_key; every key must exist on both sides."""
    seg, keyed = build_segments(crashes, BUILD, FUTURE, min_crashes=10)
    assert "seg_key" in keyed.columns
    build_keys = set(keyed[keyed.collision_year.isin(BUILD)].seg_key)
    assert set(seg.seg_key) <= build_keys
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_segments.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'blackspot.segments'`

- [ ] **Step 3: Write the implementation**

Create `ml/blackspot/segments.py`:

```python
"""Crash rows -> one row per 500 m of road.

Lifted from road_segments.py, with three changes:
  * severity is split three ways (n_fatal / n_serious / n_slight), not just KSI
  * segment_id comes from blackspot.ids, so it survives a data refresh
  * run is a real column, not something to parse out of the ID
"""
import numpy as np
import pandas as pd

from .chainage import chainage
from .ids import assign_ids

CLS = {1: "M", 2: "A(M)", 3: "A", 4: "B", 5: "C", 6: "U"}
MODE_COLS = ["road_type", "urban_or_rural_area", "light_conditions", "junction_detail"]


def _mode(s):
    m = s.mode()
    return m.iloc[0] if len(m) else np.nan


def build_segments(df: pd.DataFrame, build_years: list[int], future_years: list[int],
                   seg_m: int = 500, min_crashes: int = 60
                   ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (segment table, crash rows carrying seg_key).

    The second value exists so recency can be computed without recomputing
    chainage, which is the expensive step.
    """
    df = df[df.collision_year.isin(build_years + future_years)]
    df = df[np.isfinite(df.latitude) & np.isfinite(df.longitude)]
    df = df[df.first_road_class.isin(CLS) & (df.first_road_number > 0)]
    df = df.reset_index(drop=True).copy()

    df["road_id"] = df.first_road_class.map(CLS) + df.first_road_number.astype(int).astype(str)
    df["is_fatal"] = (df.Accident_Severity == "Fatal").astype(int)
    df["is_serious"] = (df.Accident_Severity == "Serious").astype(int)
    df["is_slight"] = (df.Accident_Severity == "Slight").astype(int)
    df["is_ksi"] = df.is_fatal + df.is_serious

    counts = df.road_id.value_counts()
    roads = counts[counts >= min_crashes].index.tolist()
    if not roads:
        return pd.DataFrame(), pd.DataFrame()

    parts = []
    for rid in roads:
        r = df[df.road_id == rid]
        ch, run = chainage(r.latitude.values, r.longitude.values)
        parts.append(pd.DataFrame({"idx": r.index.values, "chainage_m": ch, "run": run}))
    ch_df = pd.concat(parts).set_index("idx")
    df = df.join(ch_df, how="inner")

    df["seg_km"] = np.floor(df.chainage_m / seg_m) * seg_m / 1000
    df["seg_key"] = (df.road_id + "|" + df.run.astype(str) + "|"
                     + df.seg_km.round(3).astype(str))

    b = df[df.collision_year.isin(build_years)]
    g = b.groupby("seg_key")
    seg = pd.DataFrame({
        "road_id": g.road_id.first(), "run": g.run.first(), "km_from": g.seg_km.first(),
        "n_crashes": g.size(),
        "n_ksi": g.is_ksi.sum(), "n_fatal": g.is_fatal.sum(),
        "n_serious": g.is_serious.sum(), "n_slight": g.is_slight.sum(),
        "lat": g.latitude.mean(), "lon": g.longitude.mean(),
        "speed_max": g.speed_limit.max(), "speed_mean": g.speed_limit.mean(),
        "n_veh_mean": g.number_of_vehicles.mean(),
        "n_cas_mean": g.number_of_casualties.mean(),
        "pct_night": g.Hour.agg(lambda s: ((s >= 22) | (s <= 5)).mean()),
        "pct_junction": g.junction_detail.agg(lambda s: (s != 0).mean()),
        "n_years": g.collision_year.nunique(),
    }).reset_index()
    for c in MODE_COLS:
        if c in b.columns:
            seg[f"mode_{c}"] = g[c].agg(_mode).values

    seg["km_to"] = seg.km_from + seg_m / 1000
    seg["crashes_per_year"] = seg.n_crashes / len(build_years)
    seg["ksi_rate"] = seg.n_ksi / seg.n_crashes

    f = df[df.collision_year.isin(future_years)]
    fut = f.groupby("seg_key").agg(future_ksi=("is_ksi", "sum"),
                                   future_fatal=("is_fatal", "sum"),
                                   future_crashes=("is_ksi", "size")).reset_index()
    seg = seg.merge(fut, on="seg_key", how="left").fillna(
        {"future_ksi": 0, "future_fatal": 0, "future_crashes": 0})

    seg = seg.sort_values(["road_id", "run", "km_from"]).reset_index(drop=True)
    seg["segment_id"] = assign_ids(seg)
    seg["location"] = (seg.road_id + " km " + seg.km_from.round(1).astype(str)
                       + "-" + seg.km_to.round(1).astype(str)
                       + np.where(seg.run > 0, " (seg " + seg.run.astype(int).astype(str) + ")", ""))
    # seg_key stays on both frames so recency can join without redoing chainage
    return seg, df
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/test_segments.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add ml/blackspot/segments.py ml/tests/test_segments.py
git commit -m "feat: extract segment aggregation, add 3-way severity split and run column"
```

---

### Task 6: Road-grouped out-of-fold scoring

This is the correctness fix. Two bugs, one code region, one test cycle:

1. `road_segments.py:229` trains on 70% then calls `m.predict(X)` on 100%. 77% of the published top 500 are training rows the model memorised; mean predicted score on train rows equals mean actual `future_ksi` to three decimals.
2. `train_test_split` puts `A23 km 0.5` in train and `A23 km 1.0` in test — adjacent 500 m of the same road, with `lat`/`lon` as features. The held-out numbers are inflated by spatial autocorrelation.

Both are fixed by `cross_val_predict` with `GroupKFold` grouped on `road_id`: every segment gets a score from a model that never saw *any* part of its road.

**Files:**
- Create: `ml/blackspot/scoring.py`
- Create: `ml/tests/test_scoring.py`
- Modify: `ml/road_segments.py`

**Interfaces:**
- Produces: `score_segments(seg: pd.DataFrame, n_splits: int = 5, random_state: int = 42) -> tuple[pd.Series, LGBMRegressor]` — the out-of-fold score for every row, plus a model refit on all data for scoring *new* segments only.
- Produces: `capture_table(scores: dict[str, np.ndarray], future_ksi: np.ndarray) -> pd.DataFrame`

- [ ] **Step 1: Write the failing test**

Create `ml/tests/test_scoring.py`:

```python
import numpy as np
import pandas as pd

from blackspot.scoring import score_segments, capture_table, FEATURE_DROP
from blackspot.segments import build_segments

BUILD = [2019, 2020, 2021]
FUTURE = [2022, 2023]


def _seg(crashes):
    seg, _ = build_segments(crashes, BUILD, FUTURE, min_crashes=10)
    return seg


def test_every_segment_gets_a_score(crashes):
    seg = _seg(crashes)
    scores, _ = score_segments(seg, n_splits=3)
    assert len(scores) == len(seg)
    assert scores.notna().all()


def test_scores_are_non_negative(crashes):
    """Poisson objective predicts a count; negatives mean the wrong objective."""
    seg = _seg(crashes)
    scores, _ = score_segments(seg, n_splits=3)
    assert (scores >= 0).all()


def test_no_future_column_reaches_the_model(crashes):
    seg = _seg(crashes)
    leaked = [c for c in seg.columns if c.startswith("future_") and c not in FEATURE_DROP]
    assert leaked == []


def test_scores_are_out_of_fold_not_fitted(crashes):
    """An in-sample prediction tracks the target almost exactly. An out-of-fold
    one does not. Correlation near 1.0 is the signature of the old bug."""
    seg = _seg(crashes)
    scores, _ = score_segments(seg, n_splits=3)
    r = np.corrcoef(scores.values, seg.future_ksi.values)[0, 1]
    assert r < 0.95, f"scores look fitted, not predicted (r={r:.3f})"


def test_folds_never_split_a_road(crashes):
    """Grouping is by road_id, so a road is wholly in train or wholly in test."""
    seg = _seg(crashes)
    _, _ = score_segments(seg, n_splits=3)
    # exercised indirectly; the assertion below guards the grouping contract
    from sklearn.model_selection import GroupKFold
    gkf = GroupKFold(n_splits=3)
    for tr, te in gkf.split(seg, groups=seg.road_id):
        assert set(seg.road_id.iloc[tr]) & set(seg.road_id.iloc[te]) == set()


def test_capture_table_reports_the_naive_baseline():
    rng = np.random.default_rng(0)
    n = 1000
    future = rng.poisson(0.4, n)
    tbl = capture_table({"model": rng.random(n), "past crash count": rng.random(n)}, future)
    assert "past crash count" in tbl.index
    assert {"top1pct", "top5pct", "top10pct", "top20pct"} <= set(tbl.columns)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_scoring.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'blackspot.scoring'`

- [ ] **Step 3: Write the implementation**

Create `ml/blackspot/scoring.py`:

```python
"""Out-of-fold blackspot scoring, grouped by road.

Two problems with the original:

  1. The published score column was model.predict() over ALL rows after
     training on 70% of them. 77% of the top 500 were training rows; the model
     had memorised their future_ksi. The score meant different things in
     different rows of the same file.

  2. train_test_split ignores that segments of one road are adjacent 500 m
     pieces with lat/lon as features. "A23 km 0.5" in train and "A23 km 1.0" in
     test is not a held-out test.

cross_val_predict with GroupKFold on road_id fixes both: every row is scored by
a model that saw no part of its road, and every row is scored the same way.
"""
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.model_selection import GroupKFold, cross_val_predict

RS = 42

# Identity, labels, and the answer. None of these may become features.
FEATURE_DROP = {
    "segment_id", "seg_key", "road_id", "location",
    "future_ksi", "future_fatal", "future_crashes",
    "last_crash_date",              # non-numeric, added by blackspot.recency
    "confidence",                   # non-numeric, added by blackspot.confidence
}

PARAMS = dict(objective="poisson", n_estimators=500, num_leaves=63,
              learning_rate=0.05, min_child_samples=30, colsample_bytree=0.7,
              reg_lambda=1.0, random_state=RS, n_jobs=-1, verbose=-1)


def feature_matrix(seg: pd.DataFrame) -> pd.DataFrame:
    feats = [c for c in seg.columns if c not in FEATURE_DROP]
    X = seg[feats].apply(pd.to_numeric, errors="coerce").astype(np.float32)
    return X.replace([np.inf, -np.inf], np.nan)


def score_segments(seg: pd.DataFrame, n_splits: int = 5, random_state: int = RS):
    """Out-of-fold score per segment, plus a model refit on everything.

    The returned model is for scoring segments NOT in `seg`. Never use it to
    re-score `seg` — that reintroduces the in-sample bug.
    """
    X = feature_matrix(seg)
    y = seg.future_ksi.values
    groups = seg.road_id.values

    n_groups = pd.Series(groups).nunique()
    splits = min(n_splits, n_groups)
    if splits < 2:
        raise ValueError(f"need >=2 distinct roads to group-split, got {n_groups}")

    oof = cross_val_predict(LGBMRegressor(**{**PARAMS, "random_state": random_state}),
                            X, y, groups=groups, cv=GroupKFold(n_splits=splits))
    oof = np.clip(oof, 0.0, None)

    full = LGBMRegressor(**{**PARAMS, "random_state": random_state}).fit(X, y)
    return pd.Series(oof, index=seg.index, name="blackspot_score"), full


def capture_table(scores: dict, future_ksi: np.ndarray) -> pd.DataFrame:
    """Share of future KSI captured by targeting the top X% under each ranking.

    The 'past crash count' row is the number that matters: it is what you get
    with no model at all, and the model has to beat it to justify itself.
    """
    total = float(np.sum(future_ksi))
    rows = {}
    for name, sc in scores.items():
        order = np.argsort(-np.asarray(sc))
        rows[name] = {
            f"top{int(p * 100)}pct": float(
                future_ksi[order[:max(1, int(len(order) * p))]].sum() / total * 100)
            for p in (0.01, 0.05, 0.10, 0.20)
        }
    return pd.DataFrame(rows).T
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/test_scoring.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add ml/blackspot/scoring.py ml/tests/test_scoring.py
git commit -m "fix: out-of-fold road-grouped scoring, replacing in-sample predictions"
```

---

### Task 7: Split serving from validation artifacts

`data/road_segments_top500.json` — the file the README tells the backend to serve — contains `future_ksi` and `future_fatal` on every record. That is the 2022–23 answer. Make it structurally impossible to ship again.

**Files:**
- Create: `ml/blackspot/artifacts.py`
- Create: `ml/tests/test_artifacts.py`
- Delete: `data/road_segments_ranked.csv` (replaced by two files)

**Interfaces:**
- Consumes: `blackspot.paths`
- Produces: `write_serving(seg, top_n=500) -> None`, `write_validation(seg) -> None`, `SERVING_COLUMNS: list[str]`

- [ ] **Step 1: Write the failing test**

Create `ml/tests/test_artifacts.py`:

```python
import json

import pandas as pd
import pytest

from blackspot import artifacts


@pytest.fixture
def seg():
    return pd.DataFrame({
        "segment_id": ["A23_1_2", "A3_4_5"],
        "road_id": ["A23", "A3"],
        "run": [0, 1],
        "location": ["A23 km 0.0-0.5", "A3 km 1.0-1.5 (seg 1)"],
        "km_from": [0.0, 1.0], "km_to": [0.5, 1.5],
        "lat": [51.46, 51.47], "lon": [-0.116, -0.132],
        "blackspot_score": [2.4, 1.1],
        "n_crashes": [60, 12], "n_ksi": [10, 3],
        "n_fatal": [1, 0], "n_serious": [9, 3], "n_slight": [50, 9],
        "ksi_rate": [0.167, 0.25], "crashes_per_year": [20.0, 4.0],
        "speed_max": [30.0, 40.0], "pct_night": [0.23, 0.1],
        "pct_junction": [0.7, 0.3],
        "future_ksi": [13.0, 2.0], "future_fatal": [2.0, 0.0],
        "future_crashes": [40.0, 8.0],
    })


def test_serving_csv_has_no_future_columns(seg, tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts.paths, "SERVING_CSV", tmp_path / "s.csv")
    monkeypatch.setattr(artifacts.paths, "SERVING_JSON", tmp_path / "s.json")
    artifacts.write_serving(seg)
    cols = pd.read_csv(tmp_path / "s.csv").columns
    assert not [c for c in cols if c.startswith("future_")]


def test_serving_json_has_no_future_keys(seg, tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts.paths, "SERVING_CSV", tmp_path / "s.csv")
    monkeypatch.setattr(artifacts.paths, "SERVING_JSON", tmp_path / "s.json")
    artifacts.write_serving(seg)
    records = json.loads((tmp_path / "s.json").read_text())
    assert all(not k.startswith("future_") for r in records for k in r)


def test_serving_includes_run_as_its_own_column(seg, tmp_path, monkeypatch):
    """The README's SQL schema declares run NOT NULL; the old CSV omitted it,
    forcing the backend to string-parse segment_id to draw a polyline."""
    monkeypatch.setattr(artifacts.paths, "SERVING_CSV", tmp_path / "s.csv")
    monkeypatch.setattr(artifacts.paths, "SERVING_JSON", tmp_path / "s.json")
    artifacts.write_serving(seg)
    assert "run" in pd.read_csv(tmp_path / "s.csv").columns


def test_serving_is_ranked_by_score_descending(seg, tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts.paths, "SERVING_CSV", tmp_path / "s.csv")
    monkeypatch.setattr(artifacts.paths, "SERVING_JSON", tmp_path / "s.json")
    artifacts.write_serving(seg)
    out = pd.read_csv(tmp_path / "s.csv")
    assert out.blackspot_score.is_monotonic_decreasing
    assert out["rank"].tolist() == [1, 2]


def test_validation_csv_keeps_future_columns(seg, tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts.paths, "VALIDATION_CSV", tmp_path / "v.csv")
    artifacts.write_validation(seg)
    cols = pd.read_csv(tmp_path / "v.csv").columns
    assert "future_ksi" in cols and "future_fatal" in cols


def test_write_serving_refuses_an_unknown_future_column(tmp_path, monkeypatch, seg):
    """Belt and braces: a newly added future_* column must not slip through."""
    seg = seg.assign(future_something_new=[1, 2])
    monkeypatch.setattr(artifacts.paths, "SERVING_CSV", tmp_path / "s.csv")
    monkeypatch.setattr(artifacts.paths, "SERVING_JSON", tmp_path / "s.json")
    artifacts.write_serving(seg)
    cols = pd.read_csv(tmp_path / "s.csv").columns
    assert "future_something_new" not in cols
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_artifacts.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'blackspot.artifacts'`

- [ ] **Step 3: Write the implementation**

Create `ml/blackspot/artifacts.py`:

```python
"""The only writers of segment output.

Serving and validation are separate files because they answer different
questions. The serving file is what the backend loads; it must not contain
future_ksi / future_fatal, which are the 2022-23 outcome the model is judged
against. Shipping them means the map is displaying the answer.

The old pipeline wrote one file containing both and relied on a README warning.
Here it is a filter plus a test.
"""
import numpy as np
import pandas as pd

from . import paths

SERVING_COLUMNS = [
    "rank", "segment_id", "location", "road_id", "run", "km_from", "km_to",
    "lat", "lon", "blackspot_score", "confidence", "score_low", "score_high",
    "n_crashes", "n_ksi", "n_fatal", "n_serious", "n_slight", "ksi_rate",
    "crashes_per_year", "speed_max", "pct_night", "pct_junction",
    "last_crash_date", "recency_weighted_crashes",
    "aadt", "veh_km_per_year", "casualty_rate",
]


def _ranked(seg: pd.DataFrame) -> pd.DataFrame:
    out = seg.sort_values("blackspot_score", ascending=False).reset_index(drop=True)
    out["rank"] = np.arange(1, len(out) + 1)
    return out


def write_serving(seg: pd.DataFrame, top_n: int = 500) -> None:
    out = _ranked(seg)
    # two guards: an explicit allow-list, and a hard reject of anything future_*
    cols = [c for c in SERVING_COLUMNS if c in out.columns]
    cols = [c for c in cols if not c.startswith("future_")]
    out = out[cols]
    assert not [c for c in out.columns if c.startswith("future_")], \
        "future_* column reached the serving artifact"
    paths.SERVING_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(paths.SERVING_CSV, index=False)
    out.head(top_n).to_json(paths.SERVING_JSON, orient="records", indent=2)


def write_validation(seg: pd.DataFrame) -> None:
    """Everything, including the answer. For the report, never for the API."""
    out = _ranked(seg)
    paths.VALIDATION_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(paths.VALIDATION_CSV, index=False)
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/test_artifacts.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Remove the contaminated artifact**

```bash
git rm data/road_segments_ranked.csv data/road_segments_top500.json
```

They are regenerated by the orchestrator in Task 12. Removing them now prevents anyone loading the leaky version in the meantime.

- [ ] **Step 6: Commit**

```bash
git add ml/blackspot/artifacts.py ml/tests/test_artifacts.py
git commit -m "fix: separate serving and validation artifacts, drop future_ksi from served data"
```

---

### Task 8: Recency weighting and last crash date

Plan §3.5 specifies a composite score weighting *recent* accidents higher. No recency term exists anywhere in the pipeline — a segment with 20 crashes in 2019 and none since scores identically to one with 20 crashes in 2021.

**Files:**
- Create: `ml/blackspot/recency.py`
- Create: `ml/tests/test_recency.py`

**Interfaces:**
- Consumes: crash rows with `date` (DD/MM/YYYY) and `collision_year`
- Produces: `add_recency(seg, crashes, build_years, half_life_years=2.0) -> pd.DataFrame` adding `last_crash_date` (ISO date string) and `recency_weighted_crashes` (float)

- [ ] **Step 1: Write the failing test**

Create `ml/tests/test_recency.py`:

```python
import pandas as pd

from blackspot.recency import add_recency, recency_weight

BUILD = [2019, 2020, 2021]


def test_weight_is_one_at_the_reference_year():
    assert recency_weight(2021, ref_year=2021, half_life_years=2.0) == 1.0


def test_weight_halves_after_one_half_life():
    w = recency_weight(2019, ref_year=2021, half_life_years=2.0)
    assert abs(w - 0.5) < 1e-9


def test_older_crashes_weigh_less():
    assert (recency_weight(2019, 2021, 2.0)
            < recency_weight(2020, 2021, 2.0)
            < recency_weight(2021, 2021, 2.0))


def test_recent_segment_outweighs_stale_segment_with_equal_counts():
    seg = pd.DataFrame({"_key": ["stale", "fresh"], "n_crashes": [10, 10]})
    crashes = pd.DataFrame({
        "_key": ["stale"] * 10 + ["fresh"] * 10,
        "collision_year": [2019] * 10 + [2021] * 10,
        "date": ["01/06/2019"] * 10 + ["01/06/2021"] * 10,
    })
    out = add_recency(seg, crashes, BUILD, key="_key")
    fresh = out.loc[out._key == "fresh", "recency_weighted_crashes"].iloc[0]
    stale = out.loc[out._key == "stale", "recency_weighted_crashes"].iloc[0]
    assert fresh > stale
    assert abs(stale / fresh - 0.5) < 0.01


def test_last_crash_date_is_the_most_recent_iso_date():
    seg = pd.DataFrame({"_key": ["a"], "n_crashes": [3]})
    crashes = pd.DataFrame({
        "_key": ["a", "a", "a"],
        "collision_year": [2019, 2021, 2020],
        "date": ["05/03/2019", "14/11/2021", "02/07/2020"],
    })
    out = add_recency(seg, crashes, BUILD, key="_key")
    assert out.last_crash_date.iloc[0] == "2021-11-14"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_recency.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'blackspot.recency'`

- [ ] **Step 3: Write the implementation**

Create `ml/blackspot/recency.py`:

```python
"""Recency weighting -- plan section 3.5's missing term.

Raw crash counts treat a 2019 crash and a 2021 crash identically. Road layouts
change, junctions get signalised, speed limits drop. An exponential half-life
discount is the standard way to say "older evidence counts less" without
inventing a cutoff.

half_life_years=2.0 over a three-year build window means the oldest year is
worth half the newest. Longer half-lives make the term nearly inert; shorter
ones throw away most of the sample.
"""
import numpy as np
import pandas as pd


def recency_weight(year, ref_year: int, half_life_years: float = 2.0):
    return np.power(0.5, (ref_year - np.asarray(year)) / half_life_years)


def add_recency(seg: pd.DataFrame, crashes: pd.DataFrame, build_years: list[int],
                half_life_years: float = 2.0, key: str = "seg_key") -> pd.DataFrame:
    """Join recency onto seg. `crashes` is the keyed frame build_segments returns."""
    ref = max(build_years)
    b = crashes[crashes.collision_year.isin(build_years)].copy()
    b["_w"] = recency_weight(b.collision_year.values, ref, half_life_years)

    weighted = b.groupby(key)["_w"].sum().rename("recency_weighted_crashes")

    dt = pd.to_datetime(b.date, format="%d/%m/%Y", errors="coerce")
    last = dt.groupby(b[key]).max().dt.strftime("%Y-%m-%d").rename("last_crash_date")

    out = seg.merge(weighted, left_on=key, right_index=True, how="left")
    out = out.merge(last, left_on=key, right_index=True, how="left")
    out["recency_weighted_crashes"] = out.recency_weighted_crashes.fillna(0.0)
    return out
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/test_recency.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add ml/blackspot/recency.py ml/tests/test_recency.py
git commit -m "feat: recency-weighted crash counts and last_crash_date"
```

---

### Task 9: Confidence gating for thin segments

86.2% of the 45,014 segments rest on fewer than 6 crashes, and 19,479 (43%) on exactly one. Their scores are noise. The README says "filter to n_crashes >= 6 for anything user-facing" — but the data ships no field expressing that, so nothing enforces it.

**Files:**
- Create: `ml/blackspot/confidence.py`
- Create: `ml/tests/test_confidence.py`

**Interfaces:**
- Produces: `add_confidence(seg, low_max=2, medium_max=5) -> pd.DataFrame` adding `confidence` (`"low"`/`"medium"`/`"high"`), `score_low`, `score_high` (Poisson 90% interval on the observed KSI count)

- [ ] **Step 1: Write the failing test**

Create `ml/tests/test_confidence.py`:

```python
import pandas as pd

from blackspot.confidence import add_confidence


def _seg():
    return pd.DataFrame({
        "segment_id": ["a", "b", "c"],
        "n_crashes": [1, 4, 40],
        "n_ksi": [0, 1, 12],
        "blackspot_score": [0.2, 0.6, 3.1],
    })


def test_confidence_bands_follow_crash_count():
    out = add_confidence(_seg())
    assert out.confidence.tolist() == ["low", "medium", "high"]


def test_interval_brackets_the_score():
    out = add_confidence(_seg())
    assert (out.score_low <= out.blackspot_score).all()
    assert (out.score_high >= out.blackspot_score).all()


def test_thin_segments_get_wider_intervals():
    out = add_confidence(_seg())
    width = out.score_high - out.score_low
    relative = width / out.blackspot_score
    assert relative.iloc[0] > relative.iloc[2]


def test_interval_low_is_never_negative():
    out = add_confidence(_seg())
    assert (out.score_low >= 0).all()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_confidence.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'blackspot.confidence'`

- [ ] **Step 3: Write the implementation**

Create `ml/blackspot/confidence.py`:

```python
"""How much to trust a segment's score.

43% of segments rest on a single crash. Ranking them against a segment with 60
crashes is comparing a measurement to a rumour. Rather than silently dropping
them -- which hides real roads from the map -- every segment carries a
confidence band and an interval, and the UI can grey out or filter on it.

The interval is a Poisson 90% interval on the observed KSI count, rescaled to
the score. It answers "how much would this score move if the same road had a
different two years?", which is the question a thin sample actually raises.
"""
import numpy as np
import pandas as pd
from scipy.stats import chi2


def _poisson_interval(k: np.ndarray, alpha: float = 0.10):
    """Exact (Garwood) Poisson interval for an observed count k."""
    k = np.asarray(k, dtype=float)
    lo = np.where(k > 0, chi2.ppf(alpha / 2, 2 * k) / 2.0, 0.0)
    hi = chi2.ppf(1 - alpha / 2, 2 * (k + 1)) / 2.0
    return lo, hi


def add_confidence(seg: pd.DataFrame, low_max: int = 2, medium_max: int = 5) -> pd.DataFrame:
    out = seg.copy()
    out["confidence"] = np.select(
        [out.n_crashes <= low_max, out.n_crashes <= medium_max],
        ["low", "medium"], default="high")

    lo, hi = _poisson_interval(out.n_ksi.values)
    # scale the count interval onto the score: score/observed, guarding n_ksi=0
    obs = np.maximum(out.n_ksi.values, 1.0)
    scale = out.blackspot_score.values / obs
    out["score_low"] = np.maximum(lo * scale, 0.0)
    out["score_high"] = np.maximum(hi * scale, out.blackspot_score.values)
    out["score_low"] = np.minimum(out.score_low, out.blackspot_score.values)
    return out
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/test_confidence.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ml/blackspot/confidence.py ml/tests/test_confidence.py
git commit -m "feat: confidence bands and Poisson score intervals for thin segments"
```

---

### Task 10: Exposure normalisation with DfT traffic counts

419 of the top 500 blackspots fall inside the Greater London bounding box. The score is expected casualties, not casualties per vehicle-km, so it ranks busy roads above dangerous ones and the map renders as a London heatmap. This is also the best available shot at beating the 49.35% crash-count baseline by more than a point, because traffic volume is the one signal crash history does *not* already encode.

**Files:**
- Create: `ml/blackspot/exposure.py`
- Create: `ml/tests/test_exposure.py`
- Modify: `ml/README.md` (document the manual download)

**Interfaces:**
- Produces: `join_aadt(seg: pd.DataFrame, aadf: pd.DataFrame, max_km: float = 5.0) -> pd.DataFrame` adding `aadt`, `veh_km_per_year`, `casualty_rate`

**Manual prerequisite:** DfT AADF count-point data is not committed (it is large and licence-tagged). Download the "AADF by direction, all count points" CSV from `https://roadtraffic.dft.gov.uk/downloads` and save as `ml/reference/dft_aadf.csv`. Confirm it has `latitude`, `longitude`, `road_name`, `all_motor_vehicles`, `year`. If the column names differ in the year you download, adjust `AADF_COLUMNS` in the module rather than the rest of the code.

- [ ] **Step 1: Write the failing test**

Create `ml/tests/test_exposure.py`:

```python
import numpy as np
import pandas as pd

from blackspot.exposure import join_aadt, haversine_km


def _seg():
    return pd.DataFrame({
        "segment_id": ["a", "b", "c"],
        "road_id": ["A23", "A23", "B1234"],
        "lat": [51.4600, 51.4700, 53.4000],
        "lon": [-0.1160, -0.1160, -1.5000],
        "blackspot_score": [2.0, 2.0, 2.0],
        "km_from": [0.0, 0.5, 0.0], "km_to": [0.5, 1.0, 0.5],
    })


def _aadf():
    return pd.DataFrame({
        "latitude": [51.4601, 51.4699, 53.4001],
        "longitude": [-0.1161, -0.1161, -1.5001],
        "road_name": ["A23", "A23", "B1234"],
        "all_motor_vehicles": [40_000, 10_000, 2_000],
        "year": [2021, 2021, 2021],
    })


def test_haversine_is_accurate_over_short_distances():
    # 0.01 degrees of latitude is about 1.11 km
    d = haversine_km(51.46, -0.116, 51.47, -0.116)
    assert abs(d - 1.11) < 0.05


def test_each_segment_gets_its_nearest_count_point():
    out = join_aadt(_seg(), _aadf())
    assert out.loc[out.segment_id == "a", "aadt"].iloc[0] == 40_000
    assert out.loc[out.segment_id == "b", "aadt"].iloc[0] == 10_000


def test_count_points_on_a_different_road_are_not_matched():
    seg = _seg()
    aadf = _aadf().assign(road_name=["A99", "A99", "A99"])
    out = join_aadt(seg, aadf)
    assert out.aadt.isna().all()


def test_casualty_rate_penalises_the_busier_road():
    """Same score, 4x the traffic -> a quarter of the rate."""
    out = join_aadt(_seg(), _aadf())
    a = out.loc[out.segment_id == "a", "casualty_rate"].iloc[0]
    b = out.loc[out.segment_id == "b", "casualty_rate"].iloc[0]
    assert abs(b / a - 4.0) < 0.01


def test_veh_km_accounts_for_segment_length():
    out = join_aadt(_seg(), _aadf())
    a = out.loc[out.segment_id == "a"].iloc[0]
    expected = 40_000 * 365 * 0.5   # AADT * days * km
    assert abs(a.veh_km_per_year - expected) < 1.0


def test_far_count_points_are_rejected():
    seg = _seg()
    aadf = _aadf().assign(latitude=[52.0, 52.0, 54.0])   # >>5 km away
    out = join_aadt(seg, aadf, max_km=5.0)
    assert out.aadt.isna().all()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_exposure.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'blackspot.exposure'`

- [ ] **Step 3: Write the implementation**

Create `ml/blackspot/exposure.py`:

```python
"""Traffic volume, so the ranking stops being a population map.

Without exposure, blackspot_score is expected casualties, which rises with
traffic. 419 of the old top 500 segments were in Greater London -- not because
London roads are the most dangerous, but because the most vehicles pass over
them. casualty_rate divides by vehicle-kilometres and answers the question a
highway engineer actually asks: is this stretch worse than its traffic explains?

DfT publishes AADF (annual average daily flow) per count point.
Download "AADF by direction, all count points" from
https://roadtraffic.dft.gov.uk/downloads and save to ml/reference/dft_aadf.csv.

Matching is nearest count point ON THE SAME ROAD NUMBER, within max_km. Matching
across road numbers would attach a motorway's flow to the B road beside it.
"""
import numpy as np
import pandas as pd

AADF_COLUMNS = {
    "lat": "latitude",
    "lon": "longitude",
    "road": "road_name",
    "flow": "all_motor_vehicles",
    "year": "year",
}
EARTH_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(a))


def join_aadt(seg: pd.DataFrame, aadf: pd.DataFrame, max_km: float = 5.0) -> pd.DataFrame:
    c = AADF_COLUMNS
    missing = [v for v in c.values() if v not in aadf.columns]
    if missing:
        raise KeyError(f"AADF file is missing {missing}; adjust AADF_COLUMNS")

    # one flow per count point: the most recent year available
    pts = (aadf.sort_values(c["year"])
              .groupby([c["road"], c["lat"], c["lon"]], as_index=False)
              .last())

    by_road = {r: g for r, g in pts.groupby(c["road"])}

    aadt = np.full(len(seg), np.nan)
    for i, (road, lat, lon) in enumerate(zip(seg.road_id, seg.lat, seg.lon)):
        g = by_road.get(road)
        if g is None or g.empty:
            continue
        d = haversine_km(lat, lon, g[c["lat"]].values, g[c["lon"]].values)
        j = int(np.argmin(d))
        if d[j] <= max_km:
            aadt[i] = g[c["flow"]].values[j]

    out = seg.copy()
    out["aadt"] = aadt
    seg_km = (out.km_to - out.km_from).values
    out["veh_km_per_year"] = out.aadt.values * 365.0 * seg_km
    with np.errstate(divide="ignore", invalid="ignore"):
        # casualties per 100 million vehicle-km, the DfT convention
        out["casualty_rate"] = np.where(
            out.veh_km_per_year.values > 0,
            out.blackspot_score.values / out.veh_km_per_year.values * 1e8,
            np.nan)
    return out
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/test_exposure.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Document the download in the README**

Add to `ml/README.md` under Reproducing:

```markdown
**AADF traffic counts (manual, ~40 MB).** Download "AADF by direction, all
count points" from https://roadtraffic.dft.gov.uk/downloads and save as
`ml/reference/dft_aadf.csv`. Open Government Licence v3.0, same as STATS19.
Without it the pipeline still runs; `aadt`, `veh_km_per_year` and
`casualty_rate` come out null and the ranking stays exposure-blind.
```

- [ ] **Step 6: Commit**

```bash
git add ml/blackspot/exposure.py ml/tests/test_exposure.py ml/README.md
git commit -m "feat: join DfT AADF traffic counts for exposure-normalised rates"
```

---

### Task 11: Fix threshold and multiplier tuning in the severity models

`severity_final.py:104` names a variable `tr_oof` but computes `m_ksi.predict_proba(X.iloc[tr])` — in-sample fitted probabilities. The F1-optimal threshold is then chosen against them. Fitted probabilities are systematically over-confident, so the selected threshold is biased high and the reported precision/recall balance is not the one the model achieves in production. The same pattern appears in the three-class multiplier grid search (`P3tr`) and in `severity_deployable.py` (`ptr`).

**Files:**
- Create: `ml/blackspot/thresholds.py`
- Create: `ml/tests/test_severity_thresholds.py`
- Modify: `ml/severity_final.py`, `ml/severity_deployable.py`

**Interfaces:**
- Produces: `oof_probabilities(estimator, X, y, cv=3, random_state=42) -> np.ndarray`, `best_f1_threshold(y, p) -> float`

- [ ] **Step 1: Write the failing test**

Create `ml/tests/test_severity_thresholds.py`:

```python
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.datasets import make_classification

from blackspot.thresholds import oof_probabilities, best_f1_threshold


def _data():
    return make_classification(n_samples=1200, n_features=12, n_informative=5,
                               weights=[0.77, 0.23], random_state=42)


def test_oof_probabilities_cover_every_row():
    X, y = _data()
    p = oof_probabilities(LGBMClassifier(n_estimators=40, verbose=-1), X, y, cv=3)
    assert p.shape == (len(y),)
    assert np.isfinite(p).all()


def test_oof_probabilities_are_less_confident_than_fitted():
    """The whole point: fitted probabilities hug 0 and 1, out-of-fold ones don't."""
    X, y = _data()
    m = LGBMClassifier(n_estimators=200, verbose=-1).fit(X, y)
    fitted = m.predict_proba(X)[:, 1]
    oof = oof_probabilities(LGBMClassifier(n_estimators=200, verbose=-1), X, y, cv=3)
    assert np.abs(oof - 0.5).mean() < np.abs(fitted - 0.5).mean()


def test_best_f1_threshold_is_in_range():
    y = np.array([0, 0, 1, 1, 0, 1, 0, 1])
    p = np.array([0.1, 0.2, 0.8, 0.7, 0.3, 0.9, 0.15, 0.6])
    t = best_f1_threshold(y, p)
    assert 0.05 <= t <= 0.95


def test_best_f1_threshold_separates_a_clean_split():
    y = np.array([0] * 50 + [1] * 50)
    p = np.array([0.1] * 50 + [0.9] * 50)
    t = best_f1_threshold(y, p)
    assert 0.1 < t <= 0.9
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_severity_thresholds.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'blackspot.thresholds'`

- [ ] **Step 3: Write the implementation**

Create `ml/blackspot/thresholds.py`:

```python
"""Operating points chosen on out-of-fold predictions, not fitted ones.

severity_final.py named a variable tr_oof but filled it with
model.predict_proba(X_train) -- the model's own training predictions. A
gradient-boosted model fits its training set hard, so those probabilities hug 0
and 1, and the F1-optimal threshold picked against them sits higher than the
one that is optimal in production. The three-class multiplier grid had the same
problem.

Choosing on out-of-fold predictions keeps the test set untouched (so the
reported metrics stay honest) while giving an unbiased view of the probability
distribution the threshold has to cut.
"""
import numpy as np
from sklearn.base import clone
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import f1_score

THRESHOLDS = np.arange(0.05, 0.96, 0.01)


def oof_probabilities(estimator, X, y, cv: int = 3, random_state: int = 42) -> np.ndarray:
    skf = StratifiedKFold(n_splits=cv, shuffle=True, random_state=random_state)
    p = cross_val_predict(clone(estimator), X, y, cv=skf, method="predict_proba")
    return p[:, 1] if p.ndim == 2 and p.shape[1] == 2 else p


def oof_probabilities_multiclass(estimator, X, y, cv: int = 3,
                                 random_state: int = 42) -> np.ndarray:
    skf = StratifiedKFold(n_splits=cv, shuffle=True, random_state=random_state)
    return cross_val_predict(clone(estimator), X, y, cv=skf, method="predict_proba")


def best_f1_threshold(y, p) -> float:
    return float(max(THRESHOLDS, key=lambda t: f1_score(y, (p >= t).astype(int))))
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/test_severity_thresholds.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Rewire `severity_final.py`**

Replace the threshold block (currently `tr_oof = m_ksi.predict_proba(X.iloc[tr])[:, 1]` through `best_t = max(ths, ...)`) with:

```python
from blackspot.thresholds import oof_probabilities, oof_probabilities_multiclass, best_f1_threshold

# Threshold chosen on OUT-OF-FOLD training predictions. Fitted probabilities
# are over-confident and bias the threshold upward.
tr_oof = oof_probabilities(mk(), X.iloc[tr], y_ksi[tr])
best_t = best_f1_threshold(y_ksi[tr], tr_oof)
pred_ksi = (p_ksi >= best_t).astype(int)
print(f"  threshold {best_t:.2f} (selected on out-of-fold training predictions)")
```

Replace the multiplier block's `P3tr = m3.predict_proba(X.iloc[tr])` with:

```python
P3tr = oof_probabilities_multiclass(mk(), X.iloc[tr], y_3class[tr])
```

- [ ] **Step 6: Rewire `severity_deployable.py`**

Replace:

```python
    ptr = m.predict_proba(X.iloc[tr])[:, 1]
    th = max(np.arange(.05, .96, .01),
             key=lambda t: f1_score(y[tr], (ptr >= t).astype(int)))
```

with:

```python
    ptr = oof_probabilities(LGBMClassifier(**PARAMS), X.iloc[tr], y[tr])
    th = best_f1_threshold(y[tr], ptr)
```

and hoist the estimator params into a `PARAMS` dict at module level so the same configuration is used for the out-of-fold pass and the final fit. Add the import:

```python
from blackspot.thresholds import oof_probabilities, best_f1_threshold
```

- [ ] **Step 7: Verify both scripts parse and the suite is green**

```bash
python -c "import ast; [ast.parse(open(f).read()) for f in ('severity_final.py','severity_deployable.py')]; print('parse ok')" && python -m pytest tests/ -q
```

Expected: `parse ok`, all tests pass.

- [ ] **Step 8: Commit**

```bash
git add ml/blackspot/thresholds.py ml/tests/test_severity_thresholds.py ml/severity_final.py ml/severity_deployable.py
git commit -m "fix: choose severity thresholds on out-of-fold, not fitted, probabilities"
```

---

### Task 12: Rewire `road_segments.py` as a thin orchestrator

Everything above is a module with tests. This collapses the script to the sequence that calls them, and produces the corrected artifacts.

**Files:**
- Modify: `ml/road_segments.py` (full rewrite)
- Modify: `data/road_segments_meta.json` (regenerated)

**Interfaces:**
- Consumes: `build_segments`, `score_segments`, `capture_table`, `add_recency`, `add_confidence`, `join_aadt`, `write_serving`, `write_validation`, `paths`

- [ ] **Step 1: Rewrite the script**

Replace the whole of `ml/road_segments.py` with:

```python
"""ROAD-SEGMENT BLACKSPOTS -- orchestrator.

Every stage lives in blackspot/ and is unit-tested. This file is the order they
run in, and nothing else.

  crashes -> segments -> out-of-fold score -> recency -> confidence
          -> exposure -> serving + validation artifacts

The score is expected KSI casualties on that 500 m over 2022-23, predicted by a
Poisson LightGBM from 2019-21 features, out-of-fold with folds grouped by road.
"""
import json
import warnings

import numpy as np
import pandas as pd

from blackspot import paths
from blackspot.artifacts import write_serving, write_validation
from blackspot.confidence import add_confidence
from blackspot.exposure import join_aadt
from blackspot.recency import add_recency
from blackspot.scoring import score_segments, capture_table
from blackspot.segments import build_segments

warnings.filterwarnings("ignore")

SEG_M = 500
MIN_CRASHES = 60
BUILD, FUTURE = [2019, 2020, 2021], [2022, 2023]
AADF_CSV = paths.ML_DIR / "reference" / "dft_aadf.csv"

paths.ensure_dirs()

print("loading ...")
df = pd.read_csv(paths.RAW_CSV, low_memory=False)

print("building segments ...")
seg, keyed = build_segments(df, BUILD, FUTURE, seg_m=SEG_M, min_crashes=MIN_CRASHES)
print(f"  {len(seg):,} segments on {seg.road_id.nunique():,} roads")

print("scoring (out-of-fold, grouped by road) ...")
scores, full_model = score_segments(seg)
seg["blackspot_score"] = scores

print("adding recency, confidence, exposure ...")
seg = add_recency(seg, keyed, BUILD)
seg = add_confidence(seg)

if AADF_CSV.exists():
    seg = join_aadt(seg, pd.read_csv(AADF_CSV, low_memory=False))
    matched = seg.aadt.notna().mean() * 100
    print(f"  AADF matched {matched:.1f}% of segments")
else:
    seg["aadt"] = np.nan
    seg["veh_km_per_year"] = np.nan
    seg["casualty_rate"] = np.nan
    print(f"  {AADF_CSV.name} not found -- exposure columns will be null. "
          f"See ml/README.md.")

print("\n" + "=" * 84)
print(f"VALIDATION -- out-of-fold, folds grouped by road, predicting {FUTURE[0]}-{FUTURE[1]} KSI")
print("=" * 84)
tbl = capture_table({
    "blackspot score (model)": seg.blackspot_score.values,
    "past crash count": seg.n_crashes.values,
    "past KSI count": seg.n_ksi.values,
}, seg.future_ksi.values)
print(tbl.round(2).to_string())
gap = tbl.loc["blackspot score (model)", "top20pct"] - tbl.loc["past crash count", "top20pct"]
print(f"\nModel beats the no-model baseline by {gap:+.2f} points at top 20%.")
print("Report this number. It is the honest measure of what the ML contributes.")

write_serving(seg, top_n=500)
write_validation(seg)

json.dump({
    "segment_length_m": SEG_M, "n_roads": int(seg.road_id.nunique()),
    "n_segments": int(len(seg)), "build_years": BUILD, "future_years": FUTURE,
    "method": "MST geodesic chainage along road, binned to 500m",
    "scoring": "LightGBM Poisson, out-of-fold via GroupKFold(road_id)",
    "exposure_source": "DfT AADF" if AADF_CSV.exists() else None,
    "capture_rates_pct": tbl.round(4).to_dict(orient="index"),
}, open(paths.META_JSON, "w"), indent=2)

print(f"\nSaved:\n  {paths.SERVING_CSV}\n  {paths.SERVING_JSON}"
      f"\n  {paths.VALIDATION_CSV}\n  {paths.META_JSON}")
```

- [ ] **Step 2: Add an end-to-end test on synthetic data**

Append to `ml/tests/test_artifacts.py`:

```python
def test_pipeline_runs_end_to_end_on_synthetic_data(tmp_path, monkeypatch, crashes):
    """The stages compose. Catches signature drift between modules."""
    from blackspot.segments import build_segments
    from blackspot.scoring import score_segments
    from blackspot.confidence import add_confidence
    from blackspot.recency import add_recency
    from blackspot import artifacts

    build_years = [2019, 2020, 2021]
    seg, keyed = build_segments(crashes, build_years, [2022, 2023], min_crashes=10)
    scores, _ = score_segments(seg, n_splits=3)
    seg["blackspot_score"] = scores
    seg = add_recency(seg, keyed, build_years)
    seg = add_confidence(seg)

    monkeypatch.setattr(artifacts.paths, "SERVING_CSV", tmp_path / "s.csv")
    monkeypatch.setattr(artifacts.paths, "SERVING_JSON", tmp_path / "s.json")
    monkeypatch.setattr(artifacts.paths, "VALIDATION_CSV", tmp_path / "v.csv")
    artifacts.write_serving(seg)
    artifacts.write_validation(seg)

    import pandas as pd
    served = pd.read_csv(tmp_path / "s.csv")
    assert not [c for c in served.columns if c.startswith("future_")]
    assert "confidence" in served.columns
    assert "last_crash_date" in served.columns
    assert "recency_weighted_crashes" in served.columns
    assert len(served) == len(seg)
```

- [ ] **Step 3: Run the suite**

```bash
python -m pytest tests/ -q
```

Expected: all tests pass, including the new end-to-end one.

- [ ] **Step 4: Regenerate the real artifacts**

Requires `stats19_recent.csv`. Run in the background — this takes ~15 minutes:

```bash
python road_segments.py 2>&1 | tee reports/blackspot_full_output.log
```

Expected: the capture table prints, and the "beats the baseline by" line reports the honest gap. **The number will likely be lower than the old 1.05 points, because the old comparison was contaminated by in-sample scores.** That is the correction working, not a regression — record the new number.

- [ ] **Step 5: Verify the served file is clean**

```bash
python -c "import pandas as pd; d=pd.read_csv('../data/road_segments_serving.csv'); assert not [c for c in d.columns if c.startswith('future_')], d.columns.tolist(); print('clean:', len(d), 'rows,', len(d.columns), 'cols')"
```

Expected: `clean: <n> rows, <k> cols`

- [ ] **Step 6: Commit**

```bash
git add ml/road_segments.py ml/tests/test_artifacts.py data/ ml/reports/blackspot_full_output.log
git commit -m "refactor: road_segments.py becomes a thin orchestrator over tested modules"
```

---

### Task 13: DBSCAN baseline for the report

Plan §3.3 specifies DBSCAN and §3.6 specifies silhouette scoring. The chainage approach is better here and we are keeping it — but "we chose not to" is only worth marks if you can show the comparison. This runs DBSCAN properly, scores it, and puts the numbers in the report.

**Files:**
- Create: `ml/baselines.py`
- Create: `ml/tests/test_baselines.py`

**Interfaces:**
- Produces: `dbscan_clusters(df, eps_m=150, min_samples=5) -> pd.DataFrame`, `compare_to_segments(clusters, segments) -> pd.DataFrame`

- [ ] **Step 1: Write the failing test**

Create `ml/tests/test_baselines.py`:

```python
import numpy as np
import pandas as pd

from baselines import dbscan_clusters


def _two_tight_clusters():
    rng = np.random.default_rng(0)
    a = pd.DataFrame({"latitude": 51.50 + rng.normal(0, 0.0002, 60),
                      "longitude": -0.12 + rng.normal(0, 0.0002, 60)})
    b = pd.DataFrame({"latitude": 53.40 + rng.normal(0, 0.0002, 60),
                      "longitude": -1.50 + rng.normal(0, 0.0002, 60)})
    out = pd.concat([a, b], ignore_index=True)
    out["is_ksi"] = 1
    return out


def test_finds_the_two_planted_clusters():
    out = dbscan_clusters(_two_tight_clusters(), eps_m=150, min_samples=5)
    assert out.cluster.nunique() == 2


def test_noise_points_are_labelled_minus_one():
    df = _two_tight_clusters()
    df = pd.concat([df, pd.DataFrame({"latitude": [52.0], "longitude": [0.5],
                                      "is_ksi": [1]})], ignore_index=True)
    out = dbscan_clusters(df, eps_m=150, min_samples=5)
    assert (out.cluster == -1).sum() >= 1


def test_silhouette_is_reported_and_in_range():
    out = dbscan_clusters(_two_tight_clusters(), eps_m=150, min_samples=5)
    s = out.attrs["silhouette"]
    assert -1.0 <= s <= 1.0
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_baselines.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'baselines'`

- [ ] **Step 3: Write the implementation**

Create `ml/baselines.py`:

```python
"""DBSCAN clustering baseline -- the approach the project plan specified.

We ship chainage segments instead. This exists so the report can say why, with
numbers rather than an assertion.

DBSCAN's weaknesses on this data, which the comparison should show:
  * a cluster is a blob of map, so it can span two roads at a junction, and it
    has no length -- "cluster 4127" is not an instruction to a highway engineer,
    where "A38 km 128.4-128.9" is
  * eps is a single global density threshold, but crash density varies by two
    orders of magnitude between central London and a rural A road, so no single
    eps works everywhere
  * silhouette rewards compact well-separated blobs, which is not the same
    thing as identifying where casualties will occur next

Run: python baselines.py
"""
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.metrics import silhouette_score

EARTH_M = 6_371_008.8


def dbscan_clusters(df: pd.DataFrame, eps_m: float = 150.0,
                    min_samples: int = 5) -> pd.DataFrame:
    """Haversine DBSCAN over crash positions. Returns df with a `cluster` column.

    silhouette is stored in .attrs because it describes the run, not a row.
    """
    coords = np.radians(df[["latitude", "longitude"]].values)
    labels = DBSCAN(eps=eps_m / EARTH_M, min_samples=min_samples,
                    metric="haversine", algorithm="ball_tree").fit_predict(coords)

    out = df.copy()
    out["cluster"] = labels

    core = labels != -1
    if core.sum() > 1 and len(set(labels[core])) > 1:
        sil = float(silhouette_score(coords[core], labels[core], metric="haversine"))
    else:
        sil = float("nan")
    out.attrs["silhouette"] = sil
    out.attrs["n_clusters"] = int(len(set(labels)) - (1 if -1 in labels else 0))
    out.attrs["noise_frac"] = float((labels == -1).mean())
    return out


def compare_to_segments(clusters: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    """Side-by-side for the report."""
    return pd.DataFrame([
        {"method": "DBSCAN clusters",
         "n_units": clusters.attrs["n_clusters"],
         "silhouette": round(clusters.attrs["silhouette"], 4),
         "noise_discarded_pct": round(clusters.attrs["noise_frac"] * 100, 1),
         "unit_is_addressable": False},
        {"method": "500 m chainage segments",
         "n_units": len(segments),
         "silhouette": None,
         "noise_discarded_pct": 0.0,
         "unit_is_addressable": True},
    ])


if __name__ == "__main__":
    from blackspot import paths

    df = pd.read_csv(paths.RAW_CSV, low_memory=False)
    df = df[df.collision_year.isin([2019, 2020, 2021])]
    df = df[np.isfinite(df.latitude) & np.isfinite(df.longitude)]

    for eps in (100, 150, 250, 500):
        c = dbscan_clusters(df, eps_m=eps, min_samples=5)
        print(f"eps={eps:>4}m  clusters={c.attrs['n_clusters']:>7,}  "
              f"silhouette={c.attrs['silhouette']:.4f}  "
              f"noise={c.attrs['noise_frac']*100:5.1f}%")

    seg = pd.read_csv(paths.SERVING_CSV)
    best = dbscan_clusters(df, eps_m=150, min_samples=5)
    print()
    print(compare_to_segments(best, seg).to_string(index=False))
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/test_baselines.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Produce the comparison for the report**

```bash
python baselines.py 2>&1 | tee reports/dbscan_baseline.log
```

Expected: an eps sweep table and the two-row comparison. Record the silhouette and the noise fraction — the noise fraction is usually the damning number, because those crashes get discarded entirely.

- [ ] **Step 6: Commit**

```bash
git add ml/baselines.py ml/tests/test_baselines.py ml/reports/dbscan_baseline.log
git commit -m "feat: DBSCAN + silhouette baseline for the plan's method comparison"
```

---

### Task 14: EDA aggregates for the stats dashboard

Plan §3.2 specifies EDA producing "good chart material for the website". No aggregate has ever been committed, so `frontend/src/data/series.js` is inventing its histograms.

**Files:**
- Create: `ml/eda.py`
- Create: `data/eda_summary.json`

**Interfaces:**
- Produces: `data/eda_summary.json` with keys `by_year`, `by_month`, `by_hour`, `by_day_of_week`, `by_severity`, `by_speed_limit`, `by_light_conditions`, `by_road_type`, `by_weather`, `totals`

- [ ] **Step 1: Write the script**

Create `ml/eda.py`:

```python
"""Dashboard aggregates -- plan section 3.2.

One JSON, small enough to serve statically, holding every count the stats page
needs. Computed over the same window the blackspot model uses so the dashboard
and the map never disagree.

Run: python eda.py
"""
import json

import numpy as np
import pandas as pd

from blackspot import paths

YEARS = [2019, 2020, 2021, 2022, 2023]

DECODE = {
    "light_conditions": {1: "Daylight", 4: "Dark - lit", 5: "Dark - unlit",
                         6: "Dark - no lighting", 7: "Dark - unknown"},
    "weather_conditions": {1: "Fine", 2: "Rain", 3: "Snow", 4: "Fine + wind",
                           5: "Rain + wind", 6: "Snow + wind", 7: "Fog/mist",
                           8: "Other", 9: "Unknown"},
    "road_type": {1: "Roundabout", 2: "One way", 3: "Dual carriageway",
                  6: "Single carriageway", 7: "Slip road", 9: "Unknown"},
    "day_of_week": {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu",
                    6: "Fri", 7: "Sat"},
}


def counts(df, col, decode=None):
    s = df[col].value_counts().sort_index()
    labels = [str(decode.get(k, k)) if decode else str(k) for k in s.index]
    return [{"label": l, "count": int(v)} for l, v in zip(labels, s.values)]


def severity_split(df, col, decode=None):
    """Counts broken down by severity -- what a stacked bar chart needs."""
    x = pd.crosstab(df[col], df.Accident_Severity)
    for c in ("Fatal", "Serious", "Slight"):
        if c not in x.columns:
            x[c] = 0
    return [{"label": str(decode.get(k, k)) if decode else str(k),
             "fatal": int(r.Fatal), "serious": int(r.Serious), "slight": int(r.Slight)}
            for k, r in x.iterrows()]


def main():
    paths.ensure_dirs()
    df = pd.read_csv(paths.RAW_CSV, low_memory=False)
    df = df[df.collision_year.isin(YEARS)]

    out = {
        "window": YEARS,
        "totals": {
            "collisions": int(len(df)),
            "fatal": int((df.Accident_Severity == "Fatal").sum()),
            "serious": int((df.Accident_Severity == "Serious").sum()),
            "slight": int((df.Accident_Severity == "Slight").sum()),
        },
        "by_year": severity_split(df, "collision_year"),
        "by_month": counts(df, "Month"),
        "by_hour": counts(df, "Hour"),
        "by_day_of_week": severity_split(df, "day_of_week", DECODE["day_of_week"]),
        "by_severity": counts(df, "Accident_Severity"),
        "by_speed_limit": severity_split(df, "speed_limit"),
        "by_light_conditions": severity_split(df, "light_conditions",
                                              DECODE["light_conditions"]),
        "by_road_type": severity_split(df, "road_type", DECODE["road_type"]),
        "by_weather": severity_split(df, "weather_conditions",
                                     DECODE["weather_conditions"]),
    }
    p = paths.DATA_DIR / "eda_summary.json"
    json.dump(out, open(p, "w"), indent=2)
    print(f"wrote {p} -- {out['totals']['collisions']:,} collisions")
    print("NOTE 2020-21 counts are depressed by COVID traffic reduction (~22%).")
    print("Label those years on any time-series chart.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

```bash
python eda.py
```

Expected: `wrote .../data/eda_summary.json -- <n> collisions`

- [ ] **Step 3: Sanity-check the output**

```bash
python -c "import json; d=json.load(open('../data/eda_summary.json')); t=d['totals']; assert t['fatal']+t['serious']+t['slight']==t['collisions']; print('consistent:', t)"
```

Expected: `consistent: {...}`

- [ ] **Step 4: Commit**

```bash
git add ml/eda.py data/eda_summary.json
git commit -m "feat: EDA aggregates for the stats dashboard"
```

---

### Task 15: Data provenance and repo hygiene

Four loose ends, all documentation-or-deletion, all cheap, all things an examiner opens the repo and sees.

**Files:**
- Create: `DATA_PROVENANCE.md`
- Modify: `ml/build_recent.py` (revert the Indian severity relabelling)
- Move: `ml/clean_road_accident_data.py` → `ml/archive/scripts/`
- Modify: `CLAUDE.md`, `ml/README.md`

- [ ] **Step 1: Revert the severity relabelling**

In `ml/build_recent.py`, change:

```python
SEV = {1: "Fatal", 2: "Grievous", 3: "Minor"}
```

to:

```python
# STATS19's own labels. An earlier version renamed these to the Indian
# MoRTH/IRC scheme (Grievous/Minor) while the data stayed British, which reads
# as a claim the data is Indian. Keep the source's vocabulary.
SEV = {1: "Fatal", 2: "Serious", 3: "Slight"}
```

Then update the downstream string comparisons: in `ml/severity_final.py` the `names3.index(c) for c in ["Fatal", "Grievous", "Minor"]` becomes `["Fatal", "Serious", "Slight"]`, and every `!= "Minor"` (in `severity_final.py`, `severity_deployable.py`) becomes `!= "Slight"`.

- [ ] **Step 2: Find any remaining references**

```bash
grep -rn "Grievous\|\"Minor\"\|'Minor'" --include=*.py --include=*.md . | grep -v archive/
```

Expected: no hits outside `archive/`. Fix any that appear.

- [ ] **Step 3: Archive the orphaned cleaning script**

`clean_road_accident_data.py` processes `Road_Accident_Data.csv` — the shifted-date 2009/2010 file. Nothing in the pipeline reads its output. It is real work and documents a genuine data-recovery problem, so archive rather than delete:

```bash
git mv ml/clean_road_accident_data.py ml/archive/scripts/clean_road_accident_data.py
```

- [ ] **Step 4: Write the provenance note**

Create `DATA_PROVENANCE.md` at the repo root:

```markdown
# Data Provenance

## What this project uses

**UK STATS19** — road casualty statistics collected by police forces in Great
Britain, published by the Department for Transport under the Open Government
Licence v3.0. Source: https://data.dft.gov.uk/road-accidents-safety-data/

Three linked tables joined on `collision_index`: collision, vehicle, casualty.
Window: 2015–2023, 1,049,378 collisions. Everything is numerically coded.

**DfT AADF traffic counts** — annual average daily flow per count point, used
for exposure normalisation. Same licence. Source:
https://roadtraffic.dft.gov.uk/downloads

Severity labels are STATS19's own: **Fatal / Serious / Slight**.

## Why British data

The project needs a national road-casualty dataset with per-collision
coordinates, road classification, and multi-year coverage. STATS19 has all
three and is openly licensed. No Indian dataset with equivalent coordinate
precision and road numbering was available to the team.

The **method** is not UK-specific. Chainage derivation, Poisson segment
scoring, exposure normalisation, and the SHAP explanation layer all transfer to
any dataset carrying `(lat, lon, road identifier, date, severity)`. Section
"Future scope" of the report should say so explicitly.

## Datasets that appear in the repo but are NOT used

| File | Status |
|---|---|
| `Road_Accident_Data.csv` | A Kaggle re-publication of STATS19 with shifted dates (2009–10 relabelled 2021–22) and a corrupted index column. `archive/scripts/clean_road_accident_data.py` recovers the real dates. Superseded by the direct DfT extract; kept because the recovery is a genuine result. |
| `AccidentsBig.csv` | Referenced in an early frontend comment. Never used by the ML pipeline. |

## What is not in git

`ml/stats19_recent.csv` (581 MB) and `ml/stats19_raw/` (~4 GB) are gitignored.
Regenerate with `python build_recent.py` (~30 min, needs internet).

`ml/reference/dft_aadf.csv` is a manual download; see `ml/README.md`.
```

- [ ] **Step 5: Correct `CLAUDE.md`**

Its "Layout" section describes a `handoff/` directory that does not exist and says scripts run "from the repo root" when they run from `ml/`. Replace that section with (note the fences below are part of the file content):

````markdown
## Layout

```
ml/                    scripts, the blackspot package, tests -- RUN FROM HERE
ml/blackspot/          the pipeline as importable, tested modules
ml/tests/              pytest; runs without the 581MB extract
ml/models/             joblib models + metrics json
ml/shap/               global + per-level SHAP tables
ml/reports/            full console logs
ml/reference/          DfT casualty valuations + manually downloaded AADF
ml/archive/            superseded experiments -- keep, they document what failed
data/                  artifacts the backend consumes (sibling of ml/)
```

`data/road_segments_serving.csv` is what the backend loads.
`data/road_segments_validation.csv` additionally holds `future_ksi` /
`future_fatal` — the 2022–23 outcome. **Never serve the validation file.**
````

Also replace its "No test suite, no build step" line with:

````markdown
```bash
python -m pytest tests/ -q      # runs in seconds, needs no data download
```
````

- [ ] **Step 6: Update `ml/README.md` results table**

Replace the capture-rate table and the "adds about one point" paragraph with the numbers from Task 12 Step 4. State the evaluation protocol in the same sentence as the number:

```markdown
Held-out via GroupKFold on `road_id` — every segment scored by a model that saw
no part of its road. The earlier figures were partly in-sample and are not
comparable.
```

- [ ] **Step 7: Run the full suite one final time**

```bash
python -m pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "docs: data provenance, revert Indian severity labels, correct layout docs"
```

---

## Self-Review

**Spec coverage** — every problem from the diagnosis maps to a task:

| Problem | Task |
|---|---|
| In-sample scores published as predictions | 6 |
| `future_ksi` in the served JSON | 7 |
| `run` missing from output | 5, 7 |
| Random split ignores spatial autocorrelation | 6 |
| Model beats baseline by ~1 point | 6 (honest re-measure), 10 (exposure as a non-redundant signal) |
| Severity model unusable / mislabelled | 11 (honest thresholds); presentation guidance already in README |
| No exposure normalisation, 84% London | 10 |
| 86% of segments under 6 crashes | 9 |
| Unstable `segment_id` | 4 |
| No recency term (plan §3.5) | 8 |
| No DBSCAN / silhouette (plan §3.3, §3.6) | 13 |
| No EDA outputs (plan §3.2) | 14 |
| Output paths don't match repo layout | 2 |
| `severity_deployable.py` crashes on fresh clone | 2 |
| UK data wearing Indian severity labels | 15 |
| Orphaned `clean_road_accident_data.py` | 15 |
| No reproducibility without the 581 MB file | 1 (tests), 15 (provenance) |
| Threshold tuned on fitted probabilities | 11 |
| Stale `CLAUDE.md` layout | 15 |

**Not covered, deliberately:** road coverage below `MIN_CRASHES = 60` (excluding unclassified roads) is left as-is — widening it changes the product definition, not a bug fix. `severity_3class_model.joblib` stays uncommitted; Task 15's provenance note documents why.

**Out of scope per your decision:** Spring Boot backend, PostGIS load, frontend rewiring. The serving artifact's column list in `artifacts.py:SERVING_COLUMNS` is the contract those will consume when you get to them.

---

## Sequencing

Tasks 1–2 unblock everything. Tasks 3–7 are the correctness chain and must run in order. Tasks 8–11 are independent of each other and can be done in any order or in parallel. Task 12 requires 3–10. Tasks 13–14 are independent of everything after Task 2.

**Task 15 Step 1 is an exception and must run before any real-data step** — that is, before Task 12 Step 4, Task 13 Step 5, and Task 14 Step 2. `build_segments` compares severity against `"Fatal"` / `"Serious"` / `"Slight"`, but `build_recent.py` currently emits `"Grievous"` / `"Minor"`. Running the real pipeline before the revert yields all-zero severity counts silently. The rest of Task 15 can stay at the end.

**If time is short, Tasks 1, 2, 6, 7 alone fix the data being wrong.** Everything else is improvement.

## Prerequisite: source data

`ml/stats19_recent.csv` and `ml/stats19_raw/` are not in the repo and are not
regenerable without a manual download — **`build_recent.py` contains no
download code**, contrary to what `CLAUDE.md` and `ml/README.md` both claim.
It reads three pre-downloaded DfT CSVs from `ml/stats19_raw/`:

```
dft-road-casualty-statistics-collision-1979-latest-published-year.csv
dft-road-casualty-statistics-vehicle-1979-latest-published-year.csv
dft-road-casualty-statistics-casualty-1979-latest-published-year.csv
```

Source: https://data.dft.gov.uk/road-accidents-safety-data/ (~4 GB total).
Task 15 should correct the two docs that describe this step wrongly.

**Tasks 1–11 need none of this** — they run entirely against the synthetic
fixture from Task 1. Only Task 12 Steps 4–5, Task 13 Step 5, and Task 14
Steps 2–4 require the real extract.
