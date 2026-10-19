"""Historical blackspot rankings: retrospective backtests (research only).

    .venv/Scripts/python ml/experiments/historical_rankings.py                 (~15 min, ~3-4 GB RAM)
    .venv/Scripts/python ml/experiments/historical_rankings.py --cutoffs 2019  (one cutoff, checkpointed)
    .venv/Scripts/python ml/experiments/historical_rankings.py --report-only   (summaries + report from checkpoints)

WHAT IT DOES
  Cutoffs 2019-2023: the frozen v2 specification (selected model, frozen hyperparameters, the
  same 45 features) is refitted on the audited training pair of features.Fold(c), features
  c-4..c-2 -> target c-1..c, and applied to the history window c-2..c. That ranks the segments
  for c+1..c+2. Fitting, scoring and the count baselines run through experiment.run_fold, the
  code path of the development and holdout folds, so the metrics must reproduce the archived
  fold results. Nothing is tuned and no feature or model is chosen here.

  Cutoff 2025: the production forecast. The released scores are reproduced by the saved
  production model (no refit) and must be identical. The production model is never applied to
  earlier periods: it was trained on 2024-2025 outcomes.

  Cutoff 2024 is omitted: its 2025-2026 target is incomplete (the data end in 2025).

  Recorded KSI (history and target windows) is aggregated from collisions with
  features.window_sums, never from model output, and kept in separate observed_* columns.

THESE ARE NOT UNTOUCHED EVALUATIONS
  - The specification was selected on development folds whose targets run to 2023.
  - The 2024-25 holdout (cutoff 2023) was already examined; 2023-24 (cutoff 2022) overlaps it.
  - Every period uses the OS Open Roads 2026-04 network snapshot, not the network of its time.

Writes only ml/outputs/history/ and ml/reports/historical_rankings.md (`_guard`). The
production model, scores, release files and contract are read, never written.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import BACKEND_DATA, FIRST_YEAR, LAST_YEAR, OUTPUTS, REPORTS  # noqa: E402
from blackspot.evaluation import calibration_table, capture_at  # noqa: E402
from blackspot.experiment import _cols, national_ksi, run_fold, standard_specs  # noqa: E402
from blackspot.features import (COUNT_COLS, DEV_CUTOFFS, FORECAST_CUTOFF, HOLDOUT_CUTOFF,  # noqa: E402
                                POSTHOC_CUTOFFS, PRIMARY, Fold, build_frame, window_sums)
from blackspot.io_utils import atomic_path, file_hash, setup_logging, write_csv, write_json, write_text  # noqa: E402
from blackspot.stability import national_ranks, segment_id_order  # noqa: E402
from blackspot.windows import COVID_YEARS  # noqa: E402

log = logging.getLogger("blackspot.history")

OUT = OUTPUTS / "history"
CKPT = OUT / "checkpoints"
RESULT = OUT / "historical_rankings.parquet"
META = OUT / "historical_rankings_meta.json"
REPORT = REPORTS / "historical_rankings.md"
PRODUCTION_MODEL = OUTPUTS / "explainability" / "production_lgbm.txt"
PRODUCTION_VERIFICATION = OUTPUTS / "explainability" / "production_model_verification.json"
PRODUCTION_SCORES = OUTPUTS / "road_segments_v2_full.parquet"
RELEASE_META = BACKEND_DATA / "v2" / "road_segments_meta_v2.json"

RETRO, PRODUCTION, OBSERVED = "retrospective_backtest", "production_forecast", "observed"
# earliest cutoff whose TRAINING features (c-4..c-2) start inside the data
EARLIEST_CUTOFF = min(c for c in range(FIRST_YEAR, LAST_YEAR + 1) if Fold(c).train_x.start >= FIRST_YEAR)
BACKTEST_CUTOFFS = tuple(c for c in range(EARLIEST_CUTOFF, FORECAST_CUTOFF) if Fold(c).test_y.end <= LAST_YEAR)
OMITTED = {c: f"target {Fold(c).test_y} is incomplete: the data end in {LAST_YEAR}"
           for c in range(EARLIEST_CUTOFF, FORECAST_CUTOFF) if c not in BACKTEST_CUTOFFS}
CUTOFFS = BACKTEST_CUTOFFS + (FORECAST_CUTOFF,)
BASELINES = {"hist_adj_ksi": "recorded history: adjusted KSI casualties",
             "hist_collisions": "recorded history: collisions"}
POPULATIONS = ("all", "hist1")
TOPK_FRACS = (0.01, 0.05, 0.10)
CAP_COLS = ["cutoff", "forecast_period", "population", "ranking", "model", "ranking_kind", "capture_top1",
            "capture_top5", "capture_top10", "capture_top20", "poisson_deviance", "sum_pred_over_obs"]
REP_COLS = ["cutoff", "archived_study", "model", "metrics_compared", "max_abs_diff"]

SCHEMA = pa.schema([
    ("cutoff", pa.int16()), ("ranking_kind", pa.string()),
    ("train_feature_period", pa.string()), ("train_target_period", pa.string()),
    ("history_period", pa.string()), ("forecast_period", pa.string()), ("target_observed", pa.bool_()),
    ("segment_id", pa.string()),
    ("predicted_adj_ksi", pa.float64()), ("predicted_rank", pa.int32()),
    ("observed_target_adj_ksi", pa.float64()), ("observed_target_rank", pa.int32()),
    ("observed_history_adj_ksi", pa.float64()), ("observed_history_ksi_cas", pa.int32()),
    ("observed_history_collisions", pa.int32()), ("observed_history_ksi_collisions", pa.int32()),
    ("observed_history_fatal_cas", pa.int32()), ("observed_history_rank", pa.int32()),
    ("spec_sha256", pa.string()), ("network_release", pa.string()), ("caveat", pa.string()),
])
DICTIONARY = {
    "cutoff": "last year of data the ranking may use",
    "ranking_kind": f"what predicted_* are: '{RETRO}' (2019-2023, refitted at the cutoff) or '{PRODUCTION}' (2025)",
    "train_feature_period": "history window of the training pair (features c-4..c-2)",
    "train_target_period": "target window of the training pair (c-1..c); never beyond the cutoff",
    "history_period": "history window the ranking is computed from (c-2..c)",
    "forecast_period": "two-year period the ranking forecasts (c+1..c+2)",
    "target_observed": "whether the forecast period is complete in the data",
    "segment_id": "OS Open Roads 2026-04 segment (same id in every period)",
    "predicted_adj_ksi": "MODEL OUTPUT: expected adjusted KSI casualties in forecast_period",
    "predicted_rank": "MODEL RANK: 1 = highest predicted_adj_ksi; ties by segment_id ascending (production rule)",
    "observed_target_adj_ksi": "RECORDED: adjusted KSI casualties in forecast_period; null when not observed",
    "observed_target_rank": f"RECORDED RANK ({OBSERVED}): rank of observed_target_adj_ksi; null when not observed. "
                            "Recorded counts tie heavily, at zero and at positive values (e.g. 1.0 adjusted KSI); tied "
                            "segments are ordered by segment_id only, which is arbitrary. Do not build top-k sets from "
                            "this column: the summaries use tie-aware inclusion probabilities (topk_inclusion)",
    "observed_history_adj_ksi": "RECORDED: adjusted KSI casualties in history_period",
    "observed_history_ksi_cas": "RECORDED: KSI casualties as reported in history_period",
    "observed_history_collisions": "RECORDED: collisions in history_period",
    "observed_history_ksi_collisions": "RECORDED: collisions with >= 1 KSI casualty in history_period",
    "observed_history_fatal_cas": "RECORDED: fatal casualties in history_period",
    "observed_history_rank": f"RECORDED RANK ({OBSERVED}): rank of observed_history_adj_ksi (the count ranking a "
                             "history-only method would give). Ties at zero and at positive values are ordered by "
                             "segment_id only; use tie-aware statistics, not top-k sets from this column",
    "spec_sha256": "frozen model specification (ml/outputs/frozen_spec.json)",
    "network_release": "road network used for every period",
    "caveat": "what the row's ranking is and is not",
}


# ------------------------------------------------------------------ periods
def ranking_kind(c: int) -> str:
    """Role of a cutoff; raises for cutoffs that cannot be ranked honestly."""
    if c == FORECAST_CUTOFF:
        return PRODUCTION
    if c in BACKTEST_CUTOFFS:
        return RETRO
    if c in OMITTED:
        raise ValueError(f"cutoff {c} is omitted: {OMITTED[c]}")
    if c < EARLIEST_CUTOFF:
        raise ValueError(f"cutoff {c} is before {EARLIEST_CUTOFF}: its training features ({Fold(c).train_x}) "
                         f"would start before the first data year {FIRST_YEAR}")
    raise ValueError(f"cutoff {c} is after the production cutoff {FORECAST_CUTOFF}: no data after {LAST_YEAR}")


def periods(c: int) -> dict:
    kind = ranking_kind(c)
    f = Fold(c)
    return {"cutoff": c, "ranking_kind": kind, "train_feature_period": str(f.train_x),
            "train_target_period": str(f.train_y), "history_period": str(f.test_x),
            "forecast_period": str(f.test_y), "target_observed": f.test_y.end <= LAST_YEAR}


def fold_role(c: int) -> str:
    if c in DEV_CUTOFFS:
        return "development fold (spec selection)"
    if c in POSTHOC_CUTOFFS:
        return "post-hoc fold (overlaps holdout)"
    if c == HOLDOUT_CUTOFF:
        return "final holdout (already examined)"
    if c == FORECAST_CUTOFF:
        return "production"
    return "not a v2 fold"


def caveat(c: int, network: str) -> str:
    p = periods(c)
    f = Fold(c)
    net = (f"Road segments, classes and junctions are the {network.split(' (')[0]} snapshot (used for every period), "
           f"not the network of {p['history_period']}.")
    if p["ranking_kind"] == PRODUCTION:
        return ("Production forecast: the released v2.0 scores, reproduced by the saved production model (not "
                f"refitted). {p['forecast_period']} is not yet observed. The model was trained on the 2024-2025 "
                f"outcomes of the examined holdout. {net}")
    parts = [f"Retrospective backtest, not a ranking that existed in {c}: the model type, hyperparameters and "
             "features were chosen in 2026 on development folds with targets up to 2023."]
    if c in DEV_CUTOFFS:
        parts.append(f"This cutoff's target {p['forecast_period']} was one of the selection targets.")
    if c in POSTHOC_CUTOFFS:
        parts.append(f"Target {p['forecast_period']} overlaps the already-examined 2024-2025 holdout.")
    if c == HOLDOUT_CUTOFF:
        parts.append(f"Target {p['forecast_period']} is the final holdout, already examined: not an untouched test.")
    covid = sorted(set(COVID_YEARS) & set(f.train_x.years + f.train_y.years + f.test_x.years + f.test_y.years))
    if covid:
        parts.append(f"COVID-affected years ({', '.join(map(str, covid))}) fall in this cutoff's history, training "
                     "or target windows, so totals are less reliable than ranks.")
    parts.append(net)
    return " ".join(parts)


def network_release() -> str:
    seg = json.loads(RELEASE_META.read_text(encoding="utf-8")).get("segmentation", "")
    m = re.search(r"OS Open Roads centrelines \((\d{4}-\d{2}) release\)", seg)
    if not m:
        raise RuntimeError(f"{RELEASE_META} does not name the OS Open Roads release")
    return f"OS Open Roads {m.group(1)} (one snapshot for every period)"


def _guard(path: Path) -> Path:
    """Every write goes through here: only the research directory and the report."""
    p = Path(path).resolve()
    if p == REPORT.resolve() or p == OUT.resolve() or OUT.resolve() in p.parents:
        return p
    raise RuntimeError(f"refusing to write outside {OUT} and {REPORT}: {p}")


# ------------------------------------------------------------------ models
def selected_spec(spec: dict):
    return next(s for s in standard_specs(spec["lgbm_params"]) if s.name == spec["selected_model"])


def backtest_specs(spec: dict) -> list:
    chosen = selected_spec(spec)
    return [chosen] + [s for s in standard_specs(spec["lgbm_params"]) if s.name in BASELINES and s.name != chosen.name]


def backtest_cutoff(ctx, c: int, spec: dict) -> dict:
    """Refit the frozen specification on Fold(c)'s training pair and score its test pair (run_fold)."""
    if ranking_kind(c) != RETRO:
        raise ValueError(f"cutoff {c} is not a backtest cutoff; backtests are {BACKTEST_CUTOFFS}")
    fold = Fold(c)
    if fold.train_y.end > c or fold.test_x.end > c:
        raise AssertionError(f"fold {c} uses years after its cutoff")
    return run_fold(ctx, fold, backtest_specs(spec), populations=POPULATIONS, n_boot=0, reference=None,
                    keep_predictions=True)


