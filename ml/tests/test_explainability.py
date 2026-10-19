"""Explanations reference the production feature set, add up, and leak no targets."""
import json

import numpy as np
import pandas as pd
import pytest

from blackspot.config import BACKEND_DATA, OUTPUTS
from blackspot.explain import (FEATURES, assert_no_target_columns, check_additivity, contributions,
                               group_contributions, top_contributions)
from blackspot.features import CONTEXT_FEATURES, COUNT_COLS, ROAD_FEATURES

VERIF = OUTPUTS / "explainability" / "production_model_verification.json"
EXPORT = BACKEND_DATA / "v2" / "extensions" / "segment_explanations_v2.csv"
EXPORT_JSON = BACKEND_DATA / "v2" / "extensions" / "segment_explanations_top5000_v2.json"


@pytest.fixture(scope="module")
def tiny_model():
    from lightgbm import LGBMRegressor
    rng = np.random.default_rng(0)
    X = rng.normal(size=(3000, 4)).astype(np.float32)
    mu = np.exp(0.3 + 0.8 * X[:, 0] - 0.5 * X[:, 1] + 0.2 * X[:, 0] * X[:, 2])
    y = rng.poisson(mu)
    m = LGBMRegressor(objective="poisson", n_estimators=60, num_leaves=8, verbose=-1, random_state=0).fit(X, y)
    return m, X


def test_treeshap_adds_up_to_log_prediction(tiny_model):
    m, X = tiny_model
    C = contributions(m.booster_, X, batch=1000)
    assert C.shape == (len(X), X.shape[1] + 1)
    assert check_additivity(C, m.predict(X)) < 1e-4


def test_lightgbm_contrib_matches_shap_library(tiny_model):
    import shap
    m, X = tiny_model
    C = contributions(m.booster_, X[:200])
    sv = np.asarray(shap.TreeExplainer(m.booster_).shap_values(X[:200]))
    assert np.max(np.abs(sv - C[:, :-1])) < 1e-4


def test_top_contributions_sorted_and_factor_is_exp(tiny_model):
    m, X = tiny_model
    C = contributions(m.booster_, X)
    cols = ["h_n_coll", "log_length", "n_junctions", "net_km_3km"]
    t = top_contributions(C, cols, X, np.array([0, 5]), k=3)
    assert len(t) == 6
    for _, g in t.groupby("row"):
        assert g.shap_log.abs().is_monotonic_decreasing
    np.testing.assert_allclose(t.factor, np.exp(t.shap_log), rtol=1e-6)
    gc = group_contributions(C, cols)
    np.testing.assert_allclose(gc[["shap_history", "shap_road", "shap_context", "base"]].sum(axis=1),
                               C.sum(axis=1), rtol=1e-5, atol=1e-5)


def test_every_production_feature_has_a_label():
    hist = [f"h_{c}" for c in COUNT_COLS] + ["h_last_n_coll", "h_last_adj_ksi_cas", "h_years_with_crash",
                                             "h_share_junction", "h_share_dark", "h_share_urban", "h_share_wet",
                                             "h_speed_median", "h_share_single_vehicle", "h_ksi_share",
                                             "h_adj_ksi_per_km", "h_coll_per_km"]
    for f in hist + ROAD_FEATURES + CONTEXT_FEATURES:
        assert f in FEATURES, f


def test_target_guard():
    with pytest.raises(AssertionError):
        assert_no_target_columns(["h_n_coll", "y_adj_ksi_cas"])
    with pytest.raises(AssertionError):
        assert_no_target_columns(["blackspot_score"])
    assert_no_target_columns(["h_n_coll", "log_length"])


@pytest.mark.skipif(not VERIF.exists(), reason="run ml/experiments/explain_blackspot.py first")
def test_explained_model_is_the_production_model():
    v = json.loads(VERIF.read_text())
    assert v["verification"]["max_abs_diff"] < 1e-6           # reproduces stored blackspot_score
    assert len(v["features"]) == v["n_features"] == 45
    assert not any(c.startswith(("y_", "mid_e", "mid_n", "log_aadf")) for c in v["features"])
    spec = json.loads((OUTPUTS / "frozen_spec.json").read_text())
    assert v["frozen_spec_sha256"] == spec["sha256"]
    from lightgbm import Booster
    b = Booster(model_file=str(OUTPUTS / "explainability" / "production_lgbm.txt"))
    assert b.feature_name() == [f"Column_{i}" for i in range(45)] or b.feature_name() == v["features"]
    assert b.num_feature() == 45


@pytest.mark.skipif(not EXPORT.exists(), reason="run ml/experiments/explain_blackspot.py first")
def test_explanation_exports_have_no_targets_and_valid_ids():
    e = pd.read_csv(EXPORT)
    assert_no_target_columns(e.feature.unique())
    v = json.loads(VERIF.read_text())
    assert set(e.feature) <= set(v["features"])
    ids = set(pd.read_csv(BACKEND_DATA / "v2" / "road_segments_ranked_v2.csv", usecols=["segment_id"]).segment_id)
    assert set(e.segment_id) == ids
    js = json.loads(EXPORT_JSON.read_text())
    assert len(js["segments"]) == 5000 and set(js["segments"]) <= ids


def test_display_values_are_human_readable():
    from blackspot.explain import display_value
    assert display_value("log_length", np.log(512.0)) == "512 m"
    assert display_value("fw_single", 0.0) == "no" and display_value("cls_A", 1.0) == "yes"
    assert display_value("h_share_dark", 0.25) == "25%"
    assert display_value("h_speed_median", 30.0) == "30 mph"
    assert display_value("h_n_coll", 32.0) == "32"
    assert display_value("h_speed_median", float("nan")) == "no data"
