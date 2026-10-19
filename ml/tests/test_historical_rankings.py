"""Historical rankings (retrospective backtests): periods, leakage, separation of recorded and
predicted values, reuse of the production forecast, and confinement of outputs."""
import itertools
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
import historical_rankings as hr  # noqa: E402
from blackspot.config import OUTPUTS  # noqa: E402
from blackspot.evaluation import capture_at  # noqa: E402
from blackspot.experiment import make_context  # noqa: E402
from blackspot.features import COUNT_COLS, Fold, window_sums  # noqa: E402
from blackspot.stability import national_ranks, segment_id_order  # noqa: E402
from test_leakage import world  # noqa: F401,E402  (fixture)

SPEC = {"selected_model": "lgbm", "sha256": "test-spec",
        "lgbm_params": {"num_leaves": 4, "min_child_samples": 2, "n_estimators": 20}}
HAVE_RESULT = hr.RESULT.exists() and hr.META.exists()


def _ctx(world, mutate=None):
    seg, coll, assign = world
    coll = coll.copy()
    if mutate is not None:
        mutate(coll)
    return make_context(seg, coll, assign, with_aadf=False)


def _zeros(n):
    return pd.DataFrame(0.0, index=pd.RangeIndex(n), columns=COUNT_COLS)


# ------------------------------------------------------------------ periods
def test_period_arithmetic_and_valid_cutoffs():
    assert hr.EARLIEST_CUTOFF == 2019
    assert hr.BACKTEST_CUTOFFS == (2019, 2020, 2021, 2022, 2023)
    assert hr.CUTOFFS == (2019, 2020, 2021, 2022, 2023, 2025)
    p = hr.periods(2019)
    assert (p["train_feature_period"], p["train_target_period"], p["history_period"], p["forecast_period"]) == \
        ("2015-2017", "2018-2019", "2017-2019", "2020-2021")
    p = hr.periods(2023)
    assert (p["history_period"], p["forecast_period"], p["target_observed"]) == ("2021-2023", "2024-2025", True)
    p = hr.periods(2025)
    assert (p["ranking_kind"], p["train_target_period"], p["history_period"], p["forecast_period"],
            p["target_observed"]) == (hr.PRODUCTION, "2024-2025", "2023-2025", "2026-2027", False)
    for c in hr.BACKTEST_CUTOFFS:
        f = Fold(c)
        assert hr.ranking_kind(c) == hr.RETRO
        assert f.train_x.end < f.train_y.start and f.train_y.end == c       # no training target beyond the cutoff
        assert f.test_x.end == c < f.test_y.start and f.test_y.end <= 2025  # target complete in the data


@pytest.mark.parametrize("c,match", [(2015, "before 2019"), (2018, "before 2019"), (2024, "incomplete"),
                                     (2026, "after the production cutoff")])
def test_early_incomplete_and_future_cutoffs_are_refused(c, match):
    with pytest.raises(ValueError, match=match):
        hr.ranking_kind(c)
    with pytest.raises(ValueError):
        hr.periods(c)


def test_cutoff_2024_is_omitted_before_any_work():
    assert 2024 not in hr.CUTOFFS and set(hr.OMITTED) == {2024}
    assert "2025-2026" in hr.OMITTED[2024]
    with pytest.raises(ValueError, match="incomplete"):
        hr.main(["--cutoffs", "2024"])                  # refused before data or the frozen spec are loaded


def test_caveats_disclose_selection_holdout_and_network():
    net = "OS Open Roads 2026-04 (one snapshot for every period)"
    for c in hr.BACKTEST_CUTOFFS:
        t = hr.caveat(c, net)
        assert t.startswith("Retrospective backtest") and "targets up to 2023" in t and "2026-04" in t
    assert "one of the selection targets" in hr.caveat(2019, net) and "COVID" in hr.caveat(2019, net)
    assert "overlaps the already-examined 2024-2025 holdout" in hr.caveat(2022, net)
    assert "final holdout, already examined" in hr.caveat(2023, net)
    assert hr.caveat(2025, net).startswith("Production forecast") and "not yet observed" in hr.caveat(2025, net)


