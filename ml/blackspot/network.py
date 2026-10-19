"""Road centreline network (OS Open Roads) -> stable ~500 m road segments.

WHY A REAL NETWORK
  v1 traced each road from its own crash points, so segment boundaries,
  stretch labels and chainage moved whenever a crash was added, including
  crashes from the period being predicted, and road with no recorded crash
  did not exist at all. Segments here come from OS Open Roads, Ordnance
  Survey's open national centreline (OGL v3), and never look at a crash.

METHOD
  1. Route key per link: the road number for numbered roads (M25, A23,
     A1(M), B1234); otherwise "<class>:<name>" ("C:Mill Lane", "U:" when
     unnamed). Links sharing a number in different parts of the country stay
     apart because they never share a node.
  2. Strokes: links of the same key are chained through every node where
     exactly two links of that key meet. A stroke therefore runs between real
     junctions of the route (branches, carriageway splits, roundabouts, ends);
     side roads joining it do not break it, because they carry another key.
  3. Each stroke is cut into round(L / 500 m) equal pieces (at least one),
     so segment lengths fall between about 333 m and 750 m. Strokes shorter
     than 250 m stay as one short segment. Length is kept as a model offset.
  4. IDs are deterministic. A stroke is walked from the end node with the
     smaller OS node identifier (a cycle starts at its smallest link
     identifier), and the segment ID is "<class/number>-<first link id, 12 hex>-<piece>".
     The same network release always gives the same IDs.

  OS Open Roads draws most dual carriageways as one collapsed centreline
  ("Collapsed Dual Carriageway"). The minority drawn as two carriageways are
  segmented per carriageway and flagged `form_of_way == "Dual Carriageway"`.

All coordinates are British National Grid (EPSG:27700) metres; the shapefiles
ship in EPSG:27700 (checked from the .prj in `load_links`).
"""
from __future__ import annotations

import io
import logging
import struct
import zipfile

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .config import INTERIM, RAW, SEGMENT_TARGET_M
from .io_utils import atomic_path, write_parquet

log = logging.getLogger("blackspot.network")

OS_ZIP = RAW / "os_open_roads" / "oproad_essh_gb.zip"
LINKS_PARQUET = INTERIM / "road_links.parquet"
LINK_VERTS_NPZ = INTERIM / "road_link_vertices.npz"
SEGMENTS_PARQUET = INTERIM / "segments.parquet"
SEG_VERTS_NPZ = INTERIM / "segment_vertices.npz"

CLASS_CODE = {"Motorway": "M", "A Road": "A", "B Road": "B", "Classified Unnumbered": "C",
              "Unclassified": "U", "Not Classified": "N", "Unknown": "X"}
LINK_FIELDS = ["identifier", "class", "roadNumber", "name1", "formOfWay", "length", "primary",
               "trunkRoad", "startNode", "endNode", "structure", "function"]


# ------------------------------------------------------------------ reading
def _read_dbf(raw: bytes, fields: list[str]) -> pd.DataFrame:
    """Fixed-width dBASE records -> DataFrame, via one numpy structured view."""
    n_rec = struct.unpack("<I", raw[4:8])[0]
    hdr_len, rec_len = struct.unpack("<HH", raw[8:12])
    names, sizes, pos = [], [], 32
    while raw[pos] != 0x0D:
        names.append(raw[pos:pos + 11].split(b"\x00")[0].decode("ascii"))
        sizes.append(raw[pos + 16])
        pos += 32
    dt = np.dtype([("_del", "S1")] + [(n, f"S{s}") for n, s in zip(names, sizes)])
    assert dt.itemsize == rec_len, "unexpected dbf layout"
    arr = np.frombuffer(raw, dtype=dt, count=n_rec, offset=hdr_len)
    out = {}
    for f in fields:
        s = pd.Series(arr[f]).str.decode("utf-8", errors="replace").str.strip()
        out[f] = s
    return pd.DataFrame(out)


