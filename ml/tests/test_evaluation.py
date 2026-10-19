"""Capture metrics, tie handling and clustered bootstrap."""
import numpy as np
import pytest

from blackspot.evaluation import (calibration_table, capture_at, capture_bounds_with_ties,
                                  cluster_bootstrap, count_metrics, poisson_deviance)


def test_capture_without_ties():
    score = np.array([5, 4, 3, 2, 1, 0, 0, 0, 0, 0], float)
    y = np.array([3, 1, 0, 0, 0, 0, 0, 0, 1, 5], float)
    assert capture_at(score, y, 0.2) == pytest.approx(40.0)     # top 2 rows hold 4 of 10


def test_ties_expected_is_pro_rata():
    score = np.array([2, 1, 1, 1, 1], float)    # top 40% = row 0 + one of four tied rows
    y = np.array([1, 4, 0, 0, 0], float)
    worst, best, exp = capture_bounds_with_ties(score, y, 0.4)
    assert worst == pytest.approx(20.0)
    assert best == pytest.approx(100.0)
    assert exp == pytest.approx(20.0 + 80.0 / 4)


def test_ties_do_not_depend_on_row_order():
    rng = np.random.default_rng(0)
    score = rng.integers(0, 4, 500).astype(float)
    y = rng.poisson(score)
    p = rng.permutation(500)
    assert capture_at(score, y, 0.2) == pytest.approx(capture_at(score[p], y[p], 0.2))


def test_poisson_deviance_zero_for_perfect():
    y = np.array([0, 1, 2, 5], float)
    assert poisson_deviance(y, y) == pytest.approx(0.0, abs=1e-6)
    assert poisson_deviance(y, np.full(4, 2.0)) > 0


def test_count_metrics_null_model_explains_nothing():
    y = np.array([0, 1, 2, 5], float)
    m = count_metrics(y, np.full(4, y.mean()))
    assert m["deviance_explained"] == pytest.approx(0.0, abs=1e-9)
    assert m["sum_pred_over_obs"] == pytest.approx(1.0)


def test_calibration_table_totals():
    rng = np.random.default_rng(1)
    mu = rng.gamma(1, 1, 1000); y = rng.poisson(mu)
    t = calibration_table(y, mu)
    assert t.n.sum() == 1000 and t.obs_sum.sum() == y.sum()


def test_cluster_bootstrap_resamples_whole_groups():
    groups = np.repeat(np.arange(10), 5)
    seen = []
    def stat(idx):
        g = groups[idx]
        # every sampled group must appear with all 5 of its members
        _, counts = np.unique(g, return_counts=True)
        seen.append(np.all(counts % 5 == 0))
        return len(idx)
    out = cluster_bootstrap(groups, stat, n_boot=20)
    assert all(seen) and np.all(out == 50)


def test_weighted_ranker_matches_unweighted_ties():
    from blackspot.evaluation import WeightedRanker
    rng = np.random.default_rng(5)
    score = rng.integers(0, 5, 3000).astype(float)
    y = rng.poisson(score / 2 + 0.1)
    r = WeightedRanker(score)
    for f in (0.01, 0.05, 0.1, 0.2):
        assert r.capture(y, np.ones(3000), f) == pytest.approx(capture_bounds_with_ties(score, y, f)[2])


def test_weighted_ranker_duplicate_weights_equal_repeated_rows():
    from blackspot.evaluation import WeightedRanker
    rng = np.random.default_rng(6)
    score = rng.normal(size=500); y = rng.poisson(1, 500).astype(float)
    w = rng.integers(0, 3, 500).astype(float)
    rep = np.repeat(np.arange(500), w.astype(int))
    assert WeightedRanker(score).capture(y, w, 0.2) == pytest.approx(
        capture_bounds_with_ties(score[rep], y[rep], 0.2)[2], abs=0.5)


def test_length_capture_cuts_on_km():
    from blackspot.evaluation import WeightedRanker
    score = np.array([3.0, 2.0, 1.0, 0.0])
    y = np.array([1.0, 1.0, 1.0, 1.0])
    length = np.array([100.0, 100.0, 100.0, 700.0])          # 1000 m total
    r = WeightedRanker(score)
    assert r.capture(y, np.ones(4), 0.2, size=length) == pytest.approx(50.0)   # top 200 m = 2 rows
    assert r.capture(y, np.ones(4), 0.25, size=length) == pytest.approx(62.5)  # half of row 3 pro rata


def test_fast_bootstrap_paths_match_reference():
    from blackspot.evaluation import WeightedRanker, block_weights, weighted_deviance
    rng = np.random.default_rng(8)
    n = 4000
    score = rng.integers(0, 6, n).astype(float); y = rng.poisson(score / 3 + 0.05).astype(float)
    mu = score / 3 + 0.1; blocks = rng.integers(0, 40, n)
    r = WeightedRanker(score).prepare(y)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(y > 0, y * np.log(y / mu), 0.0)
    dev_i = 2 * (t - (y - mu))
    for w in block_weights(blocks, 5, seed=1):
        assert r.capture_fast(w, 0.1) == pytest.approx(r.capture(y, w, 0.1))
        assert np.dot(w, dev_i) / w.sum() == pytest.approx(weighted_deviance(y, mu, w))
