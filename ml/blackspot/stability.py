"""Ranking stability under refitting (phase 4).

What the spread measures: how much the ranking moves when the model is
refitted on a resampled training set (spatial-block bootstrap: whole 50 km
blocks drawn with replacement) or with a different random seed. That is
estimation variability of the ranking. It is NOT a calibrated predictive
interval for future casualties, which would also need outcome (Poisson /
NB) noise and model misspecification.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def national_ranks(pred: np.ndarray, tiebreak: np.ndarray | None = None) -> np.ndarray:
    """1 = highest prediction. Ties broken by `tiebreak` ascending (the production file breaks
    them by segment_id; pass `segment_id_order(...)`), else by position."""
    order = np.argsort(-pred, kind="stable") if tiebreak is None else np.lexsort((tiebreak, -pred))
    r = np.empty(len(pred), np.int32)
    r[order] = np.arange(1, len(pred) + 1)
    return r


def segment_id_order(segment_ids) -> np.ndarray:
    """Position of each segment_id in ascending string order (the production tie-break)."""
    ids = np.asarray(segment_ids).astype(str)
    key = np.empty(len(ids), np.int64)
    key[np.argsort(ids, kind="stable")] = np.arange(len(ids))
    return key


def block_bootstrap_weights(blocks: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Per-row weight = how many times the row's spatial block was drawn (blocks resampled with replacement)."""
    uniq, inv = np.unique(blocks, return_inverse=True)
    cnt = np.bincount(rng.integers(0, len(uniq), len(uniq)), minlength=len(uniq))
    return cnt[inv].astype(np.float64)


def topk_sets(ranks: np.ndarray, k: int) -> list[set]:
    """ranks: (replicates, segments) -> list of sets of segment positions with rank <= k."""
    return [set(np.flatnonzero(r <= k)) for r in ranks]


def mean_pairwise_overlap(sets: list[set], k: int) -> float:
    """Mean |A & B| / k over all replicate pairs."""
    n = len(sets)
    if n < 2:
        return float("nan")
    tot, m = 0.0, 0
    for i in range(n):
        for j in range(i + 1, n):
            tot += len(sets[i] & sets[j]) / k
            m += 1
    return tot / m


def topk_overlap(ranks: np.ndarray, k: int, prod_rank: np.ndarray | None = None) -> tuple[float, float]:
    """(mean pairwise top-k overlap between replicates, mean overlap with production top-k).

    Uses a boolean membership matrix, so memory is replicates x segments bits, not sets.
    """
    M = (ranks <= k).astype(np.float32)
    G = M @ M.T / k
    n = len(M)
    pair = float(G[np.triu_indices(n, 1)].mean()) if n > 1 else float("nan")
    prod = float((M[:, prod_rank <= k].sum(axis=1) / k).mean()) if prod_rank is not None else float("nan")
    return pair, prod


def membership_frequency(ranks: np.ndarray, k: int) -> np.ndarray:
    """Share of replicates in which each segment is in the top k."""
    return (ranks <= k).mean(axis=0)


def rank_summary(ranks: np.ndarray, rows: np.ndarray) -> pd.DataFrame:
    r = ranks[:, rows]
    return pd.DataFrame({"rank_median": np.median(r, axis=0), "rank_p05": np.percentile(r, 5, axis=0),
                         "rank_p95": np.percentile(r, 95, axis=0),
                         "rank_iqr": np.percentile(r, 75, axis=0) - np.percentile(r, 25, axis=0)})


def order_preserved(ranks: np.ndarray, prod_rank: np.ndarray, gap: int, upto: int) -> float:
    """For production ranks r and r+gap (r < upto), share of replicates keeping the same order."""
    pos = np.argsort(prod_rank)                       # positions sorted by production rank
    a, b = pos[: upto - gap], pos[gap:upto]
    return float((ranks[:, a] < ranks[:, b]).mean())


def stability_class(freq_top1000: np.ndarray, freq_top5pct: np.ndarray) -> np.ndarray:
    return np.select([freq_top1000 >= 0.9, freq_top1000 >= 0.5, freq_top5pct >= 0.9],
                     ["robust top-1000", "borderline top-1000", "robust top-5%"], "variable")
