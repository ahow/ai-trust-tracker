"""Lens blending and composite (spec Section 5, Phase-1 form).
b_i = 0 PRIOR everywhere -> every output PROVISIONAL; bands widened by the
provisional multiplier. Identification: inverse-variance weights with a 40%
per-source cap, renormalised (the fixed-lambda Kalman form arrives in Phase 3).
"""
import math

def _cap_weights(weights, cap):
    """Iteratively cap weights and renormalise the remainder."""
    weights = dict(weights)
    for _ in range(10):
        total = sum(weights.values())
        over = {k: v for k, v in weights.items() if v / total > cap}
        if not over:
            break
        for k in over:
            weights[k] = cap * total
        locked = sum(v for v in weights.values() if v == cap * total)
        rest = {k: v for k, v in weights.items() if k not in over}
        s = sum(rest.values())
        if s > 0:
            for k in rest:
                weights[k] = rest[k] / s * (1 - locked)
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}

def blend_lens(series_rows, cap=0.40):
    """series_rows: [{source, wmean, se, n_eff}]. Returns value, se, weights."""
    rows = [r for r in series_rows if r["se"] and r["se"] > 0]
    if not rows:
        return None, None, {}
    prec = {r["source"]: 1.0 / (r["se"] ** 2) for r in rows}
    w = _cap_weights(prec, cap)
    value = sum(w[r["source"]] * r["wmean"] for r in rows)
    se = math.sqrt(sum((w[r["source"]] * r["se"]) ** 2 for r in rows))
    n_eff = sum(r["n_eff"] for r in rows)
    return value, se, {"weights": w, "n_eff": n_eff}

def to_100(direction, dmin=-2, dmax=2):
    return (direction - dmin) / (dmax - dmin) * 100

def combine_lenses(lens_values, lens_weights, band_mult=2.0):
    """lens_values: {lens: (value, se)}. Returns 0-100 composite + 90% band."""
    total_w = sum(lens_weights[l] for l in lens_values if l in lens_weights)
    if total_w <= 0:
        return None
    v, var = 0.0, 0.0
    for lens, (value, se) in lens_values.items():
        w = lens_weights.get(lens, 0) / total_w  # renormalise over present lenses
        v += w * value
        var += (w * se) ** 2
    se = math.sqrt(var)
    half = 1.645 * se * band_mult
    c, lo, hi = to_100(v), to_100(v - half), to_100(v + half)
    return {"value": round(c, 1), "lo": round(max(0, lo), 1),
            "hi": round(min(100, hi), 1), "se_dir": round(se, 4)}

def survey_gap(public_value_100, anchors, metric_family="trust-in-ai"):
    """Discourse-implied public trust minus latest anchor IN THE SAME metric
    family. Cross-family comparison is invalid (question wording differs)."""
    fam = [a for a in anchors if a.get("metric_family") == metric_family]
    if not fam:
        return None
    latest = max(fam, key=lambda a: a.get("fieldwork_end") or "")
    return {"gap": round(public_value_100 - latest["value"], 1),
            "anchor_id": latest["id"], "anchor_value": latest["value"],
            "anchor_geo": latest.get("geo"), "metric_family": metric_family}