def future_invariance(ctx, c: int, Xte: pd.DataFrame) -> dict:
    """Real-data leakage check: dropping every collision after the cutoff leaves both frames unchanged."""
    fold = Fold(c)
    ac_cut = ctx.ac[ctx.ac.collision_year <= c]
    full = build_frame(ctx.seg, ctx.ac, fold.train_x, fold.train_y, ctx.road)
    cut = build_frame(ctx.seg, ac_cut, fold.train_x, fold.train_y, ctx.road)
    same_train = bool(full.equals(cut))
    del full, cut
    te_cut = build_frame(ctx.seg, ac_cut, fold.test_x, None, ctx.road)
    same_test = bool(Xte[list(te_cut.columns)].equals(te_cut))
    return {"collisions_after_cutoff_dropped": int(len(ctx.ac) - len(ac_cut)),
            "training_frame_identical": same_train, "prediction_features_identical": same_test}


def load_production_model():
    from lightgbm import Booster
    return Booster(model_file=str(PRODUCTION_MODEL))


def production_cutoff(ctx, spec: dict) -> tuple[np.ndarray, dict]:
    """The released scores, checked against the saved production model on the 2023-25 features."""
    fold = Fold(FORECAST_CUTOFF)
    ver = json.loads(PRODUCTION_VERIFICATION.read_text(encoding="utf-8"))
    if ver["frozen_spec_sha256"] != spec["sha256"]:
        raise RuntimeError("saved production model belongs to another spec")
    if file_hash(PRODUCTION_MODEL) != ver["model_file_sha256"]:
        raise RuntimeError("production_lgbm.txt differs from the verified model file")
    Xte = build_frame(ctx.seg, ctx.ac, fold.test_x, None, ctx.road)
    cols = _cols(Xte, selected_spec(spec).groups)
    if cols != ver["features"]:
        raise RuntimeError("feature order differs from the verified production model")
    p_model = load_production_model().predict(Xte[cols].values.astype(np.float32))
    del Xte
    ids = ctx.seg.segment_id.values
    stored = pd.read_parquet(PRODUCTION_SCORES, columns=["segment_id", "blackspot_score", "rank", "forecast_period",
                                                         "history_period"]).set_index("segment_id").reindex(ids)
    if stored.blackspot_score.isna().any():
        raise RuntimeError("segments missing from the stored forecast")
    score = stored.blackspot_score.values.astype(np.float64)
    diff = float(np.max(np.abs(p_model - score)))
    if diff != 0.0:
        raise RuntimeError(f"saved production model does not reproduce the stored scores (max diff {diff})")
    ranks_same = bool(np.array_equal(national_ranks(score, segment_id_order(ids)), stored["rank"].values))
    if not ranks_same:
        raise RuntimeError("the production tie rule does not reproduce the stored ranks")
    if set(stored.forecast_period) != {str(fold.test_y)} or set(stored.history_period) != {str(fold.test_x)}:
        raise RuntimeError("stored forecast periods differ from Fold(2025)")
    return score, {"source": "stored release scores (road_segments_v2_full.parquet); not refitted",
                   "check": "saved production model applied to the 2023-2025 features",
                   "max_abs_diff_model_vs_stored": diff, "ranks_identical_to_stored": ranks_same,
                   "model_file_sha256": ver["model_file_sha256"]}


# ------------------------------------------------------------------ tables
def observed(ctx, c: int) -> tuple[pd.DataFrame, np.ndarray | None]:
    """Recorded counts from collisions only: history window and (if complete) target window."""
    f, n = Fold(c), len(ctx.seg)
    hist = window_sums(ctx.ac, n, f.test_x, COUNT_COLS)
    y = window_sums(ctx.ac, n, f.test_y, [PRIMARY])[PRIMARY].values if periods(c)["target_observed"] else None
    return hist, y


def _int(v: np.ndarray, name: str) -> pa.Array:
    r = np.rint(v)
    if not np.allclose(r, v):
        raise ValueError(f"{name} is not integral")
    return pa.array(r.astype(np.int32), pa.int32())


