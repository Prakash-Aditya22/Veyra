"""Temporal leakage guards: windows, feature isolation, frozen-spec enforcement."""
import numpy as np
import pandas as pd
import pytest

from blackspot.features import (DEV_CUTOFFS, HOLDOUT_CUTOFF, POSTHOC_CUTOFFS, Fold, Window,
                                assigned_collisions, build_frame, road_features)
from blackspot.network import segment_network
from test_network import ROWS, _net


@pytest.mark.parametrize("c", list(DEV_CUTOFFS) + [HOLDOUT_CUTOFF] + list(POSTHOC_CUTOFFS))
def test_fold_windows_are_prospective(c):
    f = Fold(c)
    assert f.train_x.end < f.train_y.start          # train features precede train target
    assert f.train_y.end == c                         # training target is known at the cutoff
    assert f.test_x.end == c < f.test_y.start         # test features end at cutoff, target after
    assert len(f.train_x.years) == len(f.test_x.years) == 3
    assert len(f.train_y.years) == len(f.test_y.years) == 2


def test_dev_folds_never_touch_holdout_years():
    hold = set(Fold(HOLDOUT_CUTOFF).test_y.years)
    for c in DEV_CUTOFFS:
        f = Fold(c)
        used = set(f.train_x.years) | set(f.train_y.years) | set(f.test_x.years) | set(f.test_y.years)
        assert not used & hold


@pytest.fixture(scope="module")
def world():
    seg, _, _ = segment_network(*_net(ROWS))
    rng = np.random.default_rng(0)
    n = 400
    coll = pd.DataFrame({
        "collision_index": [f"c{i}" for i in range(n)],
        "collision_year": rng.integers(2015, 2026, n),
        "adj_ksi_cas": rng.uniform(0, 1.5, n), "n_ksi_cas": rng.integers(0, 2, n),
        "n_fatal_cas": 0, "n_cas": rng.integers(1, 3, n), "is_ksi_collision": rng.integers(0, 2, n),
        "junction_detail": rng.choice([0, 13, 16], n), "road_type": rng.choice([1, 6], n),
        "light_conditions": rng.choice([1, 4], n),
        "urban_or_rural_area": rng.choice([1, 2], n), "road_surface_conditions": rng.choice([1, 2], n),
        "speed_limit": rng.choice([30, 60], n), "number_of_vehicles": rng.integers(1, 3, n),
        "collision_severity": rng.choice([1, 2, 3], n)})
    assign = pd.DataFrame({"collision_index": coll.collision_index,
                           "seg_idx": rng.integers(0, len(seg), n)})
    return seg, coll, assign


def test_features_ignore_collisions_outside_history(world):
    seg, coll, assign = world
    f = Fold(2021)
    road = road_features(seg)
    X1 = build_frame(seg, assigned_collisions(coll, assign), f.test_x, f.test_y, road)
    # wipe and inflate everything in the target years: features must not move
    c2 = coll.copy()
    fut = c2.collision_year.isin(f.test_y.years + [2024, 2025])
    c2.loc[fut, ["adj_ksi_cas", "n_ksi_cas", "is_ksi_collision"]] = [50.0, 9, 1]
    X2 = build_frame(seg, assigned_collisions(c2, assign), f.test_x, f.test_y, road)
    feats = [c for c in X1.columns if not c.startswith("y_")]
    pd.testing.assert_frame_equal(X1[feats], X2[feats])
    assert (X2.y_adj_ksi_cas.values >= X1.y_adj_ksi_cas.values).all()
    assert X2.y_adj_ksi_cas.sum() > X1.y_adj_ksi_cas.sum()


def test_target_equals_window_sum(world):
    seg, coll, assign = world
    f = Fold(2021)
    X = build_frame(seg, assigned_collisions(coll, assign), f.test_x, f.test_y, road_features(seg))
    m = coll.merge(assign, on="collision_index")
    want = m[m.collision_year.isin(f.test_y.years)].adj_ksi_cas.sum()
    assert X.y_adj_ksi_cas.sum() == pytest.approx(want)


def test_population_does_not_depend_on_outcomes(world):
    # every segment appears in every frame regardless of crash history
    seg, coll, assign = world
    road = road_features(seg)
    empty = assign.assign(seg_idx=-1)
    X = build_frame(seg, assigned_collisions(coll, empty), Window(2019, 2021), Window(2022, 2023), road)
    assert len(X) == len(seg) and X.h_n_coll.sum() == 0


def test_holdout_refuses_without_frozen_spec(tmp_path, monkeypatch):
    from blackspot import steps
    monkeypatch.setattr(steps, "_frozen_path", lambda: tmp_path / "missing.json")
    with pytest.raises(RuntimeError, match="no frozen spec"):
        steps._load_frozen()