# ------------------------------------------------------------------ leakage
def test_future_data_does_not_change_an_earlier_cutoff(world):
    c = 2021

    def inflate_future(coll):
        fut = coll.collision_year > c
        coll.loc[fut, ["adj_ksi_cas", "n_ksi_cas", "is_ksi_collision"]] = [50.0, 9, 1]
        coll.loc[fut, ["speed_limit", "collision_severity"]] = [70, 1]

    a = hr.backtest_cutoff(_ctx(world), c, SPEC)
    b = hr.backtest_cutoff(_ctx(world, inflate_future), c, SPEC)
    feats = [k for k in a["Xte"].columns if not k.startswith("y_")]
    pd.testing.assert_frame_equal(a["Xte"][feats], b["Xte"][feats])
    np.testing.assert_array_equal(a["predictions"]["lgbm"], b["predictions"]["lgbm"])
    assert b["yte"].sum() > a["yte"].sum()               # only the recorded target moved


def test_training_pairs_end_at_the_cutoff(world):
    ctx = _ctx(world)
    for c in (2019, 2023):
        res = hr.backtest_cutoff(ctx, c, SPEC)
        f = res["fold"]
        assert f["train_target"] == f"{c - 1}-{c}" and f["test_features"] == f"{c - 2}-{c}"
        assert int(f["train_target"][-4:]) <= c and int(f["train_features"][-4:]) < c - 1


def test_backtests_never_use_the_production_model(world, monkeypatch, tmp_path):
    def refuse():
        raise AssertionError("production model loaded for a backtest")

    monkeypatch.setattr(hr, "load_production_model", refuse)
    monkeypatch.setattr(hr, "PRODUCTION_MODEL", tmp_path / "absent.txt")
    monkeypatch.setattr(hr, "PRODUCTION_SCORES", tmp_path / "absent.parquet")
    res = hr.backtest_cutoff(_ctx(world), 2019, SPEC)
    model = res["info"]["lgbm"]["_model"]                # fitted here, with the spec it was given
    assert model.n_estimators == SPEC["lgbm_params"]["n_estimators"]
    assert len(res["predictions"]["lgbm"]) == len(res["Xte"])
    with pytest.raises(ValueError):
        hr.backtest_cutoff(_ctx(world), hr.FORECAST_CUTOFF, SPEC)   # production is reused, never refitted here


# ------------------------------------------------------------------ ranks and separation
def test_tiebreak_matches_the_production_assembly():
    rng = np.random.default_rng(5)
    n = 400
    ids = np.array([f"S{i:04d}" for i in rng.permutation(n)])
    score = np.round(rng.gamma(0.5, 1, n), 1)
    score[:150] = 0.0                                    # a large tie, as in production
    o = pd.DataFrame({"segment_id": ids, "blackspot_score": score})
    o = o.sort_values(["blackspot_score", "segment_id"], ascending=[False, True])   # outputs.assemble
    want = pd.Series(np.arange(1, n + 1), index=o.index).sort_index().values
    tie = segment_id_order(ids)
    t = hr.ranking_table(2019, ids, tie, score, _zeros(n), score * 2, "x", "net")
    assert (t.column("predicted_rank").to_numpy() == want).all()


@pytest.mark.skipif(not hr.PRODUCTION_SCORES.exists(), reason="production forecast not present")
def test_tie_rule_reproduces_the_stored_production_ranks():
    s = pd.read_parquet(hr.PRODUCTION_SCORES, columns=["segment_id", "blackspot_score", "rank"])
    r = national_ranks(s.blackspot_score.values, segment_id_order(s.segment_id.values))
    assert (r == s["rank"].values).all()


def test_unobserved_target_stays_null_and_is_never_invented():
    n = 60
    ids = np.array([f"S{i:03d}" for i in range(n)])
    tie, pred = segment_id_order(ids), np.linspace(1, 0, n)
    t = hr.ranking_table(2025, ids, tie, pred, _zeros(n), None, "x", "net")
    assert t.column("observed_target_adj_ksi").null_count == n
    assert t.column("observed_target_rank").null_count == n
    with pytest.raises(ValueError):                      # no outcome may be attached to 2026-2027
        hr.ranking_table(2025, ids, tie, pred, _zeros(n), np.zeros(n), "x", "net")
    with pytest.raises(ValueError):                      # an observed period needs its record
        hr.ranking_table(2021, ids, tie, pred, _zeros(n), None, "x", "net")