def ranking_table(c: int, segment_ids, tie: np.ndarray, pred: np.ndarray, hist: pd.DataFrame,
                  y: np.ndarray | None, spec_sha: str, network: str) -> pa.Table:
    """One cutoff's rows. Model output, recorded counts and their ranks stay in separate columns."""
    p = periods(c)
    n = len(segment_ids)
    if not (len(pred) == len(hist) == n == len(tie)) or (y is not None and len(y) != n):
        raise ValueError("arrays are not aligned with the segments")
    if (y is None) == p["target_observed"]:
        raise ValueError(f"cutoff {c}: target {'missing' if y is None else 'given'} for "
                         f"{'an observed' if p['target_observed'] else 'an unobserved'} period")

    def const(v, t):
        return pa.repeat(pa.scalar(v, t), n)

    cols = {
        "cutoff": const(c, pa.int16()), "ranking_kind": const(p["ranking_kind"], pa.string()),
        "train_feature_period": const(p["train_feature_period"], pa.string()),
        "train_target_period": const(p["train_target_period"], pa.string()),
        "history_period": const(p["history_period"], pa.string()),
        "forecast_period": const(p["forecast_period"], pa.string()),
        "target_observed": const(p["target_observed"], pa.bool_()),
        "segment_id": pa.array(np.asarray(segment_ids).astype(str), pa.string()),
        "predicted_adj_ksi": pa.array(np.asarray(pred, np.float64), pa.float64()),
        "predicted_rank": pa.array(national_ranks(np.asarray(pred, np.float64), tie), pa.int32()),
        "observed_target_adj_ksi": pa.nulls(n, pa.float64()) if y is None else pa.array(y, pa.float64()),
        "observed_target_rank": pa.nulls(n, pa.int32()) if y is None else pa.array(national_ranks(y, tie), pa.int32()),
        "observed_history_adj_ksi": pa.array(hist.adj_ksi_cas.values, pa.float64()),
        "observed_history_ksi_cas": _int(hist.n_ksi_cas.values, "n_ksi_cas"),
        "observed_history_collisions": _int(hist.n_coll.values, "n_coll"),
        "observed_history_ksi_collisions": _int(hist.is_ksi_collision.values, "is_ksi_collision"),
        "observed_history_fatal_cas": _int(hist.n_fatal_cas.values, "n_fatal_cas"),
        "observed_history_rank": pa.array(national_ranks(hist.adj_ksi_cas.values, tie), pa.int32()),
        "spec_sha256": const(spec_sha, pa.string()), "network_release": const(network, pa.string()),
        "caveat": const(caveat(c, network), pa.string()),
    }
    return pa.table(cols, schema=SCHEMA)


# ------------------------------------------------------------------ checkpoints
def _seg_key(ids) -> str:
    import hashlib
    return hashlib.sha256("\n".join(np.asarray(ids).astype(str)).encode()).hexdigest()


def save_checkpoint(c: int, pred: np.ndarray, info: dict, metrics: pd.DataFrame | None) -> None:
    with atomic_path(_guard(CKPT / f"cutoff_{c}.npz")) as tmp:
        with open(tmp, "wb") as fh:
            np.savez_compressed(fh, pred=np.asarray(pred, np.float64))
    write_json(info, _guard(CKPT / f"cutoff_{c}.json"))
    if metrics is not None:
        write_csv(metrics, _guard(CKPT / f"cutoff_{c}_metrics.csv"))


def load_checkpoint(c: int, seg_key: str):
    ck = CKPT / f"cutoff_{c}.npz"
    if not ck.exists():
        return None
    info = json.loads((CKPT / f"cutoff_{c}.json").read_text(encoding="utf-8"))
    if info.get("segment_key") != seg_key:
        raise RuntimeError(f"checkpoint {ck} was made for another segment set; rerun with --fresh")
    with np.load(ck) as z:
        pred = z["pred"]
    mpath = CKPT / f"cutoff_{c}_metrics.csv"
    return pred, info, (pd.read_csv(mpath) if mpath.exists() else None)


def peak_memory_mb() -> dict:
    """Peak working set and peak commit of this process (Windows), or max RSS elsewhere."""
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return {"peak_working_set_mb": round(pmc.PeakWorkingSetSize / 2**20),
                    "peak_commit_mb": round(pmc.PeakPagefileUsage / 2**20)}
    except (AttributeError, OSError):
        pass
    try:
        import resource
        return {"max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)}
    except ImportError:
        return {}


# ------------------------------------------------------------------ summaries
# Top-k statistics on rankings with ties. A recorded-count ranking has large tie blocks: every
# zero-KSI segment, and whole-number adjusted values such as 1.0 or 2.0. The k-th place often falls
# inside such a block. The stored *_rank columns order a block by segment_id, which is arbitrary and
# the same in every period, so top-k sets built from them would share the same arbitrary members
# across periods and overstate persistence. Every top-k statistic below therefore uses inclusion
# probabilities under uniform random tie-breaking, computed exactly (no seed, no simulation). It is
# the same pro-rata rule as the capture metric (evaluation.capture_at).
def topk_inclusion(score, k: int) -> np.ndarray:
    """P(row is in the top k) when ties at the cut are broken uniformly at random.

    Rows above the k-th largest value are in (1), rows below are out (0), and the rows tied with the
    k-th value share the remaining places equally. The probabilities sum to k.
    """
    s = np.asarray(score, float)
    n = len(s)
    if not 0 < k <= n:
        raise ValueError(f"k = {k} is outside 1..{n}")
    cut = np.partition(s, n - k)[n - k]                     # the k-th largest value
    above, tied = s > cut, s == cut
    p = above.astype(float)
    p[tied] = (k - int(above.sum())) / int(tied.sum())
    return p


def expected_overlap(p_a: np.ndarray, p_b: np.ndarray, k: int) -> float:
    """E|A & B| / k for two top-k sets whose ties are broken independently at random.

    Equals the plain set overlap when neither ranking has a tie at its cut.
    """
    return float(np.dot(p_a, p_b) / k)


def tie_at_cut(score, k: int) -> dict:
    """The tie block the k-th place falls in (tie_block 1 = no tie at the cut)."""
    s = np.asarray(score, float)
    cut = float(np.partition(s, len(s) - k)[len(s) - k])
    above, tied = int((s > cut).sum()), int((s == cut).sum())
    return {"value_at_cut": cut, "tie_block": tied, "taken_from_block": k - above,
            "share_from_zero_tie": (k - above) / k if cut == 0 else 0.0}


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(pd.Series(a).rank().values, pd.Series(b).rank().values)[0, 1])


def topk_sizes(n: int) -> dict[str, int]:
    return {"top100": 100, "top1000": 1000, "top1pct": int(n * 0.01), "top5pct": int(n * 0.05)}


# rankings compared in the summaries: model output, and two rankings of recorded counts
RANKINGS = {"model": ("pred", RETRO), "recorded_target": ("y", OBSERVED), "recorded_history_ksi": ("h", OBSERVED)}


class _Inclusion:
    """Memoised topk_inclusion per (cutoff, ranking, k): each is reused by several tables."""

    def __init__(self, R: dict):
        self.R, self.memo = R, {}

    def __call__(self, c: int, key: str, k: int) -> np.ndarray:
        if (c, key, k) not in self.memo:
            self.memo[(c, key, k)] = topk_inclusion(self.R[c][key], k)
        return self.memo[(c, key, k)]


def tie_table(R: dict) -> pd.DataFrame:
    """Where each ranking's top-k cut falls: the size of the tie block and how much of it is taken."""
    rows = []
    for c, A in sorted(R.items()):
        for rk, (key, kind) in RANKINGS.items():
            if A.get(key) is None:
                continue
            for name, k in topk_sizes(len(A["pred"])).items():
                t = tie_at_cut(A[key], k)
                rows.append({"cutoff": c, "ranking": rk, "ranking_kind": ranking_kind(c) if rk == "model" else kind,
                             "k_name": name, "k": k, **t, "split": t["taken_from_block"] < t["tie_block"]})
    return pd.DataFrame(rows)


