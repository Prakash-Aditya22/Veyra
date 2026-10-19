"""Ranking-stability metrics and artefact integrity."""
import json

import numpy as np
import pandas as pd
import pytest

from blackspot.config import BACKEND_DATA, REPORTS
from blackspot.stability import (block_bootstrap_weights, mean_pairwise_overlap, membership_frequency,
                                 national_ranks, order_preserved, topk_overlap, topk_sets)

STAB = BACKEND_DATA / "v2" / "extensions" / "segment_stability_v2.csv"


def test_national_ranks_are_a_permutation_with_stable_ties():
    r = national_ranks(np.array([0.5, 2.0, 2.0, 0.1]))
    assert list(r) == [3, 1, 2, 4]


def test_block_weights_constant_within_block():
    rng = np.random.default_rng(1)
    blocks = np.repeat(np.arange(20), 7)
    w = block_bootstrap_weights(blocks, rng)
    assert all(len(set(w[blocks == b])) == 1 for b in range(20))
    assert w.sum() == pytest.approx(len(blocks))                 # equal-sized blocks: total preserved


def test_overlap_matrix_equals_set_version():
    rng = np.random.default_rng(2)
    R = np.vstack([national_ranks(rng.normal(size=500)) for _ in range(6)])
    prod = national_ranks(rng.normal(size=500))
    for k in (10, 50, 200):
        pair, withprod = topk_overlap(R, k, prod)
        assert pair == pytest.approx(mean_pairwise_overlap(topk_sets(R, k), k))
        ps = set(np.flatnonzero(prod <= k))
        assert withprod == pytest.approx(np.mean([len(s & ps) / k for s in topk_sets(R, k)]))


def test_identical_replicates_are_perfectly_stable():
    p = np.random.default_rng(3).gamma(1, 1, 300)
    R = np.vstack([national_ranks(p)] * 4)
    assert topk_overlap(R, 30, national_ranks(p)) == (1.0, 1.0)
    assert membership_frequency(R, 30).max() == 1.0
    assert order_preserved(R, national_ranks(p), 1, 100) == 1.0


@pytest.mark.skipif(not STAB.exists(), reason="run ml/experiments/ranking_stability.py first")
def test_stability_export_matches_backend_population():
    s = pd.read_csv(STAB)
    v2 = pd.read_csv(BACKEND_DATA / "v2" / "road_segments_ranked_v2.csv", usecols=["segment_id", "rank"])
    assert s.segment_id.is_unique and set(s.segment_id) == set(v2.segment_id)
    m = s.merge(v2, on="segment_id", suffixes=("", "_v2"))
    assert (m["rank"] == m.rank_v2).all()                       # production ranks carried, not recomputed
    for c in [c for c in s.columns if c.startswith("freq_")]:
        assert s[c].between(0, 1).all()
    assert (s.rank_p05 <= s.rank_p95).all()


def test_production_artefacts_unchanged():
    """Phase 2 must not alter any v1/v2 production file (manifest recorded before phase 2)."""
    man = REPORTS / "phase2_artifact_manifest.json"
    if not man.exists():
        pytest.skip("no manifest")
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "audit"))
    from artifact_manifest import current
    base = json.loads(man.read_text())["files"]
    now = current()
    changed = [k for k in base if k not in now or now[k]["sha256"] != base[k]["sha256"]]
    assert not changed, changed


def test_tiebreak_by_segment_id_matches_production_rule():
    from blackspot.stability import segment_id_order
    pred = np.array([1.0, 2.0, 1.0, 1.0])
    ids = np.array(["c", "z", "a", "b"])
    r = national_ranks(pred, segment_id_order(ids))
    # production: sort by score desc, then segment_id asc -> z, a, b, c
    assert list(r) == [4, 1, 2, 3]
