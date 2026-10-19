"""Backend contract: the v2 file must be a drop-in superset of the v1 file."""
import json

import numpy as np
import pandas as pd
import pytest

from blackspot.config import BACKEND_DATA
from blackspot.outputs import LEGACY_COLS

V1 = BACKEND_DATA / "road_segments_ranked.csv"
V2 = BACKEND_DATA / "v2" / "road_segments_ranked_v2.csv"
META = BACKEND_DATA / "v2" / "road_segments_meta_v2.json"

needs_v2 = pytest.mark.skipif(not V2.exists(), reason="run `pipeline.py forecast` first")


def test_v1_file_untouched_schema():
    v1 = pd.read_csv(V1, nrows=5)
    assert list(v1.columns) == LEGACY_COLS


@needs_v2
def test_v2_starts_with_every_legacy_column_in_order():
    v2 = pd.read_csv(V2, nrows=5)
    assert list(v2.columns[:len(LEGACY_COLS)]) == LEGACY_COLS


@needs_v2
def test_v2_types_and_keys():
    v1 = pd.read_csv(V1, nrows=2000)
    v2 = pd.read_csv(V2, low_memory=False)
    for c in LEGACY_COLS:
        if c in ("future_ksi", "future_fatal"):
            assert v2[c].isna().all()                       # forecast period not observed
            continue
        assert pd.api.types.is_numeric_dtype(v1[c]) == pd.api.types.is_numeric_dtype(v2[c]), c
    assert v2.segment_id.is_unique                          # primary key
    assert v2["rank"].is_monotonic_increasing and v2["rank"].iloc[0] == 1
    assert v2.blackspot_score.is_monotonic_decreasing
    assert v2.lat.between(49.8, 61.0).all() and v2.lon.between(-8.7, 2.0).all()


@needs_v2
def test_meta_documents_every_changed_column():
    meta = json.loads(META.read_text())
    notes = " ".join(meta["legacy_column_notes"])
    for c in ["segment_id", "n_ksi", "n_fatal", "pct_junction", "future_ksi", "blackspot_score", "run"]:
        assert c in notes
    assert meta["frozen_spec_sha256"]
