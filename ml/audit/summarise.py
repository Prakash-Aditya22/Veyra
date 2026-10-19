"""Summary tables from the raw run outputs.

    .venv/Scripts/python ml/audit/summarise.py

Reads  reports/rolling_origin_results.csv, rolling_origin_bootstrap.csv,
       reports/model_comparison.csv, model_comparison_bootstrap.csv, coverage files
Writes reports/ablation_results.csv     (ablation, every dev fold + mean, paired CIs vs lgbm)
       reports/summary_tables.md        (tables embedded in robustness.md / final_audit.md)
       reports/headline.json            (every number the README quotes, for the doc check)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import OUTPUTS, REPORTS  # noqa: E402
from blackspot.io_utils import write_csv, write_json, write_text  # noqa: E402

PRIMARY = "adj_ksi_cas"


def ci(b, model, metric, study=None, pop="all", cutoff=None, target=PRIMARY):
    d = b[(b.model == model) & (b.metric == metric) & (b.population == pop) & (b.target == target)
          & b.get("pair_reference", pd.Series(np.nan, index=b.index)).isna()]
    if study is not None:
        d = d[d.study == study]
    if cutoff is not None:
        d = d[d.cutoff == cutoff]
    return (float(d.ci_low.iloc[0]), float(d.ci_high.iloc[0])) if len(d) else (np.nan, np.nan)


def pair(b, a, ref, metric, study, pop="all", cutoff=None, target=PRIMARY):
    d = b[(b.model == a) & (b.get("pair_reference") == ref) & (b.metric == metric) & (b.population == pop)
          & (b.study == study) & (b.target == target)]
    if cutoff is not None:
        d = d[d.cutoff == cutoff]
    if not len(d):
        return None
    r = d.iloc[0]
    return {"diff": float(r.diff_vs_ref_mean), "lo": float(r.diff_ci_low), "hi": float(r.diff_ci_high)}


def md_table(df, floatfmt=3):
    cols = list(df.columns)
    out = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            cells.append(f"{v:.{floatfmt}f}" if isinstance(v, (float, np.floating)) and np.isfinite(v) else str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def main():
    R = pd.read_csv(REPORTS / "rolling_origin_results.csv")
    RB = pd.read_csv(REPORTS / "rolling_origin_bootstrap.csv")
    H = pd.read_csv(REPORTS / "model_comparison.csv")
    HB = pd.read_csv(REPORTS / "model_comparison_bootstrap.csv")
    spec = json.loads((OUTPUTS / "frozen_spec.json").read_text())
    sel = spec["selected_model"]
    head: dict = {"selected_model": sel, "spec_sha256": spec["sha256"][:12]}
    parts = []

    # ---------------- ablation
    ab = R[(R.study == "ablation") & (R.population == "all")]
    rows = []
    for (c, m), g in ab.groupby(["cutoff", "model"]):
        r = g.iloc[0]
        p = pair(RB, m, "lgbm", "dev", "ablation", cutoff=c) if m != "lgbm" else None
        p10 = pair(RB, m, "lgbm", "c10", "ablation", cutoff=c) if m != "lgbm" else None
        rows.append({"cutoff": c, "model": m, "poisson_deviance": r.poisson_deviance,
                     "capture_top5": r.capture_top5, "capture_top10": r.capture_top10,
                     "capture_top20": r.capture_top20,
                     "dev_diff_vs_lgbm": p["diff"] if p else np.nan,
                     "dev_diff_ci_low": p["lo"] if p else np.nan, "dev_diff_ci_high": p["hi"] if p else np.nan,
                     "c10_diff_vs_lgbm": p10["diff"] if p10 else np.nan,
                     "c10_diff_ci_low": p10["lo"] if p10 else np.nan,
                     "c10_diff_ci_high": p10["hi"] if p10 else np.nan})
    A = pd.DataFrame(rows)
    mean = A.groupby("model").mean(numeric_only=True).reset_index().assign(cutoff="mean")
    A = pd.concat([A, mean], ignore_index=True)
    write_csv(A.round(6), REPORTS / "ablation_results.csv")
    parts.append("## Ablation (dev folds, population all; paired diff vs full LightGBM, 95% block CI)\n\n" +
                 md_table(A[A.cutoff == "mean"][["model", "poisson_deviance", "capture_top10", "capture_top20",
                                                  "dev_diff_vs_lgbm", "c10_diff_vs_lgbm"]], 4))

    # ---------------- dev folds, main models
    main = R[(R.study == "main") & (R.population == "all")]
    t = main.pivot_table(index="model", columns="cutoff", values=["poisson_deviance", "capture_top10"]).round(4)
    t.columns = [f"{a}_{b}" for a, b in t.columns]
    parts.append("## Development folds (population all)\n\n" + md_table(t.reset_index(), 4))
    calib = main.pivot_table(index="model", columns="cutoff", values="sum_pred_over_obs").round(3)
    parts.append("## Calibration in total (sum predicted / sum observed), dev folds\n\n" +
                 md_table(calib.reset_index(), 3))

    # ---------------- holdout
    hm = H[(H.study == "holdout") & (H.target == PRIMARY)]
    for pop in ["all", "numbered", "hist1"]:
        d = hm[hm.population == pop].copy()
        lo_hi = [ci(HB, m, "c10", "holdout", pop) for m in d.model]
        d["c10_ci"] = [f"[{a:.1f}, {b:.1f}]" if np.isfinite(a) else "" for a, b in lo_hi]
        parts.append(f"## Final holdout 2024-25, population `{pop}`\n\n" + md_table(
            d[["model", "poisson_deviance", "deviance_explained", "sum_pred_over_obs", "capture_top1",
               "capture_top5", "capture_top10", "c10_ci", "capture_top20", "capture_km_top10"]], 3))
    pr = HB[(HB.study == "holdout") & (HB.population == "all") & HB.get("pair_reference").notna()
            & (HB.target == PRIMARY)]
    pr = pr[pr.metric.isin(["dev", "c10", "c20"])][["model", "pair_reference", "metric", "diff_vs_ref_mean",
                                                      "diff_ci_low", "diff_ci_high"]]
    parts.append("## Final holdout: paired differences (row model minus reference), block bootstrap, 300 resamples\n\n" +
                 md_table(pr, 4))

    sp = H[(H.study == "holdout_spatial") & (H.population == "all")]
    parts.append("## Final holdout, spatial: each 50 km block group predicted by models fitted without it\n\n" +
                 md_table(sp[["model", "poisson_deviance", "capture_top5", "capture_top10", "capture_top20"]], 3))
    ex = H[(H.study == "holdout_exposure")]
    parts.append("## Exposure study (M/A with AADF), final holdout\n\n" + md_table(
        ex[ex.population == "exposure"][["model", "poisson_deviance", "capture_top5", "capture_top10",
                                         "capture_top20"]], 4))
    q = ex[ex.population.str.startswith("aadf_q")].pivot_table(index="model", columns="population",
                                                               values="capture_top10").round(2)
    parts.append("## Exposure study by AADF quintile (capture top 10% within quintile)\n\n" +
                 md_table(q.reset_index(), 2))
    tg = H[H.study.str.startswith("holdout_target_") | ((H.study == "holdout") & (H.population == "all"))]
    tg = tg[tg.population == "all"][["study", "target", "model", "poisson_deviance", "capture_top10"]]
    parts.append("## Outcome-definition sensitivity (final holdout, population all)\n\n" + md_table(tg, 4))
    ph = H[(H.study == "posthoc")]
    parts.append("## Post-hoc fold (cutoff 2022, target 2023-24)\n\n" +
                 md_table(ph[["model", "poisson_deviance", "capture_top10", "capture_top20"]], 4))

    # ---------------- headline numbers
    def g(study, pop, model, col, target=PRIMARY):
        d = H[(H.study == study) & (H.population == pop) & (H.model == model) & (H.target == target)]
        return float(d[col].iloc[0])
    for pop in ["all", "numbered", "hist1"]:
        for m in [sel, "hist_collisions", "eb", "hist_adj_ksi"]:
            head[f"holdout_{pop}_{m}_c10"] = round(g("holdout", pop, m, "capture_top10"), 1)
            head[f"holdout_{pop}_{m}_c20"] = round(g("holdout", pop, m, "capture_top20"), 1)
    p = pair(HB, sel, "hist_collisions", "c10", "holdout")
    if p:
        head["holdout_all_sel_minus_counts_c10"] = [round(p["diff"], 1), round(p["lo"], 1), round(p["hi"], 1)]
    cov = pd.read_csv(REPORTS / "coverage_by_population.csv")
    c = cov[(cov.cutoff == 2023) & (cov.target == PRIMARY)].set_index("population")
    for pop in ["all", "numbered", "hist1", "exposure"]:
        if pop in c.index:
            head[f"coverage_{pop}_share_national"] = round(100 * float(c.loc[pop, "share_of_national"]), 1)
    write_json(head, REPORTS / "headline.json")
    write_text("# Summary tables (generated by ml/audit/summarise.py; do not edit)\n\n" + "\n\n".join(parts) + "\n",
               REPORTS / "summary_tables.md")
    print(json.dumps(head, indent=1))


if __name__ == "__main__":
    main()
