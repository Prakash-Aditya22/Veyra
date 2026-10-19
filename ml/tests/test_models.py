"""Count-model correctness on synthetic data with known parameters."""
import numpy as np
import pandas as pd
import pytest
from scipy.optimize import check_grad

from blackspot.models import (CountGLM, Design, EmpiricalBayes, _nb2_negloglik, eb_forecast,
                              overdispersion_test, scaled_history)


def _nb_data(n=40_000, alpha=0.8, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 2))
    mu = np.exp(-0.5 + 0.7 * X[:, 0] - 0.4 * X[:, 1])
    lam = rng.gamma(1 / alpha, alpha * mu)                 # gamma-Poisson mixture = NB2
    return X, rng.poisson(lam).astype(float), mu


def test_nb2_gradient_matches_finite_differences():
    X, y, _ = _nb_data(500)
    X1 = np.column_stack([np.ones(len(X)), X])
    p = np.array([-0.3, 0.5, -0.2, np.log(0.6)])
    err = check_grad(lambda q: _nb2_negloglik(q, X1, y)[0], lambda q: _nb2_negloglik(q, X1, y)[1], p)
    assert err < 1e-3 * np.abs(_nb2_negloglik(p, X1, y)[1]).max()


def test_nb2_recovers_coefficients_and_alpha():
    X, y, _ = _nb_data()
    m = CountGLM("nb2", l2=0).fit(X, y)
    assert m.coef_ == pytest.approx([-0.5, 0.7, -0.4], abs=0.05)
    assert m.alpha == pytest.approx(0.8, abs=0.08)


def test_poisson_glm_matches_mean():
    X, y, _ = _nb_data()
    m = CountGLM("poisson", l2=0).fit(X, y)
    assert m.predict(X).sum() == pytest.approx(y.sum(), rel=1e-3)   # canonical link: totals match


def test_overdispersion_detected():
    X, y, mu = _nb_data()
    t = overdispersion_test(y, mu)
    assert t["alpha_ct"] == pytest.approx(0.8, abs=0.1) and t["t"] > 5


def test_eb_weights_and_shrinkage():
    rng = np.random.default_rng(3)
    n = 30_000
    X = pd.DataFrame({"log_length": np.log(rng.uniform(300, 700, n)), "cls_A": rng.integers(0, 2, n)})
    mu = np.exp(-1 + X.log_length - 6.2 + 0.8 * X.cls_A)
    lam = rng.gamma(2.0, mu / 2.0)
    x = rng.poisson(lam).astype(float)
    eb = EmpiricalBayes(spf_cols=["log_length", "cls_A"]).fit_spf(X, x)
    m, prior, w = eb.posterior(X, x)
    assert np.all((w > 0) & (w < 1))
    lo, hi = np.minimum(prior, x), np.maximum(prior, x)
    assert np.all((m >= lo - 1e-9) & (m <= hi + 1e-9))          # posterior between prior and observed
    # EB beats raw counts at estimating the true rate (regression to the mean)
    assert np.mean((m - lam) ** 2) < np.mean((x - lam) ** 2)


def test_eb_forecast_scale_uses_training_pair_only():
    rng = np.random.default_rng(4)
    n = 5000
    X = pd.DataFrame({"log_length": np.log(rng.uniform(300, 700, n)), "cls_A": rng.integers(0, 2, n)})
    for c in ["cls_M", "cls_B", "cls_C", "cls_U", "fw_collapsed_dual", "fw_dual", "fw_roundabout",
              "fw_slip", "share_roundabout", "n_junctions", "junctions_per_km", "primary_route",
              "trunk_road", "net_km_1km", "net_km_3km"]:
        X[c] = 0.0
    lam = np.exp(-7.5 + X.log_length + 0.8 * X.cls_A)
    x_tr, y_tr, x_te = rng.poisson(3 * lam), rng.poisson(2 * lam), rng.poisson(3 * lam)
    out = eb_forecast(X, x_tr.astype(float), y_tr.astype(float), X, x_te.astype(float))
    assert out["k"] == pytest.approx(2 / 3, rel=0.15)           # 2-year target / 3-year history
    assert out["forecast"].sum() == pytest.approx(2 * lam.sum(), rel=0.15)


def test_design_fitted_on_train_only():
    tr = pd.DataFrame({"a": [1.0, 2.0, np.nan], "b": [0.0, 0.0, 0.0]})
    te = pd.DataFrame({"a": [100.0, np.nan, 3.0], "b": [5.0, 5.0, 5.0]})
    d = Design(["a", "b"]).fit(tr)
    Z = d.transform(te)
    assert Z.shape == (3, 3)                                   # a, b, a__missing
    assert d.med["a"] == 1.5                                   # imputed from training rows


def test_scaled_history():
    assert scaled_history(np.array([3.0, 0]), np.array([2.0, 0]), np.array([6.0])) == pytest.approx([4.0])
