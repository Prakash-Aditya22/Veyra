"""Count models for expected future KSI per segment.

All models are fitted on a fold's TRAINING pair (history c-4..c-2 -> target
c-1..c) and applied to the TEST pair (history c-2..c). Preprocessing
(imputation medians, scaling) is fitted on the training rows only.

MODELS
  scaled_history  baseline: history count x (sum train target / sum train history)
  poisson_glm     log-link Poisson regression, log(length) as a covariate
  nb_glm          NB2 regression (Var = mu + alpha mu^2), alpha by maximum likelihood
  eb              Empirical Bayes (Hauer 1997; AASHTO HSM 2010, Part B):
                    SPF  : NB2 regression of the history-window count on road
                           characteristics only (no crash history), fitted on the
                           history window being shrunk
                    EB   : m = w*mu + (1-w)*x,  w = 1 / (1 + alpha*mu)
                    then forecast = m * k, where k = sum(train target) /
                    sum(train EB) carries the history->target change in window
                    length and national trend, estimated on the training pair.
                    Excess = m - mu: expected KSI above what similar roads have.
  lgbm            LightGBM with Poisson loss on history + road + context features

Exposure variants use log AADF (mean over the history window) as a covariate
and are fitted only on segments that have an AADF.
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd

from .config import SEED

log = logging.getLogger("blackspot.models")


# ------------------------------------------------------------------ design matrix
class Design:
    """Median-impute + missing flags + standardise, fitted on training rows only."""

    def __init__(self, cols, log1p_cols=()):
        self.cols, self.log1p_cols = list(cols), set(log1p_cols)

    def _raw(self, X):
        Z = X[self.cols].astype(float).copy()
        for c in self.log1p_cols & set(self.cols):
            Z[c] = np.log1p(Z[c].clip(lower=0))
        return Z

    def fit(self, X):
        Z = self._raw(X)
        self.med = Z.median()
        self.miss = [c for c in self.cols if Z[c].isna().any()]
        Z = self._fill(Z)
        self.mu, self.sd = Z.mean(), Z.std().replace(0, 1).fillna(1)
        self.names = list(Z.columns)
        return self

    def _fill(self, Z):
        for c in self.miss:
            Z[f"{c}__missing"] = Z[c].isna().astype(float)
        return Z.fillna(self.med)

    def transform(self, X):
        Z = self._fill(self._raw(X))
        for c in self.names:
            if c not in Z:
                Z[c] = 0.0
        return ((Z[self.names] - self.mu[self.names]) / self.sd[self.names]).values


# ------------------------------------------------------------------ NB2 / Poisson GLM
def _nb2_negloglik(params, X, y, alpha_fixed=None):
    from scipy.special import gammaln
    beta = params[:-1] if alpha_fixed is None else params
    la = params[-1] if alpha_fixed is None else np.log(alpha_fixed)
    a = np.exp(la)
    eta = np.clip(X @ beta, -30, 30)
    mu = np.exp(eta)
    r = 1.0 / a
    ll = (gammaln(y + r) - gammaln(r) - gammaln(y + 1) + r * np.log(r / (r + mu)) + y * np.log(mu / (r + mu)))
    # gradient
    dmu = (y - mu) / (1 + a * mu)
    g_beta = -(X.T @ dmu)
    if alpha_fixed is not None:
        return -ll.sum(), g_beta
    from scipy.special import digamma
    dl_dr = digamma(y + r) - digamma(r) + np.log(r / (r + mu)) + 1 - (r + y) / (r + mu)
    g_la = -(dl_dr * (-r)).sum()                      # dr/dlog(a) = -r
    return -ll.sum(), np.r_[g_beta, g_la]


class CountGLM:
    """Poisson or NB2 regression with a log link, fitted by L-BFGS.

    Implemented directly (rather than via statsmodels' IRLS) because the
    design has ~2 million rows; the likelihood and its gradient are standard
    (Cameron & Trivedi 2013, ch. 3). Real-valued y (adjusted KSI) is allowed.
    A small ridge penalty (l2) keeps rare indicator columns finite.
    """

    def __init__(self, family="poisson", l2=1e-4):
        self.family, self.l2 = family, l2

    def fit(self, X, y):
        from scipy.optimize import minimize
        X1 = np.column_stack([np.ones(len(X)), X])
        n = len(y)
        b0 = np.zeros(X1.shape[1]); b0[0] = np.log(max(y.mean(), 1e-6))

        def pois(b):
            eta = np.clip(X1 @ b, -30, 30); mu = np.exp(eta)
            f = (mu - y * eta).sum() / n + self.l2 * (b[1:] ** 2).sum()
            g = X1.T @ (mu - y) / n; g[1:] += 2 * self.l2 * b[1:]
            return f, g
        res = minimize(pois, b0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
        b = res.x
        self.alpha = 0.0
        if self.family == "nb2":
            def nb(p):
                f, g = _nb2_negloglik(p, X1, y)
                f = f / n + self.l2 * (p[1:-1] ** 2).sum()
                g = g / n; g[1:-1] += 2 * self.l2 * p[1:-1]
                return f, g
            res = minimize(nb, np.r_[b, np.log(0.5)], jac=True, method="L-BFGS-B",
                           options={"maxiter": 1000})
            b, self.alpha = res.x[:-1], float(np.exp(res.x[-1]))
        self.coef_, self.converged = b, bool(res.success)
        if not res.success:
            log.warning("%s GLM did not fully converge: %s", self.family, res.message)
        return self

    def predict(self, X):
        return np.exp(np.clip(np.column_stack([np.ones(len(X)), X]) @ self.coef_, -30, 30))


def overdispersion_test(y, mu) -> dict:
    """Cameron-Trivedi auxiliary regression: ((y-mu)^2 - y)/mu = alpha*mu + e."""
    z = ((y - mu) ** 2 - y) / np.clip(mu, 1e-9, None)
    a = float((mu * z).sum() / (mu * mu).sum())
    resid = z - a * mu
    se = float(np.sqrt((resid ** 2).sum() / (len(y) - 1) / (mu * mu).sum()))
    return {"alpha_ct": a, "se": se, "t": a / se if se > 0 else float("nan")}


# ------------------------------------------------------------------ EB
SPF_FEATURES = ["log_length", "cls_M", "cls_A", "cls_B", "cls_C", "cls_U",
                "fw_collapsed_dual", "fw_dual", "fw_roundabout", "fw_slip",
                "share_roundabout", "n_junctions", "junctions_per_km", "primary_route", "trunk_road",
                "net_km_1km", "net_km_3km"]


class EmpiricalBayes:
    """Hauer's EB with an NB2 safety performance function.

    `fit_spf` is called on the window whose observed counts are being shrunk;
    it uses road characteristics only, never crash history, so the SPF is the
    'similar roads' prior and x is the site's own record.
    """

    def __init__(self, spf_cols=SPF_FEATURES, exposure=False):
        self.cols = list(spf_cols) + (["log_aadf"] if exposure else [])

    def fit_spf(self, X, x):
        self.design = Design(self.cols, log1p_cols={"n_junctions", "net_km_1km", "net_km_3km"}).fit(X)
        self.glm = CountGLM("nb2").fit(self.design.transform(X), x)
        return self

    def posterior(self, X, x):
        mu = self.glm.predict(self.design.transform(X))
        w = 1.0 / (1.0 + self.glm.alpha * mu)
        m = w * mu + (1 - w) * x
        return m, mu, w


def eb_forecast(X_tr, x_tr, y_tr, X_te, x_te, exposure=False, spf_rows=None):
    """EB forecast for the test pair; scale k is estimated on the training pair.

    The test-window SPF is fitted on `spf_rows` of the test window (default all):
    its history counts only, never its target. Spatial CV passes the rows
    outside the held-out block so the prior comes from other regions.
    """
    eb_tr = EmpiricalBayes(exposure=exposure).fit_spf(X_tr, x_tr)
    m_tr, _, _ = eb_tr.posterior(X_tr, x_tr)
    k = float(y_tr.sum() / m_tr.sum())
    rows = np.ones(len(X_te), bool) if spf_rows is None else spf_rows
    eb_te = EmpiricalBayes(exposure=exposure).fit_spf(X_te[rows], x_te[rows])
    m_te, mu_te, w_te = eb_te.posterior(X_te, x_te)
    return {"forecast": m_te * k, "eb_history": m_te, "spf_history": mu_te, "weight": w_te,
            "excess_history": m_te - mu_te, "k": k, "alpha": eb_te.glm.alpha,
            "spf_coef": dict(zip(["intercept"] + eb_te.design.names, eb_te.glm.coef_.round(4)))}


# ------------------------------------------------------------------ LightGBM
LGBM_DEFAULT = dict(objective="poisson", n_estimators=400, learning_rate=0.05, num_leaves=63,
                    min_child_samples=200, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                    reg_lambda=1.0, verbose=-1, n_jobs=-1, random_state=SEED)


def fit_lgbm(X, y, params=None):
    from lightgbm import LGBMRegressor
    p = dict(LGBM_DEFAULT); p.update(params or {})
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*does not have valid feature names.*")
        return LGBMRegressor(**p).fit(X, y)


def scaled_history(h_tr, y_tr, h_te):
    k = y_tr.sum() / max(h_tr.sum(), 1e-9)
    return h_te * k
