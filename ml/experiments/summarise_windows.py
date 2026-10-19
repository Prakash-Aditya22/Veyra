"""Tables for historical_window_analysis.md (generated; do not hand-edit numbers).

    .venv/Scripts/python ml/experiments/summarise_windows.py

Decay half-life rule (fixed before results were seen): choose h with the lowest mean
Poisson deviance (population all) on development cutoffs 2019 and 2020; 2021 is then a
check that played no part in the choice. The 2022/2023 cutoffs are exploratory only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import REPORTS  # noqa: E402
from blackspot.io_utils import write_json, write_text  # noqa: E402

DEV, SELECT, CHECK = [2019, 2020, 2021], [2019, 2020], 2021
MAIN = ["REF_recent3_single", "A_all_single", "A_recent3_stacked", "B_nocovid3_single", "B_recent3_noncovidpair",
        "B_nocovid3_noncovidpair", "C_recent2_single", "C_recent4_single", "C_recent5_single"]


def md(df, fmt="{:.4f}"):
    cols = list(df.columns)
    out = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(fmt.format(v) if isinstance(v, (float, np.floating)) and np.isfinite(v)
                                     else ("" if isinstance(v, float) else str(v)) for v in r) + " |")
    return "\n".join(out)


def main():
    R = pd.read_csv(REPORTS / "historical_window_results.csv")
    B = pd.read_csv(REPORTS / "historical_window_bootstrap.csv")
    D = pd.read_csv(REPORTS / "historical_window_design.csv")
    X = pd.read_csv(REPORTS / "historical_window_context.csv")
    parts, sel = [], {}

    # design table
    dd = D[D.feasible & D.cutoff.isin(DEV + [2022, 2023])][["cutoff", "strategy", "predictor_years_test",
                                                             "training_predictor_years", "training_target_windows"]]
    parts.append("## Design: years behind every fit\n\n" + md(dd))

    # decay selection
    a = R[(R.population == "all") & R.strategy.str.startswith("D_decay")]
    dev_sel = a[a.cutoff.isin(SELECT)].groupby("strategy").poisson_deviance.mean()
    best_decay = dev_sel.idxmin()
    sel["decay_selection_deviance_2019_2020"] = dev_sel.round(6).to_dict()
    sel["selected_decay_strategy"] = best_decay
    parts.append("## Decay half-life choice (rule: mean deviance on 2019-2020 only)\n\n" +
                 md(dev_sel.reset_index().rename(columns={"poisson_deviance": "mean_deviance_2019_2020"}), "{:.5f}") +
                 f"\n\nSelected: **{best_decay}**. Its 2021 result below is the out-of-selection check.")

    strategies = MAIN + [best_decay]
    allp = R[(R.population == "all") & R.strategy.isin(strategies + ["hist_collisions"])]
    for metric in ["poisson_deviance", "sum_pred_over_obs", "capture_top10", "capture_top20"]:
        t = allp.pivot_table(index="strategy", columns="cutoff", values=metric).reindex(
            strategies + ["hist_collisions"])
        parts.append(f"## {metric}, population all (1,827,550 segments), by cutoff\n\n"
                     "Columns 2019-2021: development. 2022-2023: exploratory (already-examined targets).\n\n"
                     + md(t.reset_index(), "{:.4f}"))
    # paired differences vs REF, dev folds
    pb = B[(B.pair_reference == "REF_recent3_single") & B.metric.isin(["dev", "c10", "c20"])
           & B.population.isin(["all", "hist0", "hist1", "numbered"])]
    pb = pb[pb.strategy.isin(strategies)]
    for pop in ["all", "hist0", "hist1", "numbered"]:
        q = pb[pb.population == pop].copy()
        q["diff [95% CI]"] = [f"{d:+.4f} [{lo:+.4f}, {hi:+.4f}]" if m == "dev" else f"{d:+.2f} [{lo:+.2f}, {hi:+.2f}]"
                              for d, lo, hi, m in zip(q.diff_vs_ref_mean, q.diff_ci_low, q.diff_ci_high, q.metric)]
        t = q.pivot_table(index=["strategy", "metric"], columns="cutoff", values="diff [95% CI]", aggfunc="first")
        parts.append(f"## Paired difference vs REF (strategy minus REF), population `{pop}`, block bootstrap\n\n"
                     "dev = Poisson deviance (negative is better); c10/c20 = capture points (positive is better).\n\n"
                     + md(t.reset_index()))
    # roads without recent history, by class, by region (dev mean over feasible folds)
    for pop_prefix, title in [("hist0", "segments with no collision in the last 3 years"),
                              ("class_", "road class"), ("region_", "region")]:
        q = R[R.population.str.startswith(pop_prefix) & R.strategy.isin(
            ["REF_recent3_single", "A_all_single", "B_nocovid3_noncovidpair", best_decay, "hist_collisions"])
              & R.cutoff.isin(DEV)]
        t = q.groupby(["population", "strategy"]).agg(capture_top10=("capture_top10", "mean"),
                                                      deviance=("poisson_deviance", "mean"),
                                                      share_national=("population_share_of_national_ksi", "mean"))
        parts.append(f"## By {title}: mean over development folds\n\n" + md(t.reset_index(), "{:.3f}"))
    # lift over counts
    lift = allp[allp.cutoff.isin(DEV)].pivot_table(index="strategy", values="capture_top10", aggfunc="mean")
    base = lift.loc["hist_collisions", "capture_top10"]
    lift["lift_over_counts_top10"] = lift.capture_top10 / base
    parts.append("## Lift over crash-count ranking (top 10%, mean of dev folds)\n\n" + md(lift.reset_index(), "{:.3f}"))
    parts.append("## COVID-era context (local data)\n\n" + md(X, "{:.3f}"))

    # simple dev summary per strategy on folds where the strategy and REF are both feasible
    rows = []
    for s in strategies:
        q = R[(R.population == "all") & (R.strategy == s) & R.cutoff.isin(DEV)]
        ref = R[(R.population == "all") & (R.strategy == "REF_recent3_single") & R.cutoff.isin(q.cutoff)]
        rows.append({"strategy": s, "dev_folds": ",".join(map(str, sorted(q.cutoff))),
                     "mean_deviance": q.poisson_deviance.mean(), "ref_mean_deviance_same_folds": ref.poisson_deviance.mean(),
                     "mean_capture_top10": q.capture_top10.mean(), "ref_capture_top10_same_folds": ref.capture_top10.mean(),
                     "mean_abs_calibration_error": (q.sum_pred_over_obs - 1).abs().mean(),
                     "ref_abs_calibration_error": (ref.sum_pred_over_obs - 1).abs().mean()})
    S = pd.DataFrame(rows)
    parts.insert(2, "## Development summary (folds where each strategy is feasible, REF on the same folds)\n\n" + md(S, "{:.4f}"))
    write_text("# Historical-window tables (generated by ml/experiments/summarise_windows.py)\n\n"
               + "\n\n".join(parts) + "\n", REPORTS / "historical_window_tables.md")
    sel["dev_summary"] = S.round(6).to_dict(orient="records")
    write_json(sel, REPORTS / "historical_window_selection.json")
    print(S.round(4).to_string())
    print(sel["selected_decay_strategy"])


if __name__ == "__main__":
    main()
