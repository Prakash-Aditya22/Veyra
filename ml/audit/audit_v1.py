"""Quantify the v1 blackspot defects from the committed v1 outputs.

Reads data/road_segments_ranked.csv (v1 output) and stats19_recent.csv (v1
extract). Writes ml/reports/audit_v1_evidence.json, which
ml/reports/preliminary_audit.md cites. Read-only with respect to v1 artefacts.

    .venv/Scripts/python ml/audit/audit_v1.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import BACKEND_DATA, LEGACY_CSV, REPORTS, SEED  # noqa: E402
from blackspot.evaluation import capture_at, capture_bounds_with_ties  # noqa: E402
from blackspot.io_utils import write_json  # noqa: E402

BUILD, FUTURE = [2019, 2020, 2021], [2022, 2023]
CLS = {1: "M", 2: "A(M)", 3: "A", 4: "B", 5: "C", 6: "U"}
FRACS = (0.01, 0.05, 0.10, 0.20)


def poisson_deviance(y, mu):
    mu = np.clip(mu, 1e-9, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(y > 0, y * np.log(y / mu), 0.0)
    return float(2 * np.mean(t - (y - mu)))


def main() -> None:
    ev: dict = {}
    seg = pd.read_csv(BACKEND_DATA / "road_segments_ranked.csv")
    # v1 built `seg` from a groupby on segment_id (sorted), then split by position.
    seg = seg.sort_values("segment_id").reset_index(drop=True)
    tr, te = train_test_split(np.arange(len(seg)), test_size=0.3, random_state=SEED)
    is_test = np.zeros(len(seg), bool); is_test[te] = True
    seg["v1_split"] = np.where(is_test, "test", "train")

    # ---- reproduce the published held-out capture to confirm the split reconstruction
    t = seg[is_test]
    ev["reconstructed_test_capture_model"] = {
        f"top{int(f*100)}": capture_at(t.blackspot_score.values, t.future_ksi.values, f, ties="first")
        for f in FRACS}

    # ---- A. in-sample scores shipped as forecasts
    out = {}
    for name, part in seg.groupby("v1_split"):
        y, mu = part.future_ksi.values, part.blackspot_score.values
        out[name] = {"n": int(len(part)),
                     "spearman_score_vs_future": float(pd.Series(mu).corr(pd.Series(y), method="spearman")),
                     "poisson_deviance": poisson_deviance(y, mu),
                     "capture_top20": capture_at(mu, y, 0.20, ties="first")}
    ev["in_sample_vs_held_out"] = out
    top = seg.nsmallest(500, "rank")
    ev["top500_share_train_segments"] = float((top.v1_split == "train").mean())
    ev["top100_share_train_segments"] = float((seg.nsmallest(100, "rank").v1_split == "train").mean())

    # ---- C. tie handling in the crash-count baseline (held-out set)
    ties = {}
    for col in ["n_crashes", "n_ksi"]:
        for f in FRACS:
            lo, hi, exp = capture_bounds_with_ties(t[col].values, t.future_ksi.values, f)
            ties[f"{col}_top{int(f*100)}"] = {
                "v1_reported_style(argsort)": capture_at(t[col].values, t.future_ksi.values, f, ties="first"),
                "worst_tiebreak": lo, "best_tiebreak": hi, "expected_random_tiebreak": exp}
    k = int(len(t) * 0.20)
    cut = np.sort(t.n_crashes.values)[::-1][k - 1]
    ties["n_crashes_top20_cutoff_value"] = int(cut)
    ties["n_segments_tied_at_cutoff"] = int((t.n_crashes.values == cut).sum())
    ties["share_test_segments_with_1_crash"] = float((t.n_crashes == 1).mean())
    lo, hi, exp = capture_bounds_with_ties(t.blackspot_score.values, t.future_ksi.values, 0.2)
    ties["model_top20_expected"] = exp
    ev["ties"] = ties

    # bootstrap the model-minus-count difference over *roads* (clusters), held-out only
    rng = np.random.default_rng(SEED)
    roads = t.road_id.unique()
    by_road = {r: g for r, g in t.groupby("road_id")}
    diffs = []
    for _ in range(300):
        samp = pd.concat([by_road[r] for r in rng.choice(roads, len(roads), replace=True)])
        a = capture_bounds_with_ties(samp.blackspot_score.values, samp.future_ksi.values, 0.2)[2]
        b = capture_bounds_with_ties(samp.n_crashes.values, samp.future_ksi.values, 0.2)[2]
        diffs.append(a - b)
    ev["model_minus_count_top20_road_cluster_bootstrap"] = {
        "mean": float(np.mean(diffs)), "ci95": [float(np.percentile(diffs, 2.5)),
                                                float(np.percentile(diffs, 97.5))],
        "share_negative": float(np.mean(np.array(diffs) < 0))}

    # ---- A/D. eligibility leakage and national coverage (collision grain: v1 extract has no casualty severity)
    df = pd.read_csv(LEGACY_CSV, usecols=["collision_index", "collision_year", "latitude", "longitude",
                                          "first_road_class", "first_road_number", "Accident_Severity",
                                          "number_of_casualties"], low_memory=False)
    df = df[df.collision_year.isin(BUILD + FUTURE)]
    df["ksi"] = (df.Accident_Severity != "Minor").astype(int)
    numbered = df.first_road_class.isin(CLS) & (df.first_road_number > 0) & df.latitude.notna()
    df["road_id"] = np.where(numbered, df.first_road_class.map(CLS).fillna("") +
                             df.first_road_number.fillna(0).astype(int).astype(str), "")
    all_cnt = df[numbered].road_id.value_counts()
    build_cnt = df[numbered & df.collision_year.isin(BUILD)].road_id.value_counts()
    eligible = set(all_cnt[all_cnt >= 60].index)
    eligible_build_only = set(build_cnt[build_cnt >= 60].index)
    ev["eligibility"] = {
        "roads_eligible_v1(2019-2023 counts)": len(eligible),
        "roads_eligible_if_build_only(2019-2021)": len(eligible_build_only),
        "roads_admitted_only_by_future_crashes": len(eligible - eligible_build_only),
        "roads_dropped_if_build_only": sorted(eligible - eligible_build_only)[:25],
    }
    fut = df[df.collision_year.isin(FUTURE)]
    nat_ksi = int(fut.ksi.sum())
    by_class = fut.groupby(fut.first_road_class.map(CLS).fillna("unknown")).ksi.sum()
    ev["coverage_2022_2023_ksi_collisions"] = {
        "national_ksi_collisions": nat_ksi,
        "by_first_road_class": {k: int(v) for k, v in by_class.items()},
        "share_on_numbered_roads": float(fut[numbered.loc[fut.index]].ksi.sum() / nat_ksi),
        "share_on_v1_eligible_roads": float(fut[fut.road_id.isin(eligible)].ksi.sum() / nat_ksi),
        "share_in_scored_segments(sum future_ksi in output)": float(seg.future_ksi.sum() / nat_ksi),
        "share_in_v1_test_segments": float(t.future_ksi.sum() / nat_ksi),
        "c_and_unclassified_share": float(by_class.get("C", 0) + by_class.get("U", 0)) / nat_ksi,
        "note": "collision grain: v1 target counts KSI collisions, not KSI casualties",
    }
    # casualties per KSI collision -- how far apart the two quantities are
    kc = fut[fut.ksi == 1]
    ev["casualties_per_ksi_collision_mean(all severities)"] = float(kc.number_of_casualties.mean())

    # ---- E. features that are identifiers / shortcuts
    ev["feature_notes"] = {
        "run_max": int(seg.segment_id.str.extract(r"_run(\d+)_")[0].astype(int).max()),
        "km_from_direction": "chainage measured from an arbitrary end of the MST diameter",
    }
    write_json(ev, REPORTS / "audit_v1_evidence.json")
    print(pd.Series({k: v for k, v in ev.items()}).to_string()[:6000])


if __name__ == "__main__":
    main()