def _read_shp_lines(shp: bytes, shx: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Single-part polylines -> (vertices (P,2) float64, offsets (N+1,))."""
    n = (len(shx) - 100) // 8
    idx = np.frombuffer(shx, dtype=">i4", count=2 * n, offset=100).reshape(n, 2)
    starts = idx[:, 0].astype(np.int64) * 2 + 8                 # content start (bytes)
    b = np.frombuffer(shp, dtype=np.uint8)
    take = lambda off: b[off[:, None] + np.arange(4)].copy().view("<i4").ravel()  # noqa: E731
    shape_type = take(starts)
    if not np.all(np.isin(shape_type, [3, 13, 23])):        # PolyLine / PolyLineZ / PolyLineM
        raise ValueError("expected PolyLine records only")      # XY block has the same layout in all three
    n_parts = take(starts + 36)
    if not np.all(n_parts == 1):
        raise ValueError("multi-part link geometry found; this reader assumes single part")
    n_pts = take(starts + 40).astype(np.int64)
    offsets = np.zeros(n + 1, np.int64)
    np.cumsum(n_pts, out=offsets[1:])
    verts = np.empty((offsets[-1], 2))
    for i, s in enumerate(starts + 48):
        k = n_pts[i]
        verts[offsets[i]:offsets[i] + k] = np.frombuffer(shp, "<f8", count=2 * k, offset=int(s)).reshape(k, 2)
    return verts, offsets


def load_links(zip_path=OS_ZIP) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """All RoadLink records of every tile; duplicates across tiles removed."""
    if not zip_path.exists():
        raise FileNotFoundError(f"{zip_path} missing -- run ml/blackspot/download.py os_open_roads")
    frames, verts, offs, base = [], [], [], 0
    with zipfile.ZipFile(zip_path) as z:
        tiles = sorted({m.split("/")[-1].split("_")[0] for m in z.namelist() if m.endswith("_RoadLink.shp")})
        prj = z.read(f"data/{tiles[0]}_RoadLink.prj").decode("ascii", "replace")
        if "British_National_Grid" not in prj and "OSGB" not in prj:
            raise ValueError(f"unexpected CRS in OS Open Roads: {prj[:120]}")
        for t in tiles:
            d = _read_dbf(z.read(f"data/{t}_RoadLink.dbf"), LINK_FIELDS)
            v, o = _read_shp_lines(z.read(f"data/{t}_RoadLink.shp"), z.read(f"data/{t}_RoadLink.shx"))
            if len(d) != len(o) - 1:
                raise ValueError(f"{t}: dbf/shp record count mismatch")
            d["tile"] = t
            frames.append(d); verts.append(v); offs.append(o[:-1] + base); base += len(v)
            log.info("tile %s: %d links", t, len(d))
    links = pd.concat(frames, ignore_index=True)
    verts = np.concatenate(verts)
    starts = np.concatenate(offs)
    ends = np.r_[starts[1:], len(verts)]
    first = ~links.identifier.duplicated()
    log.info("%d links, %d duplicated across tiles dropped", len(links), int((~first).sum()))
    keep = np.flatnonzero(first.values)
    links = links.iloc[keep].reset_index(drop=True)
    # re-pack vertices for kept links
    lens = ends[keep] - starts[keep]
    new_off = np.zeros(len(keep) + 1, np.int64); np.cumsum(lens, out=new_off[1:])
    gather = np.repeat(starts[keep] - new_off[:-1], lens) + np.arange(new_off[-1])
    verts = verts[gather]
    links["length"] = pd.to_numeric(links.length, errors="coerce")
    links["cls"] = links["class"].map(CLASS_CODE).fillna("X")
    return links, verts, new_off


# ------------------------------------------------------------------ strokes
def route_keys(links: pd.DataFrame) -> pd.Series:
    num = links.roadNumber.str.upper().str.replace(" ", "", regex=False)
    named = links.cls + ":" + links.name1.str.upper()
    return pd.Series(np.where(num != "", num, named), index=links.index)


def build_strokes(links: pd.DataFrame) -> np.ndarray:
    """Label each link with its stroke (chain of same-key links through degree-2 nodes)."""
    n = len(links)
    key = pd.factorize(links.route_key)[0]
    ends = pd.DataFrame({"link": np.r_[np.arange(n), np.arange(n)],
                         "key": np.r_[key, key],
                         "node": np.r_[links.sn.values, links.en.values]})
    deg = ends.groupby(["key", "node"]).link.transform("size")
    two = ends[deg == 2].sort_values(["key", "node", "link"])
    a = two.link.values[0::2]; b = two.link.values[1::2]
    ok = a != b                                                    # a loop link pairs with itself
    g = coo_matrix((np.ones(ok.sum()), (a[ok], b[ok])), shape=(n, n))
    _, label = connected_components(g, directed=False)
    return label


def order_strokes(links: pd.DataFrame, stroke: np.ndarray, node_rank: np.ndarray):
    """Deterministic link order and orientation within each stroke.

    Returns (ordered link indices, reversed flags, stroke boundaries).
    """
    n = len(links)
    sn, en = links.sn.values, links.en.values
    lid_rank = pd.factorize(links.identifier, sort=True)[0].astype(np.int64)
    srt = np.lexsort((lid_rank, stroke))
    bnd = np.flatnonzero(np.r_[True, stroke[srt][1:] != stroke[srt][:-1], True])
    out_link = np.empty(n, np.int64); out_rev = np.zeros(n, bool)
    pos = 0
    for k in range(len(bnd) - 1):
        members = srt[bnd[k]:bnd[k + 1]]
        if len(members) == 1:
            i = members[0]
            out_link[pos] = i
            out_rev[pos] = node_rank[en[i]] < node_rank[sn[i]]   # start from smaller node id
            pos += 1
            continue
        inc: dict[int, list[int]] = {}
        for i in members:
            inc.setdefault(sn[i], []).append(i); inc.setdefault(en[i], []).append(i)
        term = [v for v, l in inc.items() if len(l) == 1]
        if term:
            node = min(term, key=lambda v: node_rank[v])
        else:                                                      # cycle
            i0 = members[0]                                        # smallest identifier
            node = sn[i0]
        used = set()
        for _ in range(len(members)):
            cand = [i for i in inc[node] if i not in used]
            if not cand:
                break
            i = min(cand, key=lambda j: lid_rank[j])
            used.add(i)
            rev = sn[i] != node
            out_link[pos] = i; out_rev[pos] = rev; pos += 1
            node = sn[i] if rev else en[i]
        if len(used) != len(members):
            raise RuntimeError(f"stroke {stroke[members[0]]} is not a simple path or cycle")
    return out_link, out_rev, bnd


# ------------------------------------------------------------------ cutting
def _interp(xy: np.ndarray, cum: np.ndarray, m: float) -> np.ndarray:
    j = int(np.clip(np.searchsorted(cum, m, side="right") - 1, 0, len(cum) - 2))
    seg = cum[j + 1] - cum[j]
    t = 0.0 if seg <= 0 else (m - cum[j]) / seg
    return xy[j] + t * (xy[j + 1] - xy[j])


def cut_strokes(links, verts, voff, order, rev, bnd, node_deg_start, node_deg_end,
                target=SEGMENT_TARGET_M):
    """Cut each ordered stroke polyline into equal ~target-length pieces.

    node_deg_start / node_deg_end: overall degree (all roads) of the start and
    end node of each ordered link; nodes with degree >= 3 are junctions and are
    counted once, in the piece whose measure range contains them.
    """
    seg_rows, seg_verts, seg_off = [], [], [0]
    link_seg_rows = []
    lid = links.identifier.values
    for k in range(len(bnd) - 1):
        sl = slice(bnd[k], bnd[k + 1])
        L_idx, R = order[sl], rev[sl]
        parts, link_bounds = [], [0.0]
        for i, r in zip(L_idx, R):
            p = verts[voff[i]:voff[i + 1]]
            p = p[::-1] if r else p
            parts.append(p if not parts else p[1:])
            link_bounds.append(link_bounds[-1] + float(np.hypot(*np.diff(p, axis=0).T).sum()))
        xy = np.concatenate(parts)
        cum = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
        L = cum[-1]
        npieces = max(1, int(np.floor(L / target + 0.5)))
        cuts = np.linspace(0.0, L, npieces + 1)
        lb = np.asarray(link_bounds)
        # junction nodes: stroke start node plus every link end node
        node_m = lb
        node_deg = np.r_[node_deg_start[bnd[k]], node_deg_end[sl]]
        jpiece = np.clip(np.searchsorted(cuts, node_m[node_deg >= 3], side="right") - 1, 0, npieces - 1)
        njunc = np.bincount(jpiece, minlength=npieces)
        first = lid[L_idx[0]]
        for p in range(npieces):
            a, b = cuts[p], cuts[p + 1]
            inner = np.flatnonzero((cum > a) & (cum < b))
            pts = np.vstack([_interp(xy, cum, a), xy[inner], _interp(xy, cum, b)])
            seg_verts.append(pts); seg_off.append(seg_off[-1] + len(pts))
            mid = _interp(xy, cum, (a + b) / 2)
            seg_rows.append((k, first, p, npieces, a, b, b - a, mid[0], mid[1],
                             pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max(),
                             int(njunc[p])))
        # which links fall in which piece, by measure overlap
        p_lo = np.clip(np.searchsorted(cuts, lb[:-1], side="right") - 1, 0, npieces - 1)
        p_hi = np.clip(np.searchsorted(cuts, lb[1:], side="left") - 1, 0, npieces - 1)
        for j, i in enumerate(L_idx):
            for p in range(p_lo[j], max(p_hi[j], p_lo[j]) + 1):
                ov = min(lb[j + 1], cuts[p + 1]) - max(lb[j], cuts[p])
                link_seg_rows.append((k, p, i, ov))
    seg = pd.DataFrame(seg_rows, columns=["stroke", "first_link", "piece", "n_pieces", "from_m", "to_m",
                                          "length_m", "mid_e", "mid_n", "min_e", "min_n", "max_e", "max_n",
                                          "n_junctions"])
    ls = pd.DataFrame(link_seg_rows, columns=["stroke", "piece", "link", "overlap_m"])
    return seg, np.concatenate(seg_verts), np.asarray(seg_off, np.int64), ls


# ------------------------------------------------------------------ build
def build_segments(write: bool = True):
    links, verts, voff = load_links()
    seg, sverts, soff = segment_network(links, verts, voff)
    if write:
        write_parquet(seg, SEGMENTS_PARQUET)
        with atomic_path(SEG_VERTS_NPZ) as tmp:
            with open(tmp, "wb") as fh:
                np.savez_compressed(fh, verts=sverts.astype(np.float64), offsets=soff)
        lk = links[["identifier", "cls", "roadNumber", "name1", "formOfWay", "length", "tile"]].assign(
            route_key=route_keys(links))
        write_parquet(lk, LINKS_PARQUET)
    return seg, sverts, soff


def segment_network(links: pd.DataFrame, verts: np.ndarray, voff: np.ndarray):
    """Pure function: link table + vertices -> segments. Never sees a crash."""
    links = links.reset_index(drop=True).copy()
    links["route_key"] = route_keys(links)
    nodes = pd.Index(sorted(set(links.startNode) | set(links.endNode)))
    links["sn"] = nodes.get_indexer(links.startNode)
    links["en"] = nodes.get_indexer(links.endNode)
    node_rank = np.arange(len(nodes))                    # nodes sorted by identifier string
    overall_deg = np.bincount(np.r_[links.sn.values, links.en.values], minlength=len(nodes))

    stroke = build_strokes(links)
    # relabel strokes by their smallest link identifier so processing order (and
    # the internal `stroke` number) does not depend on input row order
    first_id = pd.Series(links.identifier.values).groupby(stroke).transform("min")
    stroke = pd.factorize(first_id.values, sort=True)[0]
    order, rev, bnd = order_strokes(links, stroke, node_rank)
    log.info("%d links -> %d strokes", len(links), len(bnd) - 1)
    sn_o = np.where(rev, links.en.values[order], links.sn.values[order])   # traversal start node
    en_o = np.where(rev, links.sn.values[order], links.en.values[order])
    seg, sverts, soff, ls = cut_strokes(links, verts, voff, order, rev, bnd,
                                        overall_deg[sn_o], overall_deg[en_o])
    log.info("%d segments", len(seg))

    # attributes from the links each segment covers (length-weighted majority)
    ls = ls[ls.overlap_m > 0]
    la = links[["cls", "route_key", "roadNumber", "name1", "formOfWay", "primary", "trunkRoad",
                "structure", "function"]].iloc[ls.link.values].reset_index(drop=True)
    ls = pd.concat([ls.reset_index(drop=True), la], axis=1)
    ls["seg_key"] = ls.stroke.astype(np.int64) * 10_000 + ls.piece
    seg["seg_key"] = seg.stroke.astype(np.int64) * 10_000 + seg.piece

    def major(col):
        t = ls.groupby(["seg_key", col]).overlap_m.sum().reset_index()
        return t.sort_values(["seg_key", "overlap_m"], ascending=[True, False]).drop_duplicates("seg_key") \
                .set_index("seg_key")[col]
    for col, new in [("cls", "road_class"), ("route_key", "route_key"), ("roadNumber", "road_number"),
                     ("name1", "road_name"), ("formOfWay", "form_of_way"), ("function", "road_function")]:
        seg[new] = seg.seg_key.map(major(col))
    for col, new in [("primary", "primary_route"), ("trunkRoad", "trunk_road")]:
        seg[new] = seg.seg_key.map((ls.assign(v=(ls[col] == "true") * ls.overlap_m)
                                    .groupby("seg_key").v.sum() > 0)).astype(bool)
    seg["share_roundabout"] = seg.seg_key.map(
        ls.assign(v=(ls.formOfWay == "Roundabout") * ls.overlap_m).groupby("seg_key").v.sum()) / seg.length_m
    seg["share_slip"] = seg.seg_key.map(
        ls.assign(v=(ls.formOfWay == "Slip Road") * ls.overlap_m).groupby("seg_key").v.sum()) / seg.length_m
    seg["tunnel"] = seg.seg_key.map((ls.structure != "").groupby(ls.seg_key).any()).fillna(False)
    seg["n_links"] = seg.seg_key.map(ls.groupby("seg_key").link.nunique())

    # identifiers
    lbl = np.where(seg.road_number.fillna("") != "", seg.road_number.fillna(""), seg.road_class)
    hexid = seg.first_link.str.replace("-", "", regex=False).str[:12]
    seg["segment_id"] = lbl + "-" + hexid + "-" + seg.piece.map("{:02d}".format)
    if seg.segment_id.duplicated().any():
        raise RuntimeError("segment_id collision")
    # stroke ordinal within route key, for drawing a road in order (not a model feature)
    sk = seg.drop_duplicates("stroke")[["stroke", "route_key", "first_link"]].sort_values(["route_key", "first_link"])
    sk["run"] = sk.groupby("route_key").cumcount()
    seg["run"] = seg.stroke.map(sk.set_index("stroke").run)
    seg = seg.drop(columns=["seg_key"])
    return seg, sverts, soff


def load_segments() -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    if not SEGMENTS_PARQUET.exists():
        raise FileNotFoundError(f"{SEGMENTS_PARQUET} missing -- run: python ml/pipeline.py network")
    seg = pd.read_parquet(SEGMENTS_PARQUET)
    z = np.load(SEG_VERTS_NPZ)
    return seg, z["verts"], z["offsets"]
