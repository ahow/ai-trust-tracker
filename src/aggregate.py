"""Corrections and per-source aggregation (spec Section 4).
Order: relevance gate -> dedup/syndication -> reach caps -> author caps -> series.
"""
import re, math
from urllib.parse import urlparse, urlunparse

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|ref$|ref_)", re.I)

def canonical_url(url):
    if not url:
        return ""
    try:
        p = urlunparse
        from urllib.parse import urlparse, parse_qsl, urlencode
        u = urlparse(url.strip())
        qs = [(k, v) for k, v in parse_qsl(u.query) if not _TRACKING.match(k)]
        return p((u.scheme.lower(), u.netloc.lower().replace("www.", ""),
                  u.path.rstrip("/"), "", urlencode(qs), ""))
    except Exception:
        return url

def _tokens(title):
    return set(re.findall(r"[a-z0-9]+", (title or "").lower()))

def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def dedup(items, jaccard_threshold=0.8):
    """Collapse near-duplicates within a source-day. Cluster counts once for
    opinion; cluster size recorded (amplification) on the surviving item."""
    by_url = {}
    for it in items:
        cu = canonical_url(it.get("url"))
        key = cu or it["item_id"]
        by_url.setdefault(key, []).append(it)
    survivors, reps = [], []
    for group in by_url.values():
        reps.append(max(group, key=lambda x: x.get("reach") or 0))
    # title-level near-dup clusters (wire stories carried by many outlets)
    reps.sort(key=lambda x: -(x.get("reach") or 0))
    clusters = []
    for it in reps:
        toks = _tokens(it.get("title"))
        placed = False
        for cl in clusters:
            if _jaccard(toks, cl["toks"]) >= jaccard_threshold:
                cl["members"] += 1
                it["cluster_id"] = cl["id"]
                it["_drop"] = True      # kept in storage, zero weight
                cl["rep"].setdefault("raw", {})["amplification"] = cl["members"]
                placed = True
                break
        if not placed:
            cid = it["item_id"]
            it["cluster_id"] = cid
            clusters.append({"id": cid, "toks": toks, "rep": it, "members": 1})
            survivors.append(it)
    return items, survivors   # all items (for storage) + survivors (for scoring)

def apply_weights(items, reach_cap_percentile=99, author_cap=5):
    """w = min(log1p(reach), p99 cap per source-day); author cap N items/day."""
    logs = sorted(math.log1p(max(0, it.get("reach") or 0)) for it in items)
    cap = logs[min(len(logs) - 1, int(len(logs) * reach_cap_percentile / 100))] if logs else 1.0
    cap = max(cap, 1e-6)
    per_author = {}
    kept = []
    for it in sorted(items, key=lambda x: -(x.get("reach") or 0)):
        if it.get("_drop"):
            it["weight"] = 0.0
            continue
        a = it.get("author_hash") or "?"
        per_author[a] = per_author.get(a, 0) + 1
        if per_author[a] > author_cap:
            it["weight"] = 0.0
            continue
        it["weight"] = min(math.log1p(max(0, it.get("reach") or 0)), cap)
        if it["weight"] <= 0:
            it["weight"] = 1e-6
        kept.append(it)
    return kept

def series_for(items):
    """Weighted mean direction, effective n, SE for one source-target bucket."""
    ws = [it["weight"] for it in items]
    ds = [it["direction"] for it in items]
    sw = sum(ws)
    if sw <= 0 or not ds:
        return None
    m = sum(w * d for w, d in zip(ws, ds)) / sw
    n_eff = (sw ** 2) / sum(w * w for w in ws)
    var = sum(w * (d - m) ** 2 for w, d in zip(ws, ds)) / sw
    se = math.sqrt(var / max(n_eff, 1.0))
    return {"wmean": round(m, 4), "n_eff": round(n_eff, 1),
            "se": round(se, 4), "n_items": len(items)}
