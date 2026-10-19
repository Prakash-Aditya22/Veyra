"""Explaining the production blackspot model (TreeSHAP), shared by the experiment and the tests.

The production LightGBM uses a Poisson objective, so the model is additive in
log space: log(expected KSI) = base + sum_j phi_j. TreeSHAP values phi_j are
exact for tree ensembles (Lundberg et al. 2020) and are reported here both as
log contributions and as multiplicative factors exp(phi_j): "this feature
multiplies the expected count by x relative to the model's average".

SHAP values describe how the MODEL uses a feature, given the other features.
They are associations learnt from crash data, not causal effects, and the
largest contribution is not necessarily the most effective thing to change.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# planner-readable labels; group = where the information comes from;
# kind = "exposure_proxy" (scales with how much travel the road carries) or
# "risk_character" (describes the circumstances of crashes or the road layout)
FEATURES = {
    "h_n_coll": ("Collisions on this segment, last 3 years", "history", "exposure_proxy"),
    "h_adj_ksi_cas": ("Serious/fatal casualties here (adjusted), last 3 years", "history", "exposure_proxy"),
    "h_n_ksi_cas": ("Serious/fatal casualties here (as reported), last 3 years", "history", "exposure_proxy"),
    "h_n_fatal_cas": ("Fatal casualties here, last 3 years", "history", "exposure_proxy"),
    "h_n_cas": ("All casualties here, last 3 years", "history", "exposure_proxy"),
    "h_is_ksi_collision": ("Serious/fatal collisions here, last 3 years", "history", "exposure_proxy"),
    "h_is_fatal_collision": ("Fatal collisions here, last 3 years", "history", "exposure_proxy"),
    "h_last_n_coll": ("Collisions here in the most recent year", "history", "exposure_proxy"),
    "h_last_adj_ksi_cas": ("Serious/fatal casualties here in the most recent year", "history", "exposure_proxy"),
    "h_years_with_crash": ("Years (of 3) with at least one collision here", "history", "exposure_proxy"),
    "h_share_junction": ("Share of recent collisions at junctions", "history", "risk_character"),
    "h_share_dark": ("Share of recent collisions in darkness", "history", "risk_character"),
    "h_share_urban": ("Share of recent collisions in urban areas", "history", "risk_character"),
    "h_share_wet": ("Share of recent collisions on wet or icy roads", "history", "risk_character"),
    "h_speed_median": ("Typical speed limit at recent collisions", "history", "risk_character"),
    "h_share_single_vehicle": ("Share of recent collisions involving one vehicle", "history", "risk_character"),
    "h_ksi_share": ("Share of recent collisions that were serious/fatal", "history", "risk_character"),
    "h_adj_ksi_per_km": ("Serious/fatal casualties per km, last 3 years", "history", "exposure_proxy"),
    "h_coll_per_km": ("Collisions per km, last 3 years", "history", "exposure_proxy"),
    "log_length": ("Segment length", "road", "exposure_proxy"),
    "cls_M": ("Road class: motorway", "road", "risk_character"),
    "cls_A": ("Road class: A road", "road", "risk_character"),
    "cls_B": ("Road class: B road", "road", "risk_character"),
    "cls_C": ("Road class: C road", "road", "risk_character"),
    "cls_U": ("Road class: unclassified", "road", "risk_character"),
    "cls_N": ("Road class: not classified", "road", "risk_character"),
    "fw_collapsed_dual": ("Dual carriageway (drawn as one line)", "road", "risk_character"),
    "fw_dual": ("Dual carriageway (drawn per carriageway)", "road", "risk_character"),
    "fw_roundabout": ("Roundabout", "road", "risk_character"),
    "fw_slip": ("Slip road", "road", "risk_character"),
    "fw_single": ("Single carriageway", "road", "risk_character"),
    "share_roundabout": ("Share of segment that is roundabout", "road", "risk_character"),
    "share_slip": ("Share of segment that is slip road", "road", "risk_character"),
    "n_junctions": ("Junctions on the segment", "road", "risk_character"),
    "junctions_per_km": ("Junctions per km", "road", "risk_character"),
    "primary_route": ("Primary route", "road", "risk_character"),
    "trunk_road": ("Trunk road", "road", "risk_character"),
    "tunnel": ("Tunnel", "road", "risk_character"),
    "named": ("Road has a street name", "road", "risk_character"),
    "stroke_pieces": ("Length of the whole junction-to-junction stretch (in ~500 m pieces)", "road", "exposure_proxy"),
    "net_km_1km": ("Road network density, 1 km square (urbanity proxy)", "context", "exposure_proxy"),
    "net_km_3km": ("Road network density, 3x3 km (urbanity proxy)", "context", "exposure_proxy"),
    "nb_adj_ksi_3km": ("Serious/fatal casualties on nearby roads (3x3 km), last 3 years", "context", "exposure_proxy"),
    "nb_coll_3km": ("Collisions on nearby roads (3x3 km), last 3 years", "context", "exposure_proxy"),
    "stroke_adj_ksi_other": ("Serious/fatal casualties elsewhere on the same stretch, last 3 years", "context",
                             "exposure_proxy"),
}
TARGET_LIKE = ("y_", "future_", "blackspot_score", "eb_", "spf_")


BINARY = {"cls_M", "cls_A", "cls_B", "cls_C", "cls_U", "cls_N", "fw_collapsed_dual", "fw_dual", "fw_roundabout",
          "fw_slip", "fw_single", "primary_route", "trunk_road", "tunnel", "named"}


def display_value(f: str, v: float) -> str:
    """Human-readable feature value for UIs (model inputs are sometimes logs or 0/1 flags)."""
    if v is None or not np.isfinite(v):
        return "no data"
    if f == "log_length":
        return f"{np.exp(v):,.0f} m"
    if f in BINARY:
        return "yes" if v >= 0.5 else "no"
    if f.startswith(("h_share", "share_")) or f == "h_ksi_share":
        return f"{100 * v:.0f}%"
    if f == "h_speed_median":
        return f"{v:.0f} mph"
    if f.startswith("net_km"):
        return f"{v:,.1f} km of road"
    if f.endswith("_per_km"):
        return f"{v:,.2f} per km"
    if f == "stroke_pieces":
        return f"{v:.0f} x ~500 m"
    if abs(v - round(v)) < 1e-6:
        return f"{v:,.0f}"
    return f"{v:,.1f}"


def label(f: str) -> str:
    return FEATURES.get(f, (f, "", ""))[0]


def group(f: str) -> str:
    return FEATURES.get(f, ("", "other", ""))[1]


def contributions(booster, X: np.ndarray, batch: int = 200_000) -> np.ndarray:
    """Exact TreeSHAP from LightGBM (pred_contrib): (n, n_features + 1), last column = base value."""
    out = []
    for i in range(0, len(X), batch):
        out.append(booster.predict(X[i:i + batch], pred_contrib=True).astype(np.float32))
    return np.vstack(out)


def check_additivity(contrib: np.ndarray, pred: np.ndarray, tol: float = 1e-3) -> float:
    """max |(base + sum phi) - log(pred)|; Poisson objective -> raw score is log expected count."""
    raw = contrib.sum(axis=1, dtype=np.float64)
    return float(np.max(np.abs(raw - np.log(np.clip(pred, 1e-30, None)))))


def top_contributions(contrib: np.ndarray, cols: list[str], X: np.ndarray, rows: np.ndarray, k: int = 5):
    """Long table of the k largest |phi| per row, with labels and multiplicative factors."""
    phi = contrib[rows, :-1]
    order = np.argsort(-np.abs(phi), axis=1)[:, :k]
    recs = []
    for r_i, r in enumerate(rows):
        for j_rank, j in enumerate(order[r_i]):
            recs.append({"row": int(r), "contrib_rank": j_rank + 1, "feature": cols[j], "label": label(cols[j]),
                         "group": group(cols[j]), "feature_value": float(X[r, j]),
                         "display_value": display_value(cols[j], float(X[r, j])),
                         "shap_log": float(phi[r_i, j]), "factor": float(np.exp(phi[r_i, j]))})
    return pd.DataFrame(recs)


def group_contributions(contrib: np.ndarray, cols: list[str]) -> pd.DataFrame:
    g = pd.Series([group(c) for c in cols])
    out = {}
    for name in ["history", "road", "context"]:
        idx = np.flatnonzero(g.values == name)
        out[f"shap_{name}"] = contrib[:, idx].sum(axis=1)
    out["base"] = contrib[:, -1]
    return pd.DataFrame(out)


def assert_no_target_columns(cols) -> None:
    bad = [c for c in cols if str(c).startswith(TARGET_LIKE)]
    if bad:
        raise AssertionError(f"target or output columns among explanation features: {bad}")