def test_recorded_and_predicted_values_stay_separate(world):
    ctx, c = _ctx(world), 2021
    res = hr.backtest_cutoff(ctx, c, SPEC)
    hist, y = hr.observed(ctx, c)
    pred = res["predictions"]["lgbm"]
    ids = ctx.seg.segment_id.values
    tie = segment_id_order(ids)
    t = hr.ranking_table(c, ids, tie, pred, hist, y, "x", "net").to_pandas()
    want_y = window_sums(ctx.ac, len(ids), Fold(c).test_y, ["adj_ksi_cas"]).adj_ksi_cas.values
    np.testing.assert_allclose(t.observed_target_adj_ksi.values, want_y)      # recorded, from collisions
    np.testing.assert_array_equal(t.predicted_adj_ksi.values, pred)           # model output, untouched
    assert not np.allclose(t.predicted_adj_ksi.values, t.observed_target_adj_ksi.values)
    assert (t.predicted_rank.values == national_ranks(pred, tie)).all()
    assert (t.observed_target_rank.values == national_ranks(want_y, tie)).all()
    assert (t.observed_history_rank.values == national_ranks(hist.adj_ksi_cas.values, tie)).all()
    assert set(hr.DICTIONARY) == set(hr.SCHEMA.names)
    pred_cols = [k for k in t.columns if k.startswith("predicted_")]
    obs_cols = [k for k in t.columns if k.startswith("observed_")]
    assert pred_cols == ["predicted_adj_ksi", "predicted_rank"]
    assert all(hr.DICTIONARY[k].startswith("MODEL") for k in pred_cols)
    assert all(hr.DICTIONARY[k].startswith("RECORDED") for k in obs_cols)


def test_overlap_pairs_report_shared_years():
    n = 1000
    rng = np.random.default_rng(0)
    R = {c: {"pred": rng.random(n), "y": None} for c in (2019, 2022)}
    o = hr.overlap_table(R)
    assert set(o.history_years_shared) == {0} and set(o.target_years_shared) == {0}
    assert o.model_overlap.between(0, 1).all()


# ------------------------------------------------------------------ tie-aware top-k statistics
def _exact_expected_overlap(a, b, k):
    """Brute force: every equally likely top-k set of each ranking (ties broken at random)."""
    def sets(score):
        s = np.asarray(score, float)
        cut = np.sort(s)[::-1][k - 1]
        above = set(np.flatnonzero(s > cut))
        tied = list(np.flatnonzero(s == cut))
        return [above | set(c) for c in itertools.combinations(tied, k - len(above))]
    sa, sb = sets(a), sets(b)
    return float(np.mean([len(x & y) for x in sa for y in sb]) / k)


def test_inclusion_without_ties_is_the_top_k_set():
    s = np.array([5.0, 1.0, 4.0, 3.0, 2.0])
    np.testing.assert_array_equal(hr.topk_inclusion(s, 2), [1, 0, 1, 0, 0])
    assert hr.topk_inclusion(s, 5).sum() == 5
    with pytest.raises(ValueError):
        hr.topk_inclusion(s, 0)
    with pytest.raises(ValueError):
        hr.topk_inclusion(s, 6)


def test_fully_tied_ranking_spreads_places_evenly():
    s = np.full(8, 2.0)
    p = hr.topk_inclusion(s, 3)
    np.testing.assert_allclose(p, 3 / 8)
    assert hr.expected_overlap(p, p, 3) == pytest.approx(3 / 8)          # two independent random draws
    assert hr.expected_overlap(p, p, 3) == pytest.approx(_exact_expected_overlap(s, s, 3))


def test_zero_and_positive_ties_get_their_share_of_the_remaining_places():
    s = np.array([3.0, 2.0, 2.0, 2.0, 0.0, 0.0, 0.0, 0.0])
    np.testing.assert_allclose(hr.topk_inclusion(s, 2), [1, 1 / 3, 1 / 3, 1 / 3, 0, 0, 0, 0])   # positive tie split
    np.testing.assert_allclose(hr.topk_inclusion(s, 6), [1, 1, 1, 1, .5, .5, .5, .5])           # zero tie split
    t = hr.tie_at_cut(s, 6)
    assert (t["value_at_cut"], t["tie_block"], t["taken_from_block"]) == (0.0, 4, 2) and t["share_from_zero_tie"] == 2 / 6
    assert hr.tie_at_cut(s, 2)["share_from_zero_tie"] == 0.0


