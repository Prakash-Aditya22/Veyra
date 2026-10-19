"""Assign each collision to exactly one road segment.

RULE
  Candidates are all segments within SNAP_MAX_M (50 m) of the collision's
  British National Grid point. Each candidate gets
        cost = perpendicular distance + penalty(road coding mismatch)
  and the collision goes to the cheapest one; ties go to the lower segment
  index (deterministic). One collision -> at most one segment, so a crash on
  a boundary between two pieces is never counted twice.

  Penalties (metres) express how much we trust the police road coding over the
  plotted point:
    numbered crash (M / A(M) / A / B with a number)
        same number 0 | matches second_road number 10 | same class 25 | other 35
    C road crash      OS "Classified Unnumbered" 0 | Unclassified/Not Classified 10 | B 20 | other 35
    unclassified      OS Unclassified/Not Classified/Unknown 0 | C 10 | other 35
  So a crash coded "A23" lands on the A23 unless the A23 is more than 25 m
  further away than some other road, which signals a miscoded number.

The rule never reads severity or year: assignment of a collision depends only
on its location and road coding, so it is the same in every fold.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .config import INTERIM, SNAP_MAX_M

log = logging.getLogger("blackspot.snap")
ASSIGN_PARQUET = INTERIM / "collision_segment.parquet"
SUB_EDGE_M = 25.0
TILE_M = 100_000.0

NUM_PREFIX = {1: "M", 2: "A", 3: "A", 4: "B"}


def crash_number_key(cls, num) -> np.ndarray:
    """STATS19 class/number -> OS-style road number ('A1(M)', 'M25', 'A23', 'B1234') or ''."""
    cls = np.asarray(pd.to_numeric(pd.Series(cls), errors="coerce").fillna(-1), int)
    num = np.asarray(pd.to_numeric(pd.Series(num), errors="coerce").fillna(0), int)
    out = np.full(len(cls), "", dtype=object)
    for c, p in NUM_PREFIX.items():
        m = (cls == c) & (num > 0)
        out[m] = [f"{p}{n}(M)" if c == 2 else f"{p}{n}" for n in num[m]]
    return out


def _sub_edges(idx: np.ndarray, verts: np.ndarray, off: np.ndarray):
    """Polyline edges of segments `idx`, split to <= SUB_EDGE_M."""
    s, e = off[idx], off[idx + 1]
    n = e - s
    rel = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    V = verts[np.repeat(s, n) + rel]
    sid = np.repeat(idx, n)
    ok = sid[1:] == sid[:-1]
    a, b, sid = V[:-1][ok], V[1:][ok], sid[:-1][ok]
    L = np.hypot(*(b - a).T)
    k = np.maximum(1, np.ceil(L / SUB_EDGE_M)).astype(int)
    rep = np.repeat(np.arange(len(a)), k)
    j = np.arange(k.sum()) - np.repeat(np.cumsum(k) - k, k)
    t0, t1 = (j / k[rep])[:, None], ((j + 1) / k[rep])[:, None]
    d = (b - a)[rep]
    return a[rep] + t0 * d, a[rep] + t1 * d, sid[rep]


def _point_seg_dist(p, a, b):
    ab = b - a
    L2 = (ab ** 2).sum(1)
    t = np.where(L2 > 0, ((p - a) * ab).sum(1) / np.where(L2 > 0, L2, 1), 0.0).clip(0, 1)
    q = a + t[:, None] * ab
    return np.hypot(*(p - q).T)


def penalties(c_cls, c_key, c_key2, s_cls, s_num):
    """Vectorised penalty for (crash, segment) candidate pairs; also returns match type."""
    numbered = c_key != ""
    same_num = numbered & (s_num == c_key)
    second = (c_key2 != "") & (s_num == c_key2)
    cls_map = {1: {"M"}, 2: {"M", "A"}, 3: {"A"}, 4: {"B"}}
    same_cls = np.zeros(len(c_cls), bool)
    for c, ok in cls_map.items():
        same_cls |= (c_cls == c) & np.isin(s_cls, list(ok))
    pen = np.full(len(c_cls), 35.0)
    typ = np.full(len(c_cls), "fallback", dtype=object)
    # numbered crashes
    m = numbered & same_cls; pen[m] = 25; typ[m] = "class"
    m = second; pen[m] = np.minimum(pen[m], 10); typ[m] = "second_number"
    m = same_num; pen[m] = 0; typ[m] = "number"
    # C road crashes (and numbered-class crashes with no number)
    c5 = (~numbered) & (c_cls == 5)
    for s_set, p in [({"B"}, 20), ({"U", "N"}, 10), ({"C"}, 0)]:
        m = c5 & np.isin(s_cls, list(s_set)); pen[m] = p; typ[m] = "class" if p == 0 else "near_class"
    # unclassified / unknown-number crashes
    c6 = (~numbered) & ~(c_cls == 5)
    for s_set, p in [({"C"}, 10), ({"U", "N", "X"}, 0)]:
        m = c6 & np.isin(s_cls, list(s_set)); pen[m] = p; typ[m] = "class" if p == 0 else "near_class"
    m = (~numbered) & np.isin(c_cls, [1, 2, 3, 4]) & same_cls
    pen[m] = np.minimum(pen[m], 15); typ[m] = np.where(pen[m] == 15, "class", typ[m])
    return pen, typ


def snap(coll: pd.DataFrame, seg: pd.DataFrame, verts: np.ndarray, off: np.ndarray,
         max_d: float = SNAP_MAX_M) -> pd.DataFrame:
    """Return one row per collision: seg_idx (-1 if unassigned), distance, match type."""
    n = len(coll)
    res = pd.DataFrame({"collision_index": coll.collision_index.values, "seg_idx": -1,
                        "snap_distance_m": np.nan, "match_type": "none",
                        "unassigned_reason": ""})
    E, N = coll.easting.values.astype(float), coll.northing.values.astype(float)
    has = np.isfinite(E) & np.isfinite(N)
    res.loc[~has, "unassigned_reason"] = "no_coordinates"
    c_cls = pd.to_numeric(coll.first_road_class, errors="coerce").fillna(-1).astype(int).values
    c_key = crash_number_key(coll.first_road_class, coll.first_road_number)
    c_key2 = crash_number_key(coll.second_road_class, coll.second_road_number)
    s_cls = seg.road_class.fillna("X").values.astype(object)
    s_num = seg.road_number.fillna("").str.upper().values.astype(object)

    tx = np.floor(np.where(has, E, 0) / TILE_M); ty = np.floor(np.where(has, N, 0) / TILE_M)
    buf = max_d + SUB_EDGE_M
    for (i, j), rows in pd.Series(np.arange(n)[has]).groupby([tx[has], ty[has]]):
        rows = rows.values
        x0, y0 = i * TILE_M - buf, j * TILE_M - buf
        x1, y1 = (i + 1) * TILE_M + buf, (j + 1) * TILE_M + buf
        cand = np.flatnonzero((seg.max_e.values >= x0) & (seg.min_e.values <= x1) &
                              (seg.max_n.values >= y0) & (seg.min_n.values <= y1))
        if not len(cand):
            continue
        a, b, sid = _sub_edges(cand, verts, off)
        tree = cKDTree((a + b) / 2)
        pts = np.column_stack([E[rows], N[rows]])
        hits = tree.query_ball_point(pts, r=max_d + SUB_EDGE_M / 2)
        lens = np.fromiter((len(h) for h in hits), int, len(hits))
        if lens.sum() == 0:
            continue
        q = np.repeat(np.arange(len(rows)), lens)
        e = np.concatenate([np.asarray(h, int) for h in hits if len(h)])
        d = _point_seg_dist(pts[q], a[e], b[e])
        pr = pd.DataFrame({"q": q, "s": sid[e], "d": d})
        pr = pr[pr.d <= max_d].groupby(["q", "s"], sort=False).d.min().reset_index()
        if pr.empty:
            continue
        r = rows[pr.q.values]
        pen, typ = penalties(c_cls[r], c_key[r], c_key2[r], s_cls[pr.s.values], s_num[pr.s.values])
        pr["cost"] = pr.d.values + pen
        pr["typ"] = typ
        best = pr.sort_values(["q", "cost", "s"]).drop_duplicates("q")
        rr = rows[best.q.values]
        res.loc[rr, "seg_idx"] = best.s.values
        res.loc[rr, "snap_distance_m"] = best.d.values
        res.loc[rr, "match_type"] = best.typ.values
    res.loc[has & (res.seg_idx < 0), "unassigned_reason"] = f"no_road_within_{int(max_d)}m"
    res["segment_id"] = np.where(res.seg_idx >= 0, seg.segment_id.values[res.seg_idx.clip(lower=0)], None)
    return res
