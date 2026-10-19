"""Ranking and count-model metrics with explicit tie handling and clustered uncertainty.

Capture at k% answers: if the highest-scoring k% of segments in a population
were treated, what share of that population's future KSI would they contain?
The denominator is always the KSI total of the population passed in, so the
caller decides (and must report) which population that is.

Ties matter. A crash-count score is an integer and most segments sit on 0, 1
or 2, so the top-20% cut usually falls inside a block of thousands of tied
segments. Which of those is "in" is then decided by row order, which is
arbitrary. `capture_expected` gives the expectation under random tie-breaking
(the fair value); `capture_bounds_with_ties` gives the best and worst case.
"""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np

FRACS = (0.01, 0.05, 0.10, 0.20)


def _k(n: int, frac: float) -> int:
    return int(n * frac)


def capture_at(score, y, frac: float, ties: str = "expected") -> float:
    """Share (%) of sum(y) in the top `frac` of rows ranked by `score`.

    ties="expected": tied block at the cut contributes pro rata (fair value).
    ties="first":    v1 behaviour, np.argsort(-score) order (arbitrary).
    """
    score = np.asarray(score, float); y = np.asarray(y, float)
    tot = y.sum()
    if tot <= 0:
        return float("nan")
    k = _k(len(y), frac)
    if ties == "first":
        o = np.argsort(-score)
        return float(y[o[:k]].sum() / tot * 100)
    return capture_bounds_with_ties(score, y, frac)[2]


def capture_bounds_with_ties(score, y, frac: float) -> tuple[float, float, float]:
    """(worst, best, expected) capture % when the cut falls in a tied block."""
    score = np.asarray(score, float); y = np.asarray(y, float)
    n, tot = len(y), y.sum()
    k = _k(n, frac)
    if k == 0 or tot <= 0:
        return 0.0, 0.0, 0.0
    s_sorted = np.sort(score)[::-1]
    cut = s_sorted[k - 1]
    above = score > cut
    tied = score == cut
    a, m = int(above.sum()), int(tied.sum())
    take = k - a                                    # how many of the tied block are selected
    base = y[above].sum()
    yt = np.sort(y[tied])
    worst = base + yt[:take].sum()
    best = base + yt[::-1][:take].sum()
    expected = base + yt.sum() * take / m
    return (float(worst / tot * 100), float(best / tot * 100), float(expected / tot * 100))


def capture_curve(score, y, fracs: Sequence[float] = FRACS) -> dict[str, float]:
    return {f"top{int(round(f * 100))}": capture_at(score, y, f) for f in fracs}


def poisson_deviance(y, mu) -> float:
    """Mean Poisson deviance; 0 for a perfect forecast."""
    y = np.asarray(y, float); mu = np.clip(np.asarray(mu, float), 1e-9, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(y > 0, y * np.log(y / mu), 0.0)
    return float(2 * np.mean(t - (y - mu)))


def count_metrics(y, mu) -> dict[str, float]:
    y = np.asarray(y, float); mu = np.asarray(mu, float)
    null = np.full_like(y, y.mean())
    d, d0 = poisson_deviance(y, mu), poisson_deviance(y, null)
    return {"poisson_deviance": d,
            "deviance_explained": float(1 - d / d0) if d0 > 0 else float("nan"),
            "mae": float(np.mean(np.abs(y - mu))),
            "rmse": float(np.sqrt(np.mean((y - mu) ** 2))),
            "sum_pred_over_obs": float(mu.sum() / y.sum()) if y.sum() > 0 else float("nan")}


def calibration_table(y, mu, n_bins: int = 10):
    """Observed vs predicted totals by decile of prediction (ties kept together)."""
    import pandas as pd
    y = np.asarray(y, float); mu = np.asarray(mu, float)
    r = pd.Series(mu).rank(method="first")
    b = np.ceil(r / len(mu) * n_bins).clip(1, n_bins).astype(int)
    t = pd.DataFrame({"bin": b, "pred": mu, "obs": y}).groupby("bin").agg(
        n=("obs", "size"), pred_sum=("pred", "sum"), obs_sum=("obs", "sum"),
        pred_mean=("pred", "mean"), obs_mean=("obs", "mean")).reset_index()
    t["obs_over_pred"] = t.obs_sum / t.pred_sum.clip(lower=1e-9)
    return t


def cluster_bootstrap(groups, stat: Callable[[np.ndarray], float], n_boot: int = 500,
                      seed: int = 42) -> np.ndarray:
    """Bootstrap a statistic by resampling whole clusters (spatial blocks, roads).

    Neighbouring segments share traffic, policing and reporting, so treating
    them as independent observations understates uncertainty. `stat` receives
    an index array into the original rows (with repeats) and returns a number.
    """
    groups = np.asarray(groups)
    uniq, inv = np.unique(groups, return_inverse=True)
    order = np.argsort(inv, kind="stable")
    members = np.split(order, np.cumsum(np.bincount(inv, minlength=len(uniq)))[:-1])
    rng = np.random.default_rng(seed)
    out = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, len(uniq), len(uniq))
        idx = np.concatenate([members[p] for p in pick])
        out[b] = stat(idx)
    return out


