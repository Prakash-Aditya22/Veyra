"""Final audit: every critical requirement checked against the generated outputs.

    .venv/Scripts/python ml/audit/final_audit.py            (after develop, holdout, forecast, severity)

Writes ml/reports/final_audit.json (machine-readable) and the evidence table that
ml/reports/final_audit.md embeds. Statuses: PASS, FAIL, WARNING. Nothing here is
asserted from memory: each check recomputes or re-reads its evidence.
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML))
from blackspot.config import BACKEND_DATA, OUTPUTS, REPORTS  # noqa: E402
from blackspot.io_utils import setup_logging, write_json  # noqa: E402

RESULTS: list[dict] = []


def check(req, status, evidence):
    RESULTS.append({"requirement": req, "status": status, "evidence": evidence})
    print(f"[{status}] {req}: {evidence}")


def run_tests():
    r = subprocess.run([sys.executable, "-m", "pytest", str(ML / "tests"), "-q", "-p", "no:cacheprovider"],
                       capture_output=True, text=True, cwd=ML.parent)
    last = [ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1]
    ok = r.returncode == 0 and "skipped" not in last
    check("Tests pass (incl. output-schema tests, none skipped)", "PASS" if ok else
          ("WARNING" if r.returncode == 0 else "FAIL"), last)


def leakage_real_data(ctx, spec):
    from blackspot.experiment import fit_predict, standard_specs
    from blackspot.features import HOLDOUT_CUTOFF, PRIMARY, Fold, build_frame
    f = Fold(HOLDOUT_CUTOFF)
    fut = ctx.ac.collision_year.isin(f.test_y.years + [y + 2 for y in f.test_y.years])
    X1 = build_frame(ctx.seg, ctx.ac, f.test_x, f.test_y, ctx.road)
    X2 = build_frame(ctx.seg, ctx.ac[~fut], f.test_x, None, ctx.road)
    feats = [c for c in X1.columns if not c.startswith("y_")]
    same = X1[feats].equals(X2[feats])
    check("No future leakage: holdout features unchanged when every 2024-25 collision is deleted",
          "PASS" if same else "FAIL", f"{len(feats)} feature columns x {len(X1):,} segments compared")
    # predictions of the frozen model with and without the target years in the input
    Xtr = build_frame(ctx.seg, ctx.ac, f.train_x, f.train_y, ctx.road)
    Xtr2 = build_frame(ctx.seg, ctx.ac[~fut], f.train_x, f.train_y, ctx.road)
    chosen = [s for s in standard_specs(spec["lgbm_params"]) if s.name == spec["selected_model"]][0]
    p1, _ = fit_predict(chosen, Xtr, Xtr[f"y_{PRIMARY}"].values, X1, PRIMARY)
    p2, _ = fit_predict(chosen, Xtr2, Xtr2[f"y_{PRIMARY}"].values, X2, PRIMARY)
    d = float(np.max(np.abs(p1 - p2)))
    check("No future leakage: frozen model's holdout predictions unchanged without 2024-25 data",
          "PASS" if d < 1e-9 else ("WARNING" if d < 1e-6 else "FAIL"), f"max |diff| = {d:.2e}")
    return p1


def protocol_checks(spec):
    from blackspot.features import DEV_CUTOFFS, HOLDOUT_CUTOFF, Fold
    hold_years = set(Fold(HOLDOUT_CUTOFF).test_y.years)
    used = set()
    for c in spec["dev_cutoffs"]:
        f = Fold(c)
        used |= set(f.train_x.years + f.train_y.years + f.test_x.years + f.test_y.years)
    check("Model selection used development folds only (no holdout years)",
          "PASS" if not used & hold_years and spec["dev_cutoffs"] == list(DEV_CUTOFFS) else "FAIL",
          f"dev years {min(used)}-{max(used)}; holdout target {sorted(hold_years)}")
    spec_file = OUTPUTS / "frozen_spec.json"
    mc = REPORTS / "model_comparison.csv"
    ro = REPORTS / "rolling_origin_results.csv"
    order_ok = ro.stat().st_mtime <= spec_file.stat().st_mtime <= mc.stat().st_mtime
    m = pd.read_csv(mc)
    hash_ok = (m.frozen_spec_sha256 == spec["sha256"]).all()
    check("Holdout run after the spec was frozen, and stamped with its hash",
          "PASS" if order_ok and hash_ok else "FAIL",
          f"develop -> frozen spec -> holdout file order {'ok' if order_ok else 'WRONG'}; "
          f"hash {spec['sha256'][:12]} on all {len(m)} rows: {hash_ok}")


def geometry_checks(ctx):
    from blackspot import network
    sig = inspect.signature(network.segment_network)
    no_crash_input = list(sig.parameters) == ["links", "verts", "voff"]
    check("Segment geometry built without crash data", "PASS" if no_crash_input else "FAIL",
          f"segment_network{sig}; IDs unique: {ctx.seg.segment_id.is_unique}")
    cov = pd.read_csv(REPORTS / "rolling_origin_coverage.csv")
    n = cov[cov.population == "all"].groupby("cutoff").segments.first()
    cov2 = pd.read_csv(REPORTS / "coverage_by_population.csv")
    n2 = cov2[cov2.population == "all"].segments.unique()
    same = n.nunique() == 1 and set(n2) <= set(n)
    check("Eligibility independent of outcomes (same segment population in every fold)",
          "PASS" if same else "FAIL", f"segments per fold: {sorted(set(n) | set(n2))}")
    det = REPORTS / "network_determinism.json"
    if det.exists():
        d = json.loads(det.read_text())
        check("Segment IDs reproduce across independent network rebuilds",
              "PASS" if d.get("identical") else "FAIL", json.dumps(d))
    else:
        check("Segment IDs reproduce across independent network rebuilds", "WARNING",
              "full rebuild comparison not run (see ml/audit/network_determinism.py); row-shuffle "
              "invariance is covered by tests")


def evaluation_checks(spec, ctx, p_selected):
    m = pd.read_csv(REPORTS / "model_comparison.csv")
    studies = set(m.study)
    need = {"holdout", "holdout_spatial", "holdout_exposure", "posthoc"}
    check("Temporal (rolling + final holdout) and spatial validation completed",
          "PASS" if need <= studies else "FAIL", f"studies present: {sorted(studies)}")
    g = m.groupby(["study", "cutoff", "target", "population"])
    same = g.n_rows.nunique().max() == 1 and (g.target_sum.agg(lambda s: s.max() - s.min()).max() < 1e-6)
    check("Every model and baseline evaluated on the identical population",
          "PASS" if same else "FAIL",
          f"{g.ngroups} (study, fold, target, population) groups; max distinct row counts per group = "
          f"{g.n_rows.nunique().max()}")
    # reproduce the stored holdout deviance of the selected model
    from blackspot.evaluation import poisson_deviance
    from blackspot.features import HOLDOUT_CUTOFF, PRIMARY, Fold, build_frame
    f = Fold(HOLDOUT_CUTOFF)
    y = build_frame(ctx.seg, ctx.ac, f.test_x, f.test_y, ctx.road)[f"y_{PRIMARY}"].values
    stored = m[(m.study == "holdout") & (m.population == "all") & (m.target == PRIMARY)
               & (m.model == spec["selected_model"])].poisson_deviance.iloc[0]
    now = poisson_deviance(y, p_selected)
    check("Holdout metric of the selected model reproduces from scratch",
          "PASS" if abs(now - stored) < 1e-6 else ("WARNING" if abs(now - stored) < 1e-3 else "FAIL"),
          f"stored {stored:.6f}, recomputed {now:.6f}")


def coverage_checks():
    cov = pd.read_csv(REPORTS / "coverage_by_population.csv")
    h = cov[(cov.cutoff == 2023) & (cov.target == "adj_ksi_cas")]
    s = json.loads((REPORTS / "coverage_summary.json").read_text())
    tot = sum(s["holdout_target_2024_2025|adj_ksi_cas"]["by_bucket"].values())
    check("National coverage uses national denominators (buckets sum to 100%)",
          "PASS" if abs(tot - 1) < 2e-4 else "FAIL",
          "holdout: " + ", ".join(f"{r.population} {r.share_of_national:.1%}" for r in h.itertuples()))
    ex = h[h.population == "exposure"]
    check("Exposure coverage stated explicitly", "PASS" if len(ex) else "FAIL",
          f"M/A segments with AADF: {int(ex.segments.iloc[0]):,} segments, {ex.km.iloc[0]:,.0f} km, "
          f"{ex.share_of_national.iloc[0]:.1%} of national KSI" if len(ex) else "missing")


def severity_checks():
    meta = json.loads((OUTPUTS / "severity_v2" / "severity_deployable_v2_meta.json").read_text())
    forbidden = {"number_of_vehicles", "number_of_casualties", "did_police_officer_attend_scene_of_accident",
                 "police_force", "collision_severity", "local_authority_district"}
    bad = [c for c in meta["features"] if c in forbidden or c.startswith(("v_", "k_", "n_", "adj_"))]
    check("Severity model served as 'deployable' uses pre-outcome features only",
          "PASS" if not bad else "FAIL", f"{len(meta['features'])} features; disallowed present: {bad}")
    r = pd.read_csv(REPORTS / "severity_results.csv")
    have = set(r.split)
    check("Severity validated temporally (2025 untouched) and spatially",
          "PASS" if {"test_2025", "spatial_blocks_2022_2025"} <= have else "FAIL", f"splits: {sorted(have)}")


def schema_checks():
    from blackspot.outputs import LEGACY_COLS
    v2 = BACKEND_DATA / "v2" / "road_segments_ranked_v2.csv"
    v1 = BACKEND_DATA / "road_segments_ranked.csv"
    if not v2.exists():
        check("Output schema backward compatible", "FAIL", "v2 file missing")
        return
    cols = list(pd.read_csv(v2, nrows=1).columns)
    ok = cols[:len(LEGACY_COLS)] == LEGACY_COLS and list(pd.read_csv(v1, nrows=1).columns) == LEGACY_COLS
    check("Output schema backward compatible (v1 file untouched; v2 = legacy columns first + additions)",
          "PASS" if ok else "FAIL", f"v2 has {len(cols)} columns, first {len(LEGACY_COLS)} = v1 columns: {ok}")


def doc_checks():
    """Every headline number the README quotes must equal the generated value."""
    head = json.loads((REPORTS / "headline.json").read_text())
    readme = (ML / "README.md").read_text(encoding="utf-8")
    want = {}
    for pop in ["all", "numbered", "hist1"]:
        for m in [head["selected_model"], "hist_collisions", "eb", "hist_adj_ksi"]:
            for f in ["c10", "c20"]:
                want[f"holdout_{pop}_{m}_{f}"] = f"{head[f'holdout_{pop}_{m}_{f}']:.1f}"
    for k in ["coverage_all_share_national", "coverage_numbered_share_national",
              "coverage_hist1_share_national", "coverage_exposure_share_national"]:
        want[k] = f"{head[k]:.1f}%"
    d, lo, hi = head["holdout_all_sel_minus_counts_c10"]
    want["model_minus_counts"] = f"+{d:.1f} points"
    want["model_minus_counts_ci"] = f"[95% CI {lo:.1f}, {hi:.1f}]"
    rob = json.loads((REPORTS / "robustness_extra.json").read_text())
    rtm = rob["regression_to_the_mean_holdout"]
    want["rtm_history_top500"] = f"{rtm['top500_by_history']['future_over_history'] * 100:.0f}%"
    want["rtm_model_top500"] = f"{rtm['top500_by_model']['future_over_forecast'] * 100:.0f}%"
    sub = rob["holdout_model_vs_counts_subpopulations"]
    want["numbered_diff_ci"] = f"[{sub['numbered']['diff_c10_ci'][0]:.1f}, {sub['numbered']['diff_c10_ci'][1]:.1f}]"
    want["hist1_diff_ci"] = f"[{sub['hist1']['diff_c10_ci'][0]:.1f}, {sub['hist1']['diff_c10_ci'][1]:.1f}]"
    want["single_events"] = f"{rob['single_event_flag']['segments_flagged_nationally']} segments"
    sev = pd.read_csv(REPORTS / "severity_results.csv")
    core = sev[(sev.label_set == "injury_based_only") & (sev.feature_set == "core") & (sev.split == "test_2025")].iloc[0]
    want["severity_auc"] = f"**{core.roc_auc:.3f}** [{core.roc_auc_ci_low:.3f}, {core.roc_auc_ci_high:.3f}]"
    v1 = sev[sev.feature_set.str.startswith("v1_")].iloc[0]
    want["severity_v1_auc"] = f"{v1.roc_auc:.3f}"
    spec = json.loads((OUTPUTS / "frozen_spec.json").read_text())
    want["spec_hash"] = spec["sha256"][:12]
    missing = {k: v for k, v in want.items() if v not in readme}
    check("Documentation matches generated results (every README headline number re-derived)",
          "PASS" if not missing else "FAIL", f"{len(want) - len(missing)}/{len(want)} values found"
          + (f"; missing: {missing}" if missing else ""))
    lim = readme.split("## Read before using the numbers")[-1]
    n_lim = sum(1 for ln in lim.splitlines() if ln[:3].strip().rstrip(".").isdigit())
    check("Remaining limitations visible in the README", "PASS" if n_lim >= 5 else "FAIL",
          f"{n_lim} numbered limitations in ml/README.md; also reports/robustness.md, coverage_analysis.md")


def main():
    setup_logging()
    from blackspot.steps import _context, _load_frozen
    spec = _load_frozen()
    ctx = _context(with_aadf=False)
    run_tests()
    protocol_checks(spec)
    p = leakage_real_data(ctx, spec)
    geometry_checks(ctx)
    evaluation_checks(spec, ctx, p)
    coverage_checks()
    severity_checks()
    schema_checks()
    doc_checks()
    write_json({"frozen_spec_sha256": spec["sha256"], "checks": RESULTS}, REPORTS / "final_audit.json")
    print(pd.DataFrame(RESULTS)[["status", "requirement"]].to_string(index=False))


if __name__ == "__main__":
    main()
