"""Historical-window strategies: no future years, correct COVID handling, correct weights."""
import numpy as np
import pandas as pd
import pytest

from blackspot.features import Window, assigned_collisions, build_frame, road_features
from blackspot.windows import (COVID_YEARS, History, frame, history_features_w, strategies,
                               training_target_ends)
from test_leakage import world  # noqa: F401  (fixture)


@pytest.mark.parametrize("h", [History("recent", 2), History("recent", 3), History("recent", 5), History("all"),
                               History("recent_nocovid", 3), History("all_nocovid"),
                               History("decay", half_life=2.0)])
@pytest.mark.parametrize("k", [2019, 2021, 2023, 2025])
def test_history_never_after_cutoff(h, k):
    yw = h.years_weights(k)
    assert max(yw) <= k and min(yw) >= 2015


def test_nocovid_rules_drop_only_2020_2021():
    assert History("recent_nocovid", 3).years_weights(2021) == {2017: 1, 2018: 1, 2019: 1}
    assert History("recent_nocovid", 3).years_weights(2023) == {2019: 1, 2022: 1, 2023: 1}
    assert History("recent_nocovid", 3).years_weights(2019) == History("recent", 3).years_weights(2019)
    allnc = History("all_nocovid").years_weights(2023)
    assert set(History("all").years_weights(2023)) - set(allnc) == set(COVID_YEARS)


def test_decay_weights():
    w = History("decay", half_life=2.0).years_weights(2021)
    assert w[2021] == 1.0 and w[2019] == pytest.approx(0.5) and w[2017] == pytest.approx(0.25)
    ys = sorted(w)
    assert all(w[a] < w[b] for a, b in zip(ys, ys[1:]))      # strictly more weight on recent years


def test_pair_rules():
    h3 = History("recent", 3)
    assert training_target_ends("single", 2021, h3) == [2021]
    assert training_target_ends("stacked", 2021, h3) == [2019, 2020, 2021]   # features from 2015 earliest
    assert training_target_ends("noncovid", 2021, h3) == [2019]               # 2020-21 targets excluded
    assert training_target_ends("noncovid", 2025, h3) == [2025]
    for e in training_target_ends("stacked_noncovid", 2025, h3):
        assert not {e - 1, e} & set(COVID_YEARS)
    assert training_target_ends("single", 2019, History("recent", 5)) == []   # 2014 not available


def test_reference_reproduces_v2_exactly(world):  # noqa: F811
    seg, coll, assign = world
    ac = assigned_collisions(coll, assign)
    road = road_features(seg)
    a = build_frame(seg, ac, Window(2019, 2021), Window(2022, 2023), road)
    b = frame(seg, ac, road, History("recent", 3), 2021, [2022, 2023])
    pd.testing.assert_frame_equal(a[b.columns], b)


def test_rescaled_window_matches_reference_scale(world):  # noqa: F811
    # uniform 6-year window rescaled to 3-yr equivalent: a constant yearly rate gives the same value
    seg, coll, assign = world
    c2 = pd.concat([coll.assign(collision_year=y, collision_index=coll.collision_index + f"_{y}")
                    for y in range(2016, 2022)], ignore_index=True)
    a2 = pd.concat([assign.assign(collision_index=assign.collision_index + f"_{y}") for y in range(2016, 2022)])
    ac = assigned_collisions(c2, a2)
    h3 = history_features_w(ac, seg, {2019: 1, 2020: 1, 2021: 1})
    h6 = history_features_w(ac, seg, {y: 1.0 for y in range(2016, 2022)})
    np.testing.assert_allclose(h6.h_n_coll.values, h3.h_n_coll.values)
    np.testing.assert_allclose(h6.h_adj_ksi_cas.values, h3.h_adj_ksi_cas.values, rtol=1e-6)


def test_frame_rejects_future_years(world):  # noqa: F811
    seg, coll, assign = world
    ac = assigned_collisions(coll, assign)
    with pytest.raises(AssertionError):
        frame(seg, ac, road_features(seg), History("recent", 3), 2021, [2021, 2022])


def test_features_unchanged_by_target_period_collisions(world):  # noqa: F811
    seg, coll, assign = world
    road = road_features(seg)
    for s in strategies():
        X1 = frame(seg, assigned_collisions(coll, assign), road, s.history, 2021, [2022, 2023])
        c2 = coll.copy()
        c2.loc[c2.collision_year >= 2022, "adj_ksi_cas"] = 99.0
        X2 = frame(seg, assigned_collisions(c2, assign), road, s.history, 2021, [2022, 2023])
        feats = [c for c in X1.columns if not c.startswith("y_")]
        pd.testing.assert_frame_equal(X1[feats], X2[feats], obj=s.name)


def test_covid_exclusion_changes_only_covid_records(world):  # noqa: F811
    seg, coll, assign = world
    road = road_features(seg)
    h = History("recent_nocovid", 3)
    X1 = frame(seg, assigned_collisions(coll, assign), road, h, 2021, None)
    c2 = coll.copy()
    c2.loc[c2.collision_year.isin(COVID_YEARS), "adj_ksi_cas"] = 50.0   # perturb only 2020-21
    X2 = frame(seg, assigned_collisions(c2, assign), road, h, 2021, None)
    pd.testing.assert_frame_equal(X1, X2)