@pytest.mark.parametrize("a,b,k", [
    ([4, 3, 3, 3, 1, 0, 0], [5, 3, 3, 2, 2, 2, 0], 2),       # positive tie split in both rankings
    ([4, 3, 3, 3, 1, 0, 0], [7, 6, 5, 4, 3, 2, 1], 3),       # tie split in one ranking only
    ([2, 1, 1, 0, 0, 0, 0], [0, 1, 1, 2, 0, 0, 0], 4),       # cuts inside the zero tie
    ([1, 1, 1, 1, 1, 1, 1], [3, 2, 2, 2, 1, 1, 0], 3),       # fully tied vs partly tied
])
def test_expected_overlap_equals_exhaustive_enumeration(a, b, k):
    got = hr.expected_overlap(hr.topk_inclusion(a, k), hr.topk_inclusion(b, k), k)
    assert got == pytest.approx(_exact_expected_overlap(a, b, k))


def test_overlap_is_exact_when_scores_do_not_tie():
    rng = np.random.default_rng(3)
    a, b = rng.random(500), rng.random(500)
    for k in (1, 25, 100, 500):
        plain = ((national_ranks(a) <= k) & (national_ranks(b) <= k)).sum() / k
        assert hr.expected_overlap(hr.topk_inclusion(a, k), hr.topk_inclusion(b, k), k) == pytest.approx(plain, abs=1e-15)


def test_segment_id_order_would_overstate_overlap_of_tied_counts():
    # two periods whose counts are all tied: random tie-breaking expects k/n overlap; a fixed
    # segment_id order picks the same segments both times and reports 100%
    n, k = 200, 20
    ids = np.array([f"S{i:03d}" for i in range(n)])
    a = b = np.ones(n)
    tie = segment_id_order(ids)
    fixed = ((national_ranks(a, tie) <= k) & (national_ranks(b, tie) <= k)).sum() / k
    assert fixed == 1.0
    assert hr.expected_overlap(hr.topk_inclusion(a, k), hr.topk_inclusion(b, k), k) == pytest.approx(k / n)


def test_capture_from_inclusion_matches_the_capture_metric():
    rng = np.random.default_rng(4)
    y = rng.poisson(0.3, 2000).astype(float)
    for score in (y, rng.poisson(0.5, 2000).astype(float), rng.random(2000)):
        for f in (0.01, 0.05, 0.10):
            k = int(np.floor(f * len(y)))
            assert 100 * hr.topk_inclusion(score, k) @ y / y.sum() == pytest.approx(capture_at(score, y, f))


def test_gap_decomposition_parts_add_up():
    rng = np.random.default_rng(5)
    n = 5000
    hc = rng.poisson(0.2, n).astype(float)
    R = {2021: {"pred": rng.gamma(1, 1, n) + hc, "y": rng.poisson(0.3, n).astype(float),
                "h": hc * rng.uniform(0, 1.5, n), "hc": hc}}
    g = hr.gap_decomposition(R)
    assert set(g.top) == {"top1pct", "top5pct", "top10pct"}
    np.testing.assert_allclose(g.model_from_history_segments + g.model_from_no_history_segments, g.model_capture)
    np.testing.assert_allclose(g.gap_from_history_segments + g.gap_from_no_history_segments, g.gap)
    assert (g.count_capture >= 0).all() and set(g.count_ranking) <= {"hist_adj_ksi", "hist_collisions"}


def test_writes_are_confined_to_the_research_directory():
    assert hr._guard(hr.OUT / "x.csv") and hr._guard(hr.CKPT / "cutoff_2019.npz") and hr._guard(hr.REPORT)
    for bad in (hr.PRODUCTION_SCORES, hr.PRODUCTION_MODEL, hr.RELEASE_META, OUTPUTS / "frozen_spec.json",
                OUTPUTS / "history_extra" / "x.csv", hr.REPORT.with_name("model_comparison.csv")):
        with pytest.raises(RuntimeError):
            hr._guard(bad)


