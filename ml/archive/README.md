# Archive: superseded experiments, reclassified (v2 audit, 2026-10)

Nothing here is used by the v2 pipeline. Files are kept because they record
what was tried and why it was dropped. Each experiment is classified below so
that nobody cites an unreliable number by accident.

| Class | Meaning |
|---|---|
| **Valid negative result** | Sound protocol for its question; supports a decision that still stands |
| **Superseded** | Sound at the time; replaced by better data or method |
| **Unreliable** | Protocol flaw that biases the headline number; do not cite as evidence |
| **Invalid method** | The method is not what it claims to be |

All severity experiments here used 2009–2015 data and random row splits unless
stated. Their absolute numbers are not comparable with 2022–25 results,
because the CRASH/COPA reporting transition changed what "serious" means.

| Script | Results | Class | Why |
|---|---|---|---|
| `severity_cascade.py` | `average_precision.csv`, `ablation_2x2.csv` | Superseded (valid negative) | The cascade's macro-F1 gain came from the decision rule. AP was unchanged (Δ < 0.003), so threshold tuning on a flat model gives the same benefit. |
| `ablation_study.py` | `ablation_2x2.csv`, `ablation_validation_strategy.csv` | Valid negative result | Framing vs features 2×2. Random, ~11 km spatial and one-year temporal splits gave similar AUC (0.664–0.674), so the severity signal was not just location memorisation on 2009–10 data. |
| `validate_2009_2015.py` | `validation_2009_2015.csv` | Valid (with caveat) | Random, spatial and 2014–15 temporal tests agree (KSI AUC 0.792–0.793). The feature set includes post-crash fields, so this is the *explanatory* model, not a deployable one. |
| `svm_nn_comparison` (in `severity_prediction.py` era) | `svm_nn_comparison.csv` | Valid negative result | LinearSVC, RBF-SVC and an MLP did not beat LightGBM on AP. This supports using gradient boosting for tabular data. |
| `enriched_final_model.py`, `ensemble_comparison.csv`, `final_model_comparison.csv` | | Superseded | The LightGBM + LinearSVC blend added ~0.01 macro-AP for much more complexity. Not carried forward. |
| `enrichment_test.py` | `enrichment_results.csv` | Valid, but **explanatory only** | Vehicle and casualty fields raise AUC 0.676 → 0.789, but they are post-crash facts. This is the origin of the deployable/explanatory split. |
| `tune_enriched.py`, `fast_final.py`, `model_2009_2015.py` | `tuned_*`, `fast_final_*`, `model_2009_2015_config.json`, `comparison_2009_2015.csv` | Superseded | Pre-transition data (2009–15). The thresholds/multipliers in `fast_final.py` were chosen on in-sample training predictions (see v2 preliminary audit, D10). |
| `blackspot_segments.py` | `blackspot_validation.csv`, `blackspot_top100.csv`, `blackspot_top500.json` | **Invalid method** (as "Empirical Bayes") and **Unreliable** | (1) The EB "prior" is the sum of per-crash P(KSI) over the crashes that actually occurred, so it is conditional on the observed record, not a safety performance function of road characteristics. The dispersion `k` is a marginal moment estimate, not the SPF's NB dispersion. That is a smoothing heuristic, not Hauer's EB. (2) 500 m × 500 m grid cells, not road segments. Cite only as "a grid heuristic that did not beat crash counts". |
| `blackspot_model.py` | `blackspot_model_validation.csv`, `blackspot_shap_importance.csv` | **Unreliable** | Random 70/30 split of neighbouring grid cells (spatial leakage). Ties in the crash-count baseline were broken by `argsort` order. The "SPF" here is a LightGBM on crash history, not an SPF in the HSM sense. The 60.4% vs 59.7% top-20% gap is within tie-breaking noise. |
| `blackspot_excess_risk.py` | `blackspot_risk_shap.csv`, `blackspot_api_top500.json` | **Invalid method** | Uses `log(n_crashes)` as a Poisson **offset** and calls it exposure. Historical crashes are an outcome, not traffic. The model therefore predicts KSI *per crash* (a severity share), with regression-to-the-mean noise in the denominator. v2 uses DfT AADF for exposure and never substitutes crash counts. |
| `casualty_cost_model.py` | | Superseded | Valuation-weighted target (RAS4001). It may be worth revisiting once the v2 ranking is stable. Not validated prospectively. |
| `build_dataset.py`, `stats19_join.py` | | Superseded | 2009–2015 joins. v2's join is in `ml/blackspot/stats19.py`, with grain checks. |

Also recorded (`CLAUDE.md`): the evaluation-protocol experiment in which the
same model scored 0.379 or 0.729 depending on whether class balancing happened
before or after the train/test split. It is a **valid negative result** about
protocol and the reason v2 never resamples before splitting.
