"""Rebuild every segment from the OS Open Roads zip, with the links in a shuffled
order, and compare with the saved build.

    .venv/Scripts/python ml/audit/network_determinism.py      (~15 min, ~5 GB RAM)

Writes ml/reports/network_determinism.json. Identical segment IDs, measures and
attributes across independent runs, despite a different input order, is the
evidence that IDs are stable for a given network release.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot import network  # noqa: E402
from blackspot.config import REPORTS  # noqa: E402
from blackspot.io_utils import setup_logging, write_json  # noqa: E402


def shuffle_links(links, verts, voff, seed=123):
    """Permute link rows and rebuild the flat vertex array to match."""
    perm = np.random.default_rng(seed).permutation(len(links))
    lens = (voff[1:] - voff[:-1])[perm]
    new_off = np.zeros(len(perm) + 1, np.int64); np.cumsum(lens, out=new_off[1:])
    rel = np.arange(new_off[-1]) - np.repeat(new_off[:-1], lens)
    src = np.repeat(voff[:-1][perm], lens) + rel
    return links.iloc[perm].reset_index(drop=True), verts[src], new_off


def main():
    setup_logging()
    saved, _, _ = network.load_segments()
    links, verts, voff = network.load_links()
    seg, _, _ = network.segment_network(*shuffle_links(links, verts, voff))
    cols = ["segment_id", "from_m", "to_m", "mid_e", "mid_n", "length_m", "road_class", "n_junctions"]
    a = saved[cols].sort_values("segment_id").reset_index(drop=True)
    b = seg[cols].sort_values("segment_id").reset_index(drop=True)
    same_ids = len(a) == len(b) and bool((a.segment_id.values == b.segment_id.values).all())
    num = ["from_m", "to_m", "mid_e", "mid_n", "length_m"]
    max_diff = float(np.abs(a[num].values - b[num].values).max()) if same_ids else None
    out = {"saved_segments": int(len(a)), "rebuilt_segments": int(len(b)), "identical_ids": same_ids,
           "max_abs_measure_diff_m": max_diff,
           "identical": bool(same_ids and max_diff < 1e-6
                             and (a.road_class.values == b.road_class.values).all()
                             and (a.n_junctions.values == b.n_junctions.values).all()),
           "input_link_order": "shuffled (seed 123) before rebuilding"}
    write_json(out, REPORTS / "network_determinism.json")
    print(out)


if __name__ == "__main__":
    main()