# ------------------------------------------------------------------ the generated result
@pytest.mark.skipif(not HAVE_RESULT, reason="run ml/experiments/historical_rankings.py first")
def test_cutoff_2025_rows_are_the_stored_production_scores():
    t = pq.read_table(hr.RESULT, columns=["segment_id", "predicted_adj_ksi", "predicted_rank",
                                          "observed_target_adj_ksi", "observed_target_rank"],
                      filters=[("cutoff", "==", hr.FORECAST_CUTOFF)]).to_pandas()
    s = pd.read_parquet(hr.PRODUCTION_SCORES, columns=["segment_id", "blackspot_score", "rank"])
    m = t.merge(s, on="segment_id", how="outer", validate="one_to_one", indicator=True)
    assert (m._merge == "both").all()
    assert (m.predicted_adj_ksi.values == m.blackspot_score.values).all()    # exact, not approximate
    assert (m.predicted_rank.values == m["rank"].values).all()
    assert t.observed_target_adj_ksi.isna().all() and t.observed_target_rank.isna().all()
    info = json.loads(hr.META.read_text(encoding="utf-8"))["cutoffs"][str(hr.FORECAST_CUTOFF)]
    assert info["max_abs_diff_model_vs_stored"] == 0.0 and info["ranks_identical_to_stored"]


@pytest.mark.skipif(not HAVE_RESULT, reason="run ml/experiments/historical_rankings.py first")
def test_ranking_periods_and_metadata_are_consistent():
    meta = json.loads(hr.META.read_text(encoding="utf-8"))
    spec = json.loads((OUTPUTS / "frozen_spec.json").read_text(encoding="utf-8"))
    assert meta["spec_sha256"] == spec["sha256"] and "2026-04" in meta["network_release"]
    assert sorted(int(c) for c in meta["cutoffs"]) == list(hr.CUTOFFS)
    assert all(ch["pass"] for ch in meta["checks"]), [ch["name"] for ch in meta["checks"] if not ch["pass"]]
    assert meta["rows"] == meta["segments"] * len(hr.CUTOFFS) == pq.ParquetFile(hr.RESULT).metadata.num_rows
    text = ["ranking_kind", "train_feature_period", "train_target_period", "history_period", "forecast_period",
            "spec_sha256", "network_release", "caveat"]
    for c in hr.CUTOFFS:
        t = pq.read_table(hr.RESULT, columns=text + ["target_observed", "observed_target_adj_ksi"],
                          filters=[("cutoff", "==", c)], read_dictionary=text)
        assert t.num_rows == meta["segments"]
        p = hr.periods(c)
        want = {**{k: p[k] for k in text[:5]}, "spec_sha256": spec["sha256"],
                "network_release": meta["network_release"], "caveat": hr.caveat(c, meta["network_release"])}
        for k, v in want.items():
            assert t.column(k).unique().to_pylist() == [v], (c, k)
        assert t.column("target_observed").unique().to_pylist() == [p["target_observed"]]
        assert (t.column("observed_target_adj_ksi").null_count == 0) == p["target_observed"]
        m = meta["cutoffs"][str(c)]
        assert (m["history_period"], m["forecast_period"]) == (p["history_period"], p["forecast_period"])
        if c in hr.BACKTEST_CUTOFFS:
            assert m["model_source"].startswith("refitted")
            assert m["future_invariance"]["training_frame_identical"] and m["future_invariance"]["prediction_features_identical"]


def _table_after(text: str, heading: str) -> list[list[str]]:
    """Rows of the first markdown table after `heading`."""
    lines = text[text.index(heading):].splitlines()
    i = next(j for j, ln in enumerate(lines) if ln.startswith("| "))
    rows = []
    for ln in lines[i + 2:]:
        if not ln.startswith("| "):
            break
        rows.append([c.strip() for c in ln.strip("|").split("|")])
    return [[c.strip() for c in lines[i].strip("|").split("|")]] + rows


def _pct_or_dash(v, blank):
    return "—" if blank else f"{100 * v:.0f}%"