def overlap_table(R: dict, inc: _Inclusion | None = None) -> pd.DataFrame:
    """Top-k overlap between periods: consecutive cutoffs, plus pairs whose windows share no years.

    model_overlap is exact (model scores do not tie at these cuts; see tie_table);
    recorded_target_overlap is the expected overlap under independent random tie-breaking.
    """
    inc = inc or _Inclusion(R)
    cs = sorted(R)
    pairs = list(zip(cs, cs[1:]))
    for a in cs:
        for b in cs:
            if a < b and (b - a) in (2, 3) and (a, b) not in pairs:
                pairs.append((a, b))
    rows = []
    for a, b in sorted(pairs):
        A, B = R[a], R[b]
        hist_shared = len(set(Fold(a).test_x.years) & set(Fold(b).test_x.years))
        tgt_shared = len(set(Fold(a).test_y.years) & set(Fold(b).test_y.years))
        for name, k in topk_sizes(len(A["pred"])).items():
            r = {"cutoff_a": a, "cutoff_b": b, "history_years_shared": hist_shared, "target_years_shared": tgt_shared,
                 "k_name": name, "k": k, "model_overlap": expected_overlap(inc(a, "pred", k), inc(b, "pred", k), k)}
            if A.get("y") is not None and B.get("y") is not None:
                ta, tb = tie_at_cut(A["y"], k), tie_at_cut(B["y"], k)
                r.update({"recorded_target_overlap": expected_overlap(inc(a, "y", k), inc(b, "y", k), k),
                          "recorded_tie_block_a": ta["tie_block"], "recorded_tie_block_b": tb["tie_block"],
                          "recorded_share_from_zero_tie": max(ta["share_from_zero_tie"], tb["share_from_zero_tie"])})
            rows.append(r)
        rows[-1]["model_spearman_all"] = _spearman(A["pred"], B["pred"])
    return pd.DataFrame(rows)


def within_cutoff_table(R: dict, inc: _Inclusion | None = None) -> pd.DataFrame:
    """Per cutoff: agreement of the model ranking with the recorded-history and recorded-target rankings."""
    inc = inc or _Inclusion(R)
    rows = []
    for c, A in sorted(R.items()):
        for name, k in topk_sizes(len(A["pred"])).items():
            th = tie_at_cut(A["h"], k)
            r = {"cutoff": c, "k_name": name, "k": k,
                 "model_vs_history_count_overlap": expected_overlap(inc(c, "pred", k), inc(c, "h", k), k),
                 "history_count_tie_block": th["tie_block"], "history_count_share_from_zero_tie": th["share_from_zero_tie"]}
            if A.get("y") is not None:
                ty = tie_at_cut(A["y"], k)
                r.update({"model_vs_recorded_target_overlap": expected_overlap(inc(c, "pred", k), inc(c, "y", k), k),
                          "history_count_vs_recorded_target_overlap": expected_overlap(inc(c, "h", k), inc(c, "y", k), k),
                          "recorded_target_tie_block": ty["tie_block"],
                          "recorded_target_share_from_zero_tie": ty["share_from_zero_tie"]})
            rows.append(r)
    return pd.DataFrame(rows)


def gap_decomposition(R: dict, fracs=(0.01, 0.05, 0.10)) -> pd.DataFrame:
    """Model minus the better count ranking, split into segments with and without recorded history.

    Capture = sum of inclusion x recorded target KSI / total recorded target KSI (identical to the
    tie-aware capture metric). "History" = at least one recorded collision in the history window.
    """
    rows = []
    for c, A in sorted(R.items()):
        y = A.get("y")
        if y is None:
            continue
        tot, hist = float(y.sum()), A["hc"] > 0
        for f in fracs:
            k = int(np.floor(f * len(y)))

            def part(p, mask):
                return float(100 * np.dot(p[mask], y[mask]) / tot)

            pm = topk_inclusion(A["pred"], k)
            counts = {"hist_adj_ksi": topk_inclusion(A["h"], k), "hist_collisions": topk_inclusion(A["hc"], k)}
            best = max(counts, key=lambda nm: float(np.dot(counts[nm], y)))
            pc = counts[best]
            r = {"cutoff": c, "top": f"top{int(round(f * 100))}pct", "k": k, "count_ranking": best,
                 "segments_with_history": int(hist.sum()),
                 "model_capture": part(pm, slice(None)), "count_capture": part(pc, slice(None)),
                 "model_from_history_segments": part(pm, hist), "model_from_no_history_segments": part(pm, ~hist),
                 "count_from_history_segments": part(pc, hist), "count_from_no_history_segments": part(pc, ~hist)}
            r["gap"] = r["model_capture"] - r["count_capture"]
            r["gap_from_history_segments"] = r["model_from_history_segments"] - r["count_from_history_segments"]
            r["gap_from_no_history_segments"] = r["model_from_no_history_segments"] - r["count_from_no_history_segments"]
            rows.append(r)
    return pd.DataFrame(rows)


def persistence(R: dict, ids, info_cols: pd.DataFrame, inc: _Inclusion | None = None):
    """Persistent versus newly emerging high-ranked segments (model ranking, tie-aware counts)."""
    inc = inc or _Inclusion(R)
    back = [c for c in sorted(R) if c in BACKTEST_CUTOFFS]
    rows, lists = [], {}
    for name, k in (("top1000", 1000), ("top1pct", int(len(ids) * 0.01))):
        p = {c: inc(c, "pred", k) for c in R}
        all_back = np.prod([p[c] for c in back], axis=0) if back else np.zeros(len(ids))
        none_back = np.prod([1 - p[c] for c in back], axis=0) if back else np.ones(len(ids))
        r = {"k_name": name, "k": k, "in_every_backtest": float(all_back.sum()),
             "backtest_cutoffs": "-".join(map(str, back))}
        if FORECAST_CUTOFF in R:
            prod = p[FORECAST_CUTOFF]
            r.update({"in_every_backtest_and_production": float((all_back * prod).sum()),
                      "production_never_in_a_backtest": float((prod * none_back).sum()),
                      "production_also_in_2023_backtest": float((prod * p[back[-1]]).sum()) if back else 0.0})
            lists[name] = ((all_back * prod) == 1, (prod == 1) & (none_back == 1))
        for a, b in zip(back, back[1:]):
            r[f"entered_{b}"] = float((p[b] * (1 - p[a])).sum())
        rows.append(r)
    pers, new = pd.DataFrame(), pd.DataFrame()
    if "top1000" in lists:
        keep_p, keep_n = lists["top1000"]
        ranks = pd.DataFrame({f"rank_{c}": R[c]["pred_rank"] for c in sorted(R)})
        ranks.insert(0, "segment_id", np.asarray(ids).astype(str))
        base = ranks.join(info_cols.reset_index(drop=True))
        pers = base[keep_p].sort_values(f"rank_{FORECAST_CUTOFF}")
        new = base[keep_n].sort_values(f"rank_{FORECAST_CUTOFF}")
        new.insert(1, "best_backtest_rank", ranks.loc[keep_n, [f"rank_{c}" for c in back]].min(axis=1).values)
    return pd.DataFrame(rows), pers, new


# ------------------------------------------------------------------ report
def _pct(v, d=1):
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{d}f}"


def _range(lo: float, hi: float) -> str:
    a, b = f"{100*lo:.0f}", f"{100*hi:.0f}"
    return f"{a}%" if a == b else f"{a}–{b}%"


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def _num(v) -> str:
    """Counts that are integers when no tie is involved (expected counts otherwise)."""
    return f"{v:,.0f}" if abs(v - round(v)) < 1e-9 else f"{v:,.1f}"


def _gap_line(d: pd.Series) -> str:
    return ", ".join(f"{c}: {v:+.1f}" for c, v in d.items())


def _span(v: pd.Series, d: int = 1, sign: bool = True) -> str:
    fmt = (lambda x: f"{x:+.{d}f}") if sign else (lambda x: f"{x:.{d}f}")
    a, b = fmt(v.min()), fmt(v.max())
    return a if a == b else f"{a} to {b}"


def _model_tie_sentence(tm: pd.DataFrame) -> str:
    split = tm[tm.split] if len(tm) else tm
    if not len(split):
        return "Model scores do not split a tie at any reported cut, so model overlaps are exact."
    where = "; ".join(f"cutoff {r.cutoff} {r.k_name}: {r.taken_from_block} of {r.tie_block} tied segments fit"
                      for r in split.itertuples())
    return (f"Model scores tie rarely; a model tie is split at {len(split)} reported cut(s) ({where}), where the model "
            "overlap is the expected value; it differs from a plain overlap by less than 1/k.")


