"""Segmentation from road centrelines: strokes, cutting, stable IDs, CRS-metric lengths."""
import numpy as np
import pandas as pd
import pytest

from blackspot.network import segment_network


def _net(rows):
    """rows: (id, class, number, name, start_node, end_node, [(x,y),...])"""
    links = pd.DataFrame([{
        "identifier": r[0], "class": r[1], "roadNumber": r[2], "name1": r[3], "formOfWay": "Single Carriageway",
        "length": 0, "primary": "false", "trunkRoad": "false", "startNode": r[4], "endNode": r[5],
        "structure": "", "function": "x"} for r in rows])
    cls = {"A Road": "A", "B Road": "B", "Unclassified": "U"}
    links["cls"] = links["class"].map(cls)
    verts = np.concatenate([np.asarray(r[6], float) for r in rows])
    off = np.r_[0, np.cumsum([len(r[6]) for r in rows])].astype(np.int64)
    return links, verts, off


ROWS = [
    # A1: three collinear links 0 -> 1200 m, side road joins at x=300
    ("L1", "A Road", "A1", "", "n00", "n01", [(0, 0), (300, 0)]),
    ("L2", "A Road", "A1", "", "n01", "n02", [(300, 0), (700, 0)]),
    ("L3", "A Road", "A1", "", "n03", "n02", [(1200, 0), (700, 0)]),       # drawn backwards
    ("L4", "Unclassified", "", "Side St", "n01", "n04", [(300, 0), (300, 200)]),
    # another "A1" 100 km away, not connected: must be a separate stroke
    ("L5", "A Road", "A1", "", "n10", "n11", [(100000, 0), (100400, 0)]),
    # B2 with a branch at (500, 1000): three strokes
    ("L6", "B Road", "B2", "", "n20", "n21", [(0, 1000), (500, 1000)]),
    ("L7", "B Road", "B2", "", "n21", "n22", [(500, 1000), (1000, 1000)]),
    ("L8", "B Road", "B2", "", "n21", "n23", [(500, 1000), (500, 1500)]),
]


@pytest.fixture
def seg():
    return segment_network(*_net(ROWS))[0]


def test_same_key_links_merge_through_degree2_nodes(seg):
    a1 = seg[(seg.route_key == "A1") & (seg.mid_e < 50000)]
    # one 1200 m stroke -> 2 pieces of 600 m, even though a side road joins it
    assert len(a1) == 2 and a1.stroke.nunique() == 1
    assert a1.length_m.tolist() == pytest.approx([600, 600])


def test_disconnected_same_number_is_separate(seg):
    a1 = seg[seg.route_key == "A1"]
    assert a1.stroke.nunique() == 2
    assert sorted(a1.run.unique()) == [0, 1]


def test_branch_breaks_stroke(seg):
    assert seg[seg.route_key == "B2"].stroke.nunique() == 3


def test_lengths_conserved_and_bounded(seg):
    tot = {"A1": 1200 + 400, "B2": 1500, "U:SIDE ST": 200}
    for k, v in tot.items():
        assert seg[seg.route_key == k].length_m.sum() == pytest.approx(v)
    long = seg[seg.n_pieces > 1]
    assert long.length_m.between(333, 750).all()


def test_junction_counted_once(seg):
    a1 = seg[(seg.route_key == "A1") & (seg.mid_e < 50000)].sort_values("piece")
    assert a1.n_junctions.tolist() == [1, 0]           # node at x=300 has degree 3


def test_ids_stable_under_row_shuffle():
    links, verts, off = _net(ROWS)
    a = segment_network(links, verts, off)[0]
    rng = np.random.default_rng(0)
    perm = rng.permutation(len(ROWS))
    b = segment_network(*_net([ROWS[i] for i in perm]))[0]
    cols = ["segment_id", "from_m", "to_m", "mid_e", "mid_n"]
    pd.testing.assert_frame_equal(a[cols].sort_values("segment_id").reset_index(drop=True),
                                  b[cols].sort_values("segment_id").reset_index(drop=True))


def test_segment_geometry_continuous():
    seg, verts, off = segment_network(*_net(ROWS))
    a1 = seg[(seg.route_key == "A1") & (seg.mid_e < 50000)].sort_values("piece")
    g0 = verts[off[a1.index[0]]:off[a1.index[0] + 1]]
    g1 = verts[off[a1.index[1]]:off[a1.index[1] + 1]]
    assert np.allclose(g0[-1], g1[0])                  # pieces share their boundary point
    assert np.hypot(*np.diff(g0, axis=0).T).sum() == pytest.approx(600)
