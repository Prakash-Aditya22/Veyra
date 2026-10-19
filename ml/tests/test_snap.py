"""Collision -> segment assignment."""
import numpy as np
import pandas as pd
import pytest

from blackspot.network import segment_network
from blackspot.snap import crash_number_key, snap
from test_network import ROWS, _net


@pytest.fixture(scope="module")
def net():
    return segment_network(*_net(ROWS))


def _crashes(rows):
    return pd.DataFrame(rows, columns=["collision_index", "easting", "northing", "first_road_class",
                                       "first_road_number", "second_road_class", "second_road_number"])


def _seg_of(res, seg, cid):
    i = res.set_index("collision_index").loc[cid, "seg_idx"]
    return None if i < 0 else seg.iloc[i]


def test_number_key_formats():
    k = crash_number_key([1, 2, 3, 4, 5, 6, 3], [25, 1, 23, 1234, 7, 0, 0])
    assert list(k) == ["M25", "A1(M)", "A23", "B1234", "", "", ""]


def test_basic_assignment(net):
    seg, v, o = net
    c = _crashes([("on_a1", 150, 10, 3, 1, -1, 0),
                  ("on_side", 300, 100, 6, 0, -1, 0),
                  ("far", 50_000, 50_000, 3, 1, -1, 0),
                  ("nocoord", np.nan, np.nan, 3, 1, -1, 0)])
    r = snap(c, seg, v, o)
    assert _seg_of(r, seg, "on_a1").route_key == "A1"
    assert _seg_of(r, seg, "on_side").route_key == "U:SIDE ST"
    rr = r.set_index("collision_index")
    assert rr.loc["far", "unassigned_reason"] == "no_road_within_50m"
    assert rr.loc["nocoord", "unassigned_reason"] == "no_coordinates"


def test_number_match_beats_nearer_other_road(net):
    seg, v, o = net
    # 10 m from the side street, 30 m from the A1, coded A1 -> A1 (30+0 < 10+35)
    r = snap(_crashes([("x", 310, 30, 3, 1, -1, 0)]), seg, v, o)
    assert _seg_of(r, seg, "x").route_key == "A1"
    assert r.match_type.iloc[0] == "number"


def test_boundary_crash_assigned_once_and_deterministically(net):
    seg, v, o = net
    c = _crashes([("b", 600, 0, 3, 1, -1, 0)])           # exactly on the A1 piece boundary
    r1 = snap(c, seg, v, o); r2 = snap(c, seg, v, o)
    assert len(r1) == 1 and r1.seg_idx.iloc[0] >= 0
    assert r1.seg_idx.iloc[0] == r2.seg_idx.iloc[0]


def test_assignment_independent_of_row_order(net):
    seg, v, o = net
    rng = np.random.default_rng(1)
    pts = rng.uniform([0, -40], [1200, 40], size=(200, 2))
    c = _crashes([(f"c{i}", x, y, 3, 1, -1, 0) for i, (x, y) in enumerate(pts)])
    a = snap(c, seg, v, o).set_index("collision_index").seg_idx
    b = snap(c.sample(frac=1, random_state=3), seg, v, o).set_index("collision_index").seg_idx
    pd.testing.assert_series_equal(a.sort_index(), b.sort_index())
    # every crash lands on one of the two A1 pieces, split at x = 600
    assigned = seg.iloc[a.loc[[f"c{i}" for i in range(200)]].values]
    assert (assigned.route_key == "A1").all()
    first = assigned.piece.values == 0
    assert np.all(pts[first, 0] <= 600 + 1e-6) and np.all(pts[~first, 0] >= 600 - 1e-6)


def test_coverage_buckets_partition_national_total():
    from blackspot.coverage import coverage_table, summarise
    seg = pd.DataFrame({"road_class": ["A", "X", "U"]})
    coll = pd.DataFrame({"collision_index": list("abcde"), "collision_year": [2024] * 5,
                         "first_road_class": [3, 6, 6, 3, 3], "adj_ksi_cas": [1.0, 2.0, 3.0, 4.0, 5.0]})
    assign = pd.DataFrame({"collision_index": list("abcde"), "seg_idx": [0, 1, 2, -1, -1],
                           "unassigned_reason": ["", "", "", "no_road_within_50m", "no_coordinates"]})
    d = coverage_table(coll, assign, seg, [2024])
    s = summarise(d)
    assert s["national_total"] == 15
    assert s["by_bucket"] == {"access_road": round(2 / 15, 4), "no_coords": round(5 / 15, 4),
                              "no_road": round(4 / 15, 4), "scored": round(4 / 15, 4)}