def write_report(meta: dict, cov: pd.DataFrame, cap: pd.DataFrame, rep: pd.DataFrame, ovl: pd.DataFrame,
                 within: pd.DataFrame, pers: pd.DataFrame, pers_list: pd.DataFrame, new_list: pd.DataFrame,
                 cal: pd.DataFrame, ties: pd.DataFrame, gaps: pd.DataFrame) -> str:
    n = meta["segments"]
    net = meta["network_release"].split(" (")[0]
    L = [
        "# Historical blackspot rankings: retrospective backtests (research only)", "",
        f"*Generated by `ml/experiments/historical_rankings.py` on {meta['generated_utc'][:10]}. Frozen spec "
        f"`{meta['spec_sha256'][:12]}…` ({meta['selected_model']}). Not part of the v2 release, contract or frontend.*", "",
        "> **Read this first.**",
        "> - **Retrospective, not prospective.** The 2019–2023 rankings refit the v2 model *specification* at each "
        "cutoff using only data up to that cutoff. The specification itself (LightGBM, its hyperparameters, the 45 "
        "features) was chosen in 2026 on development folds whose targets run to 2023. No one could have produced "
        "these rankings at the time.",
        "> - **The holdout is not untouched here.** The 2024–2025 target of cutoff 2023 is the final holdout, "
        "already examined in v2; cutoff 2022's 2023–2024 target overlaps it. Cutoffs 2019–2021 are the "
        "development folds the specification was selected on.",
        f"> - **One road network for every period.** Segments, road classes and junctions come from the {net} "
        "snapshot. Roads opened after a period appear in it with no history; this is not a reconstruction of the "
        "historical network.",
        f"> - **Incomplete period omitted.** Cutoff 2024 (target 2025–2026) is not ranked: the data end in "
        f"{LAST_YEAR}. Cutoff 2025 is the production forecast for 2026–2027, whose outcomes are unknown.",
        "> - **Correction (2026-10-19).** An earlier version of this report computed recorded-count overlaps from "
        "ranks that broke ties by segment_id, which overstated them (e.g. top-1% overlap between consecutive "
        "periods). All overlaps and persistence counts are now tie-aware (section 4).", "",
        "## How to read the numbers", "",
        "1. **Predicted KSI and the model ranking** (`predicted_adj_ksi`, `predicted_rank`): model output. The "
        "expected adjusted KSI casualties on a segment in the forecast period (a burden, not a risk rate), and the "
        "national rank by it. Model scores are continuous, so ties at a reported cut are rare (`tie_blocks.csv`) "
        "and are handled the same way as ties in recorded counts.",
        "2. **Recorded KSI and rankings of recorded counts** (`observed_*`): STATS19 counts for the history or "
        "target window, never model output, and ranks of those counts. Counts tie heavily: most segments are at "
        "zero, and many share a positive value such as 1.0 adjusted KSI. The stored `observed_*_rank` columns "
        "order a tie by segment_id only, which carries no information.",
        "3. **Capture and overlap answer different questions.** *Capture* (section 3) is one period's recorded "
        "target KSI that falls in a ranking's top k%: how well a ranking concentrates the harm that followed. "
        "*Overlap* (sections 4–5) is the share of one ranking's top-k set that is also in another's: agreement or "
        "persistence, not accuracy. Both are tie-aware. Where the k-th place falls inside a tie, the tied segments "
        "share the remaining places equally: capture counts them pro rata, and overlap is the expected overlap when "
        "each ranking's ties are broken independently at random (`topk_inclusion`, exact, no simulation).", "",
        "## 1. Periods", "",
    ]
    per = cov[["cutoff", "ranking_kind", "fold_role", "train_feature_period", "train_target_period",
               "history_period", "forecast_period", "target_observed"]].copy()
    L += [_md(per), "",
          "Fold convention (`features.Fold`): the model is fitted on features c−4..c−2 against the target c−1..c, "
          "then applied to the history window c−2..c to rank segments for c+1..c+2. No training target reaches "
          "beyond its cutoff. The earliest cutoff is "
          f"{EARLIEST_CUTOFF}, the first whose training features start in {FIRST_YEAR}.", "",
          "## 2. Coverage and validation checks", ""]
    c2 = cov[["cutoff", "segments", "segments_with_history_collision", "history_adj_ksi", "training_target_adj_ksi",
              "predicted_adj_ksi_total", "observed_target_adj_ksi", "national_target_adj_ksi",
              "share_of_national_target", "segments_with_target_ksi"]].copy()
    for col in ("history_adj_ksi", "training_target_adj_ksi", "predicted_adj_ksi_total", "observed_target_adj_ksi",
                "national_target_adj_ksi"):
        c2[col] = c2[col].map(lambda v: "—" if pd.isna(v) else f"{v:,.0f}")
    c2["share_of_national_target"] = c2["share_of_national_target"].map(lambda v: "—" if pd.isna(v) else f"{100*v:.1f}%")
    for col in ("segments", "segments_with_history_collision", "segments_with_target_ksi"):
        c2[col] = c2[col].map(lambda v: "—" if pd.isna(v) else f"{int(v):,}")
    L += [f"Every cutoff ranks the same {n:,} scored segments (OS road classes M, A, B, C, U, N).", "", _md(c2), "",
          "Validation checks (all must pass; values in `historical_rankings_meta.json`):", ""]
    for chk in meta["checks"]:
        L.append(f"- **{'PASS' if chk['pass'] else 'FAIL'}** {chk['name']}: {chk['detail']}")
    if len(rep):
        L += ["", "Reproduction of the archived fold metrics (same code path, same frozen parameters):", "",
              _md(rep.assign(max_abs_diff=rep.max_abs_diff.map(lambda v: f"{v:.1e}")))]
    L += ["", "## 3. Capture of recorded target-period KSI", "",
          "Share of each target period's recorded adjusted KSI (on the scored network) that falls in the top 1%, "
          "5% and 10% of segments by each ranking. Ties at the cut count pro rata (`evaluation.capture_at`). The "
          "recorded-target ranking is the ceiling: it ranks by the outcome itself.", ""]
    cc = cap[cap.population == "all"].copy()
    for f in TOPK_FRACS:
        cc[f"top{int(f*100)}%"] = cc[f"capture_top{int(f*100)}"].map(lambda v: _pct(v))
    L += [_md(cc[["cutoff", "forecast_period", "ranking", "ranking_kind"] + [f"top{int(f*100)}%" for f in TOPK_FRACS]]), ""]
    pos = cov.dropna(subset=["segments_with_target_ksi"])
    if len(pos):
        share = pos.segments_with_target_ksi / pos.segments
        L += [f"Only {pos.segments_with_target_ksi.min():,.0f}–{pos.segments_with_target_ksi.max():,.0f} segments "
              f"({100*share.min():.1f}–{100*share.max():.1f}%) recorded any KSI in a target period, so the ceiling "
              "reaches 100% by the top 5%; the 1% column is the informative one.", ""]
    L += ["**Model versus the better of the two count rankings** (points of recorded target KSI; "
          "`gap_decomposition.csv`, `capture.csv`):", ""]
    g = gaps.set_index(["top", "cutoff"]) if len(gaps) else None
    if g is not None and "top1pct" in g.index.get_level_values(0):
        g1, g10 = g.loc["top1pct"], g.loc["top10pct"]
        L += [f"- **Whole network, top 1%:** {_gap_line(g1.gap)}. This is a refinement among segments with "
              f"recorded history: segments without any add {_span(g1.gap_from_no_history_segments, 2, False)} points "
              "to the model's top-1% capture.",
              f"- **Whole network, top 10%:** {_gap_line(g10.gap)}. All of it comes from segments without recorded "
              f"history, which count rankings cannot order (they tie at zero): those segments add "
              f"{_span(g10.gap_from_no_history_segments)} points. Among segments with recorded history the model "
              f"captures {_span(-g10.gap_from_history_segments, 1, False)} points *less* than the count ranking at "
              "that cut, because it gives some of its top-10% places to roads with no recorded crashes."]
    hp = cap[cap.population == "hist1"].pivot_table(index="cutoff", columns="ranking", values=["capture_top1", "capture_top5", "capture_top10"])
    if len(hp):
        def hgap(col):
            m = hp[col]
            return m["model"] - m[[BASELINES["hist_adj_ksi"], BASELINES["hist_collisions"]]].max(axis=1)
        L += [f"- **Segments with recorded history only** (`hist1`, its own top k%): top 1% {_gap_line(hgap('capture_top1'))}; "
              f"top 5% {_gap_line(hgap('capture_top5'))}; top 10% {_gap_line(hgap('capture_top10'))}."]
    L += ["", "So the model's advantage over recorded counts comes mainly from ranking roads with no recorded "
          "crashes. Among roads with crash history its gain is small, and at their very top (the `hist1` top 1%) it "
          "is about zero: crash history dominates, as in the v2 evaluation.", ""]
    ch = cap[cap.population == "hist1"].copy()
    if len(ch):
        for f in TOPK_FRACS:
            ch[f"top{int(f*100)}%"] = ch[f"capture_top{int(f*100)}"].map(lambda v: _pct(v))
        L += ["Capture within segments with at least one recorded collision in the history window (`hist1`):", "",
              _md(ch[["cutoff", "ranking"] + [f"top{int(f*100)}%" for f in TOPK_FRACS]]), ""]

    t1 = ties[(ties.ranking == "recorded_target") & (ties.k_name == "top1pct")] if len(ties) else ties
    tm = ties[ties.ranking == "model"] if len(ties) else ties
    L += ["## 4. Ties, and agreement with rankings of recorded counts", ""]
    if len(t1):
        L += [f"Recorded counts tie at positive values as well as at zero. At the top-1% cut the recorded-target "
              f"ranking falls inside a block of {t1.tie_block.min():,}–{t1.tie_block.max():,} segments sharing the "
              f"same value ({', '.join(sorted({f'{v:g}' for v in t1.value_at_cut}))} adjusted KSI), of which only "
              f"{t1.taken_from_block.min():,}–{t1.taken_from_block.max():,} fit in the top 1%. Which of them are "
              "\"in\" is undetermined, so every overlap below is the expected overlap under random tie-breaking. "
              + _model_tie_sentence(tm) +
              " Values are left blank (—) where part of a top-k set would be drawn from the block of zero counts, "
              "which says nothing about agreement (`tie_blocks.csv`).", ""]
    L += ["Top-k overlap within each cutoff: the model ranking versus the ranking by recorded history KSI (what a "
          "count-only method would list), and both versus the recorded target ranking.", ""]
    w = within.copy()
    show_w = ["cutoff", "k_name", "k", "model_vs_history_count_overlap"]
    w["model_vs_history_count_overlap"] = [
        "—" if z > 0 else f"{100*v:.0f}%" for v, z in zip(w.model_vs_history_count_overlap, w.history_count_share_from_zero_tie)]
    if "model_vs_recorded_target_overlap" in w:
        zt = w.recorded_target_share_from_zero_tie.fillna(1) > 0
        zh = w.history_count_share_from_zero_tie > 0
        w["model_vs_recorded_target_overlap"] = ["—" if z else f"{100*v:.0f}%" for v, z in zip(w.model_vs_recorded_target_overlap, zt)]
        w["history_count_vs_recorded_target_overlap"] = [
            "—" if (a or b) else f"{100*v:.0f}%" for v, a, b in zip(w.history_count_vs_recorded_target_overlap, zt, zh)]
        show_w += ["model_vs_recorded_target_overlap", "history_count_vs_recorded_target_overlap"]
    L += [_md(w[show_w]), "", "## 5. Rank overlap between periods", "",
          "Share of the top-k set at cutoff a that is also in the top-k set at cutoff b, for the model ranking "
          "and for the recorded target ranking (both tie-aware; see section 4). Consecutive cutoffs share two of "
          "three history years and one of two target years, so part of their overlap is mechanical; pairs with no "
          "shared years are the cleaner test of persistence. 2023→2025 skips the omitted 2024.", ""]
    if len(ovl):
        o = ovl.copy()
        o["model_overlap"] = o.model_overlap.map(lambda v: f"{100*v:.0f}%")
        keep = ["cutoff_a", "cutoff_b", "history_years_shared", "target_years_shared", "k_name", "model_overlap"]
        if "recorded_target_overlap" in o:
            o["recorded_target_overlap"] = [
                "—" if (pd.isna(v) or z > 0) else f"{100*v:.0f}%"
                for v, z in zip(o.recorded_target_overlap, o.recorded_share_from_zero_tie.fillna(1))]
            keep.append("recorded_target_overlap")
        o["model_spearman_all"] = o.get("model_spearman_all", pd.Series(np.nan, index=o.index)).map(
            lambda v: "" if pd.isna(v) else f"{v:.3f}")
        keep.append("model_spearman_all")
        L += [_md(o[keep]), "", "Spearman correlation is over all segments' predicted scores (one value per pair).", ""]
        valid = ovl.dropna(subset=["recorded_target_overlap"]) if "recorded_target_overlap" in ovl else ovl.iloc[0:0]
        valid = valid[valid.recorded_share_from_zero_tie == 0] if len(valid) else valid
        con = valid[(valid.cutoff_b - valid.cutoff_a == 1) & (valid.k_name == "top1pct")]
        dis = valid[(valid.history_years_shared == 0) & (valid.target_years_shared == 0) & (valid.k_name == "top1pct")]
        if len(con) and len(dis):
            pr = ", ".join(f"{a}→{b}" for a, b in zip(dis.cutoff_a, dis.cutoff_b))
            L += [f"Top 1%: between consecutive cutoffs {_range(con.model_overlap.min(), con.model_overlap.max())} of the "
                  f"model's set recurs, against {_range(con.recorded_target_overlap.min(), con.recorded_target_overlap.max())} "
                  f"of the recorded-target set. Where neither the history nor the target years overlap ({pr}): "
                  f"{_range(dis.model_overlap.min(), dis.model_overlap.max())} against "
                  f"{_range(dis.recorded_target_overlap.min(), dis.recorded_target_overlap.max())}.", "",
                  "The model ranking is much more stable than rankings of two-year recorded counts. The two are not "
                  "like-for-like: the model ranks from three years of history plus road attributes, while each recorded "
                  "ranking is a single two-year window of small, noisy counts. Stability is not accuracy, and this does "
                  "not show which ranking is right where they disagree.", ""]
    else:
        L += ["Only one cutoff is available.", ""]
    pk = tm[tm.k_name.isin(["top1000", "top1pct"]) & tm.split] if len(tm) else tm
    L += ["## 6. Persistent versus newly emerging high-ranked segments", "",
          "Counts use the model ranking. " + ("No model tie splits the top-1,000 or top-1% cut, so they are exact."
                                              if not len(pk) else "A model tie splits one of these cuts, so they are "
                                              "expected counts."), ""]
    pz = pers.copy()
    for col in pz.columns:
        if col not in ("k_name", "k", "backtest_cutoffs"):
            pz[col] = pz[col].map(_num)
    L += [_md(pz), "",
          "- *in_every_backtest*: in the predicted top-k at every backtest cutoff; *…_and_production*: also in the "
          "2026–2027 production top-k.",
          "- *production_never_in_a_backtest*: in the production top-k but in none of the 2019–2023 backtest top-k "
          "sets (newly emerging).",
          "- *entered_c*: in the top-k at cutoff c but not at the previous cutoff.", ""]
    show = ["segment_id", "location", "road_class"] + [f"rank_{c}" for c in CUTOFFS]
    if len(pers_list):
        L += [f"Top 15 of the {len(pers_list):,} segments in the predicted top 1,000 at every cutoff, by production "
              "rank (full list: `persistent_top1000.csv`):", "", _md(pers_list[[c for c in show if c in pers_list]].head(15)), ""]
    if len(new_list):
        sh = ["segment_id", "location", "road_class", f"rank_{FORECAST_CUTOFF}", "best_backtest_rank",
              "history_adj_ksi_2023_2025", "single_event_flag"]
        L += [f"Top 15 of the {len(new_list):,} segments in the production top 1,000 that were in no backtest top "
              "1,000 (full list: `emerging_top1000.csv`). A single-event flag means one collision dominates the "
              "2023–2025 history:", "", _md(new_list[[c for c in sh if c in new_list]].head(15)), ""]
    L += ["## 7. Calibration", "",
          "Σpredicted / Σrecorded on the scored network, and the range of recorded/predicted across deciles of "
          "the prediction (`calibration_historical.csv`). Totals move with national shocks (COVID); ranks are "
          "the product, and they are less sensitive.", ""]
    cs = cal.groupby("cutoff").agg(lowest_decile_obs_over_pred=("obs_over_pred", "first"),
                                   top_decile_obs_over_pred=("obs_over_pred", "last"),
                                   min_obs_over_pred=("obs_over_pred", "min"),
                                   max_obs_over_pred=("obs_over_pred", "max")).reset_index()
    so = cap[(cap.population == "all") & (cap.ranking == "model")][["cutoff", "sum_pred_over_obs"]]
    cs = so.merge(cs, on="cutoff")
    for col in cs.columns[1:]:
        cs[col] = cs[col].map(lambda v: f"{v:.2f}")
    L += [_md(cs), "",
          "## 8. Limitations", "",
          "- **Specification chosen with hindsight.** Model class, hyperparameters (tuned on the 2015–17 → "
          "2018–19 training pair) and the feature set were fixed in 2026 using development targets up to 2023, "
          "and the junction feature was redefined after the 2024–2025 coding change was seen. Backtest capture "
          "is therefore an optimistic estimate of what a forecaster at each cutoff could have achieved.",
          "- **Examined holdout.** 2024–2025 outcomes were examined in v2 and are the production model's "
          "training target. Nothing here is an independent test; the next one is 2026–2027, when DfT publishes it.",
          f"- **Network anachronism.** One {net} snapshot is used for every period: roads opened later appear with "
          "empty histories; reclassified roads carry their 2026 class. Fewer than 0.5% of crashes fail to match the "
          "network (`data_quality.md`).",
          "- **Data vintage.** STATS19 2015–2025 as published in 2026, including DfT's severity adjustment and "
          "revisions to past years, not the data available at each cutoff.",
          "- **Ties.** Recorded counts tie at zero and at positive values. Capture counts a tie at the cut pro rata; "
          "overlaps and persistence counts are expected values under random tie-breaking; values are blank where a "
          "top-k set would be filled from the zero block. The stored `observed_*_rank` columns order ties by "
          "segment_id for convenience only and must not be used to build top-k sets.",
          "- **Two-year targets are noisy.** Recorded KSI on one ~500 m segment over two years is a small count; "
          "low overlap between recorded target rankings is expected even for a stable underlying risk.", "",
          "## 9. Files", "",
          f"- `ml/outputs/history/historical_rankings.parquet`: {meta['rows']:,} rows, one per segment and "
          f"cutoff ({meta['result_bytes']/2**20:.0f} MB, zstd). Columns are described in "
          "`historical_rankings_meta.json` (`columns`).",
          "- `ml/outputs/history/*.csv`: the tables above (`periods_coverage.csv`, `capture.csv`, "
          "`gap_decomposition.csv`, `reproduction.csv`, `tie_blocks.csv`, `overlap_within_cutoff.csv`, "
          "`overlap_between_periods.csv`, `persistence.csv`, `persistent_top1000.csv`, `emerging_top1000.csv`, "
          "`calibration_historical.csv`).",
          "- `ml/outputs/history/checkpoints/`: per-cutoff predictions and metrics (resume with the same command).",
          f"- Runtime {meta['runtime']['total_minutes']:.1f} min for the invocation that wrote this report "
          "(cutoffs with an existing checkpoint are not recomputed); peak memory "
          f"{json.dumps(meta['runtime']['memory'])}. Compute per cutoff (fit + checks, or production check): "
          + ", ".join(f"{c} {v.get('seconds', 0):.0f} s" for c, v in meta["cutoffs"].items()) + ".", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    from blackspot.steps import _context, _load_frozen
    ap = argparse.ArgumentParser(description="Historical blackspot rankings (retrospective backtests).")
    ap.add_argument("--cutoffs", nargs="*", type=int, default=list(CUTOFFS))
    ap.add_argument("--fresh", action="store_true", help="ignore checkpoints")
    ap.add_argument("--report-only", action="store_true", help="only rebuild the result, tables and report")
    args = ap.parse_args(argv)
    for c in args.cutoffs:
        ranking_kind(c)                                   # refuse 2024, < 2019 and > 2025 before any work
    setup_logging()
    t_start = time.time()
    spec = _load_frozen()
    network = network_release()
    _guard(OUT).mkdir(parents=True, exist_ok=True)
    _guard(CKPT).mkdir(parents=True, exist_ok=True)
    ctx = _context(with_aadf=False)
    ids = ctx.seg.segment_id.values
    key = _seg_key(ids)
    tie = segment_id_order(ids)
    log.info("context ready: %d segments, %.0fs", len(ids), time.time() - t_start)

    # 1. predictions per cutoff (checkpointed)
    if not args.report_only:
        for c in args.cutoffs:
            if not args.fresh and load_checkpoint(c, key) is not None:
                log.info("cutoff %s: checkpoint exists, skipping", c)
                continue
            t0 = time.time()
            if ranking_kind(c) == RETRO:
                res = backtest_cutoff(ctx, c, spec)
                t_fit = time.time() - t0
                pred = res["predictions"][spec["selected_model"]]
                y_obs = observed(ctx, c)[1]
                if not np.allclose(res["yte"], y_obs, rtol=0, atol=1e-9):
                    raise RuntimeError("run_fold target differs from the recorded target window")
                inv = future_invariance(ctx, c, res["Xte"])
                info = {"cutoff": c, "fold": res["fold"], "model_source": "refitted on Fold(c) training pair",
                        "run_fold_seconds": round(t_fit, 1), "invariance_check_seconds": round(time.time() - t0 - t_fit, 1),
                        "future_invariance": inv,
                        "training_target_adj_ksi": float(window_sums(ctx.ac, len(ids), Fold(c).train_y, [PRIMARY]).sum().iloc[0])}
                metrics = res["metrics"]
                del res
            else:
                pred, info = production_cutoff(ctx, spec)
                info = {"cutoff": c, "model_source": info["source"], **info,
                        "training_target_adj_ksi": float(window_sums(ctx.ac, len(ids), Fold(c).train_y, [PRIMARY]).sum().iloc[0])}
                metrics = None
            info.update({"segment_key": key, "seconds": round(time.time() - t0, 1), "memory": peak_memory_mb()})
            save_checkpoint(c, pred, info, metrics)
            log.info("cutoff %s done in %.1f min (%s)", c, (time.time() - t0) / 60, info["memory"])

    # 2. assemble the long table and the in-memory arrays for the summaries
    avail = [c for c in CUTOFFS if (CKPT / f"cutoff_{c}.npz").exists()]
    R, cov_rows, cap_rows, cal_rows, infos = {}, [], [], [], {}
    with atomic_path(_guard(RESULT)) as tmp:
        writer = pq.ParquetWriter(tmp, SCHEMA, compression="zstd")
        try:
            for c in avail:
                pred, info, metrics = load_checkpoint(c, key)
                infos[c] = info
                hist, y = observed(ctx, c)
                writer.write_table(ranking_table(c, ids, tie, pred, hist, y, spec["sha256"], network),
                                   row_group_size=500_000)
                p = periods(c)
                nat = national_ksi(ctx.coll, Fold(c).test_y) if p["target_observed"] else np.nan
                R[c] = {"pred": pred, "pred_rank": national_ranks(pred, tie), "y": y,
                        "h": hist.adj_ksi_cas.values, "hc": hist.n_coll.values}
                cov_rows.append({**p, "fold_role": fold_role(c), "segments": len(ids),
                                 "segments_with_history_collision": int((hist.n_coll.values > 0).sum()),
                                 "history_adj_ksi": float(hist.adj_ksi_cas.sum()),
                                 "training_target_adj_ksi": info.get("training_target_adj_ksi"),
                                 "predicted_adj_ksi_total": float(pred.sum()),
                                 "observed_target_adj_ksi": np.nan if y is None else float(y.sum()),
                                 "national_target_adj_ksi": nat,
                                 "share_of_national_target": np.nan if y is None else float(y.sum() / nat),
                                 "segments_with_target_ksi": np.nan if y is None else int((y > 0).sum())})
                if metrics is not None:
                    names = {spec["selected_model"]: "model", **BASELINES}
                    for _, r in metrics.iterrows():
                        cap_rows.append({"cutoff": c, "forecast_period": p["forecast_period"], "population": r.population,
                                         "ranking": names[r.model], "model": r.model,
                                         "ranking_kind": RETRO if r.model == spec["selected_model"] else OBSERVED,
                                         **{k: r[k] for k in ["capture_top1", "capture_top5", "capture_top10", "capture_top20",
                                                              "poisson_deviance", "sum_pred_over_obs"]}})
                    for pop, mask in (("all", np.ones(len(ids), bool)), ("hist1", hist.n_coll.values > 0)):
                        cap_rows.append({"cutoff": c, "forecast_period": p["forecast_period"], "population": pop,
                                         "ranking": "recorded target (ceiling)", "model": "observed_target",
                                         "ranking_kind": OBSERVED,
                                         **{f"capture_top{int(f*100)}": capture_at(y[mask], y[mask], f) for f in (0.01, 0.05, 0.10, 0.20)},
                                         "poisson_deviance": np.nan, "sum_pred_over_obs": np.nan})
                    cal_rows.append(calibration_table(y, pred).assign(cutoff=c))
        finally:
            writer.close()
    cov, cap = pd.DataFrame(cov_rows), pd.DataFrame(cap_rows, columns=CAP_COLS)
    cal = pd.concat(cal_rows, ignore_index=True) if cal_rows else pd.DataFrame(columns=["cutoff", "obs_over_pred"])

    # 3. reproduction of the archived fold metrics
    roll = pd.read_csv(REPORTS / "rolling_origin_results.csv")
    comp = pd.read_csv(REPORTS / "model_comparison.csv")
    arch = pd.concat([roll[roll.study == "main"], comp[comp.study.isin(["holdout", "posthoc"])]], ignore_index=True)
    arch = arch[(arch.population == "all") & (arch.target == PRIMARY)]
    rep_rows = []
    mcols = ["poisson_deviance", "sum_pred_over_obs", "capture_top1", "capture_top5", "capture_top10", "capture_top20"]
    for _, r in cap[(cap.population == "all") & (cap.model != "observed_target")].iterrows():
        a = arch[(arch.cutoff == r.cutoff) & (arch.model == r.model)]
        if len(a) != 1:
            continue
        d = max(abs(float(r[m]) - float(a.iloc[0][m])) for m in mcols)
        rep_rows.append({"cutoff": r.cutoff, "archived_study": a.iloc[0].study, "model": r.model,
                         "metrics_compared": len(mcols), "max_abs_diff": d})
    rep = pd.DataFrame(rep_rows, columns=REP_COLS)

    # 4. tie-aware overlaps, gap decomposition, persistence
    inc = _Inclusion(R)
    ties = tie_table(R)
    ovl = overlap_table(R, inc) if len(R) > 1 else pd.DataFrame()
    within = within_cutoff_table(R, inc)
    gaps = gap_decomposition(R)
    full = pd.read_parquet(PRODUCTION_SCORES, columns=["segment_id", "location", "road_class", "single_event_flag",
                                                       "n_ksi_casualties_adjusted"]).set_index("segment_id").reindex(ids)
    info_cols = full.rename(columns={"n_ksi_casualties_adjusted": "history_adj_ksi_2023_2025"}).round(
        {"history_adj_ksi_2023_2025": 2})
    pers, pers_list, new_list = persistence(R, ids, info_cols, inc)

    # 5. checks
    checks = []
    for c in avail:
        p = periods(c)
        f = Fold(c)
        checks.append({"name": f"cutoff {c} periods follow features.Fold", "pass": p["history_period"] == str(f.test_x)
                       and p["forecast_period"] == str(f.test_y) and f.train_y.end == c,
                       "detail": f"train {p['train_feature_period']} → {p['train_target_period']}, applied "
                                 f"{p['history_period']} → {p['forecast_period']}; training target ends at the cutoff"})
        inv = infos[c].get("future_invariance")
        if inv:
            checks.append({"name": f"cutoff {c} unaffected by later collisions",
                           "pass": inv["training_frame_identical"] and inv["prediction_features_identical"],
                           "detail": f"dropping all {inv['collisions_after_cutoff_dropped']:,} collisions after {c} leaves "
                                     "the training frame and the prediction features bit-identical"})
    if FORECAST_CUTOFF in infos:
        i = infos[FORECAST_CUTOFF]
        checks.append({"name": "cutoff 2025 reproduces the released scores without refitting",
                       "pass": i["max_abs_diff_model_vs_stored"] == 0.0 and i["ranks_identical_to_stored"],
                       "detail": f"saved production model vs stored blackspot_score: max |diff| = "
                                 f"{i['max_abs_diff_model_vs_stored']}; ranks identical: {i['ranks_identical_to_stored']}"})
    if len(rep):
        checks.append({"name": "backtests reproduce the archived development, post-hoc and holdout metrics",
                       "pass": bool(rep.max_abs_diff.max() < 1e-9),
                       "detail": f"{len(rep)} model×cutoff rows, {rep.metrics_compared.sum()} metrics, max |diff| = "
                                 f"{rep.max_abs_diff.max():.1e}"})
    checks.append({"name": "backtests never use the production model", "pass": all(
        infos[c]["model_source"].startswith("refitted") for c in avail if c in BACKTEST_CUTOFFS),
        "detail": "every 2019-2023 prediction comes from a model refitted on its own Fold(c) training pair"})
    sums_ok = all(abs(v.sum() - k) < 1e-6 for (c, key, k), v in inc.memo.items())
    mt = ties[ties.ranking == "model"] if len(ties) else ties
    msplit = mt[mt.split] if len(mt) else mt
    checks.append({"name": "top-k statistics are tie-aware", "pass": sums_ok,
                   "detail": f"{len(inc.memo)} inclusion vectors each sum to k; recorded-count overlaps are expected "
                             "values under random tie-breaking, not segment_id order; model scores split a tie at "
                             f"{len(msplit)} of {len(mt)} reported cuts (largest model block {int(mt.tie_block.max()) if len(mt) else 1})"})
    if len(gaps):
        gm = gaps.merge(cap[(cap.population == "all") & (cap.model == spec["selected_model"])][
            ["cutoff", "capture_top1", "capture_top5", "capture_top10"]], on="cutoff")
        dmax = max(abs(r.model_capture - r[f"capture_{r.top.replace('pct', '')}"]) for _, r in gm.iterrows())
        checks.append({"name": "gap decomposition agrees with the capture metric", "pass": dmax < 1e-9,
                       "detail": f"model capture from inclusion probabilities vs capture.csv: max |diff| = {dmax:.1e}; "
                                 "history and no-history parts add up to the total"})
    checks.append({"name": "unobserved target stays null", "pass": all(
        (cv["observed_target_adj_ksi"] is not None and not np.isnan(cv["observed_target_adj_ksi"])) == cv["target_observed"]
        for cv in cov_rows), "detail": "observed_target_* is null exactly where the forecast period is not in the data"})

    # 6. write
    for name, df in [("periods_coverage.csv", cov), ("capture.csv", cap), ("reproduction.csv", rep),
                     ("overlap_between_periods.csv", ovl), ("overlap_within_cutoff.csv", within),
                     ("persistence.csv", pers), ("persistent_top1000.csv", pers_list),
                     ("emerging_top1000.csv", new_list), ("calibration_historical.csv", cal),
                     ("tie_blocks.csv", ties), ("gap_decomposition.csv", gaps)]:
        write_csv(df, _guard(OUT / name))
    meta = {"generated_utc": pd.Timestamp.now("UTC").isoformat(timespec="seconds"), "spec_sha256": spec["sha256"],
            "selected_model": spec["selected_model"], "lgbm_params": spec["lgbm_params"], "network_release": network,
            "segments": int(len(ids)), "rows": int(len(ids) * len(avail)), "cutoffs": {
                str(c): {**periods(c), "fold_role": fold_role(c), "caveat": caveat(c, network),
                         **{k: v for k, v in infos[c].items() if k not in ("segment_key",)}} for c in avail},
            "omitted_cutoffs": {str(c): r for c, r in OMITTED.items()}, "earliest_cutoff": EARLIEST_CUTOFF,
            "ranking_kinds": {RETRO: "model ranking refitted at the cutoff (2019-2023)",
                              PRODUCTION: "the released v2.0 ranking (2025 cutoff)",
                              OBSERVED: "ranking of recorded counts: observed_target_rank, observed_history_rank, "
                                        "and the count baselines in capture.csv"},
            "tie_handling": "capture: tie block at the cut counted pro rata; overlaps and persistence: expected "
                            "values under independent random tie-breaking (topk_inclusion); stored observed_*_rank "
                            "columns order ties by segment_id for convenience only",
            "columns": DICTIONARY, "checks": checks, "result_bytes": RESULT.stat().st_size,
            "runtime": {"total_minutes": round((time.time() - t_start) / 60, 2), "memory": peak_memory_mb()}}
    write_json(meta, _guard(META))
    write_text(write_report(meta, cov, cap, rep, ovl, within, pers, pers_list, new_list, cal, ties, gaps),
               _guard(REPORT))
    failed = [c["name"] for c in checks if not c["pass"]]
    log.info("historical rankings: %d cutoffs, %d rows, %.1f MB, %.1f min; checks failed: %s", len(avail),
             meta["rows"], meta["result_bytes"] / 2**20, meta["runtime"]["total_minutes"], failed or "none")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