@pytest.mark.skipif(not HAVE_RESULT, reason="run ml/experiments/historical_rankings.py first")
def test_report_figures_agree_with_the_summary_csvs():
    text = hr.REPORT.read_text(encoding="utf-8")
    ovl = pd.read_csv(hr.OUT / "overlap_between_periods.csv")
    within = pd.read_csv(hr.OUT / "overlap_within_cutoff.csv")
    gaps = pd.read_csv(hr.OUT / "gap_decomposition.csv")
    cap = pd.read_csv(hr.OUT / "capture.csv")
    ties = pd.read_csv(hr.OUT / "tie_blocks.csv")

    # section 5 table == overlap_between_periods.csv
    head, *rows = _table_after(text, "## 5. Rank overlap between periods")
    assert len(rows) == len(ovl)
    for r in rows:
        d = dict(zip(head, r))
        row = ovl[(ovl.cutoff_a == int(d["cutoff_a"])) & (ovl.cutoff_b == int(d["cutoff_b"])) & (ovl.k_name == d["k_name"])].iloc[0]
        assert d["model_overlap"] == f"{100 * row.model_overlap:.0f}%"
        blank = pd.isna(row.recorded_target_overlap) or row.recorded_share_from_zero_tie > 0
        assert d["recorded_target_overlap"] == _pct_or_dash(row.recorded_target_overlap, blank)

    # section 4 table == overlap_within_cutoff.csv
    head, *rows = _table_after(text, "## 4. Ties")
    assert len(rows) == len(within)
    for r in rows:
        d = dict(zip(head, r))
        row = within[(within.cutoff == int(d["cutoff"])) & (within.k_name == d["k_name"])].iloc[0]
        assert d["model_vs_history_count_overlap"] == _pct_or_dash(
            row.model_vs_history_count_overlap, row.history_count_share_from_zero_tie > 0)
        zt = pd.isna(row.recorded_target_share_from_zero_tie) or row.recorded_target_share_from_zero_tie > 0
        assert d["model_vs_recorded_target_overlap"] == _pct_or_dash(row.model_vs_recorded_target_overlap, zt)

    # gap bullets == gap_decomposition.csv, and the decomposition == capture.csv
    for top, label in (("top1pct", "Whole network, top 1%"), ("top10pct", "Whole network, top 10%")):
        line = next(ln for ln in text.splitlines() if label in ln)
        got = {int(c): float(v) for c, v in re.findall(r"(20\d\d): ([+-]\d+\.\d)", line)}
        want = gaps[gaps.top == top].set_index("cutoff").gap.round(1)
        assert got == {int(c): float(v) for c, v in want.items()}
    m = gaps.merge(cap[(cap.population == "all") & (cap.ranking == "model")], on="cutoff")
    for _, r in m.iterrows():
        assert r.model_capture == pytest.approx(r[f"capture_{r.top.replace('pct', '')}"], abs=1e-9)
    g10 = gaps[gaps.top == "top10pct"]
    assert (g10.gap_from_history_segments < 0).all() and (g10.gap_from_no_history_segments > g10.gap).all()
    hist_line = next(ln for ln in text.splitlines() if "Segments with recorded history only" in ln)
    h = cap[cap.population == "hist1"].pivot_table(index="cutoff", columns="model", values="capture_top1")
    want1 = (h["lgbm"] - h[["hist_adj_ksi", "hist_collisions"]].max(axis=1)).round(1)
    got1 = {int(c): float(v) for c, v in re.findall(r"(20\d\d): ([+-]\d+\.\d)", hist_line.split("top 5%")[0])}
    assert got1 == {int(c): float(v) for c, v in want1.items()}

    # tie sentence == tie_blocks.csv
    t1 = ties[(ties.ranking == "recorded_target") & (ties.k_name == "top1pct")]
    assert f"{t1.tie_block.min():,}–{t1.tie_block.max():,} segments" in text
    split = ties[(ties.ranking == "model") & ties.split]
    for r in split.itertuples():                                 # every split model tie is disclosed
        assert f"cutoff {r.cutoff} {r.k_name}: {r.taken_from_block} of {r.tie_block} tied segments fit" in text
    assert set(ties[ties.ranking == "model"].ranking_kind) <= {hr.RETRO, hr.PRODUCTION}
    assert (ties[(ties.ranking == "model") & (ties.cutoff == hr.FORECAST_CUTOFF)].ranking_kind == hr.PRODUCTION).all()

    # retired wording and retained caveats
    for gone in ("dominated by chance", "snapshot (used for every period) snapshot", "(one snapshot for every period) snapshot",
                 "tie at zero for most segments; the stored observed ranks order"):
        assert gone not in text
    for kept in ("Retrospective, not prospective", "The holdout is not untouched here", "Incomplete period omitted",
                 "One road network for every period", "Stability is not accuracy"):
        assert kept in text