def summarise_boot(samples: np.ndarray) -> dict[str, float]:
    s = samples[np.isfinite(samples)]
    return {"mean": float(s.mean()), "ci_low": float(np.percentile(s, 2.5)),
            "ci_high": float(np.percentile(s, 97.5)), "share_le_0": float((s <= 0).mean())}


class WeightedRanker:
    """Tie-aware capture under bootstrap weights, with one sort per score.

    Rows are sorted once by score (descending) and grouped into tie blocks. A
    bootstrap replicate is a weight per row (how many times its cluster was
    drawn); capture is then the weighted share of y in the top `frac` of total
    weight, with the tie block at the cut counted pro rata, which equals
    `capture_bounds_with_ties(...)[2]` when all weights are 1.
    """

    def __init__(self, score):
        score = np.asarray(score, float)
        self.order = np.argsort(-score, kind="stable")
        s = score[self.order]
        self.starts = np.flatnonzero(np.r_[True, s[1:] != s[:-1]])

    def prepare(self, y, size=None):
        """Pre-sort y (and size) once so each bootstrap replicate only gathers weights."""
        self._ys = np.asarray(y, float)[self.order]
        self._ss = None if size is None else np.asarray(size, float)[self.order]
        return self

    def capture_fast(self, w, frac, use_size=False):
        """Same result as capture(y, w, frac, size) for the prepared y/size."""
        w = np.asarray(w, float)[self.order]
        ws = w * self._ss if use_size else w
        W = np.add.reduceat(ws, self.starts); Y = np.add.reduceat(w * self._ys, self.starts)
        return self._finish(W, Y, frac, use_size)

    def _finish(self, W, Y, frac, sized):
        tot_w, tot_y = W.sum(), Y.sum()
        if tot_y <= 0:
            return float("nan")
        K = frac * tot_w if sized else np.floor(frac * tot_w)
        cw = np.cumsum(W)
        g = int(np.searchsorted(cw, K, side="left"))
        if g >= len(W):
            return 100.0
        before_w = cw[g] - W[g]; before_y = Y[:g].sum()
        part = (K - before_w) / W[g] if W[g] > 0 else 0.0
        return float((before_y + part * Y[g]) / tot_y * 100)

    def capture(self, y, w, frac, size=None):
        """`size` (e.g. segment length): cut at `frac` of total size instead of row count."""
        y = np.asarray(y, float)[self.order]; w = np.asarray(w, float)[self.order]
        ws = w if size is None else w * np.asarray(size, float)[self.order]
        W = np.add.reduceat(ws, self.starts); Y = np.add.reduceat(w * y, self.starts)
        tot_w, tot_y = W.sum(), Y.sum()
        if tot_y <= 0:
            return float("nan")
        K = np.floor(frac * tot_w) if size is None else frac * tot_w
        cw = np.cumsum(W)
        g = int(np.searchsorted(cw, K, side="left"))
        if g >= len(W):
            return 100.0
        before_w = cw[g] - W[g]; before_y = Y[:g].sum()
        part = (K - before_w) / W[g] if W[g] > 0 else 0.0
        return float((before_y + part * Y[g]) / tot_y * 100)


def block_weights(groups, n_boot, seed=42):
    """Yield per-row weights = number of times the row's cluster is drawn."""
    uniq, inv = np.unique(np.asarray(groups), return_inverse=True)
    rng = np.random.default_rng(seed)
    for _ in range(n_boot):
        cnt = np.bincount(rng.integers(0, len(uniq), len(uniq)), minlength=len(uniq))
        yield cnt[inv].astype(float)


def weighted_deviance(y, mu, w):
    y = np.asarray(y, float); mu = np.clip(np.asarray(mu, float), 1e-9, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(y > 0, y * np.log(y / mu), 0.0)
    return float(2 * np.sum(w * (t - (y - mu))) / np.sum(w))
