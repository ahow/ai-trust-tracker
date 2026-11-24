"""Daily update: collect -> score -> correct -> aggregate -> combine -> store.
Run:  python3 scripts/daily_update.py [--day YYYY-MM-DD] [--timespan 1d] [--reuse]
"""
import sys, os, datetime, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml
import store, rubric, aggregate, combine
from collectors import COLLECTORS

ROOT = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(ROOT, "data", "trust.db")

def load_cfg(name):
    with open(os.path.join(ROOT, "config", name)) as f:
        return yaml.safe_load(f)

def run(day=None, timespan="1d", reuse=False):
    day = day or datetime.datetime.now(datetime.UTC).date().isoformat()
    params = load_cfg("parameters.yaml")
    companies = load_cfg("companies.yaml")["companies"]
    surveys = load_cfg("surveys.yaml")
    con = store.connect(DB)
    store.load_anchors(con, surveys["anchors"])

    # 1. collect ------------------------------------------------------------
    all_items = []
    if reuse:
        rows = con.execute(
            "SELECT item_id, source, lens, url, title, text, author_hash, author_type, "
            "country, language, reach, published_utc, day FROM items WHERE day=?",
            (day,)).fetchall()
        keys = ["item_id", "source", "lens", "url", "title", "text", "author_hash",
                "author_type", "country", "language", "reach", "published_utc", "day"]
        all_items = [dict(zip(keys, r)) for r in rows]
        print(f"  reusing {len(all_items)} stored items for {day}")
    else:
        for source, fn in COLLECTORS.items():
            if not params["sources"].get(source, {}).get("enabled", True):
                store.set_status(con, day, source, "disabled")
                continue
            kwargs = {"day": day}
            if source == "gdelt":
                kwargs["timespan"] = timespan
            items, status, detail = fn(**kwargs)
            store.set_status(con, day, source, status, detail, len(items))
            print(f"  [{source:11s}] {status:11s} {len(items):4d} items  {detail[:80]}")
            all_items.extend(items)
    con.commit()

    # 2. score + gate --------------------------------------------------------
    gated = []
    for it in all_items:
        s = rubric.score_item(it.get("title"), it.get("text"))
        it.update(s)
        store.upsert_item(con, it)
        for cid, field in rubric.match_companies(it.get("title"), it.get("text"), companies):
            store.link_company(con, it["item_id"], cid, field)
        if s["relevance"] >= params["rubric"]["relevance_drop_below"]:
            gated.append(it)
    con.commit()

    # 3. corrections ---------------------------------------------------------
    corr = params["corrections"]
    by_src = {}
    for it in gated:
        by_src.setdefault(it["source"], []).append(it)
    scored = []
    for src, items in by_src.items():
        _, survivors = aggregate.dedup(items, corr["dedup_title_jaccard"])
        scored.extend(aggregate.apply_weights(
            survivors, corr["reach_cap_percentile"], corr["author_max_items_per_day"]))
    for it in all_items:   # persist cluster ids
        if it.get("cluster_id"):
            con.execute("UPDATE items SET cluster_id=? WHERE item_id=?",
                        (it["cluster_id"], it["item_id"]))
    con.commit()

    # 4. per (source, target) series -----------------------------------------
    links = {r[0]: r[1] for r in con.execute("SELECT item_id, company_id FROM item_companies")}
    buckets = {}
    for it in scored:
        buckets.setdefault((it["source"], it["lens"], "field"), []).append(it)
        cid = links.get(it["item_id"])
        if cid:
            buckets.setdefault((it["source"], it["lens"], cid), []).append(it)
    for (src, lens, target), items in buckets.items():
        s = aggregate.series_for(items)
        if s:
            con.execute("INSERT OR REPLACE INTO series VALUES (?,?,?,?,?,?,?,?)",
                        (day, src, lens, target, s["wmean"], s["n_eff"], s["se"], s["n_items"]))
    con.commit()

    # 5. lens blending (field target only for lens indices) -------------------
    cmb = params["combine"]
    lens_values, coverage_info = {}, {}
    lenses = sorted({v["lens"] for v in params["sources"].values()})
    for lens in lenses:
        srcs = [s for s, v in params["sources"].items() if v["lens"] == lens]
        rows = [dict(source=r[0], wmean=r[1], se=r[2], n_eff=r[3]) for r in con.execute(
            "SELECT source, wmean, se, n_eff FROM series WHERE day=? AND lens=? AND target='field'",
            (day, lens))]
        present = {r["source"] for r in rows}
        coverage = len(present) / max(1, len(srcs))
        published = 1 if coverage >= cmb["min_lens_coverage"] else 0
        if rows:
            value, se, meta = combine.blend_lens(rows, cmb["source_max_lens_weight"])
        else:
            value, se, meta = None, None, {"n_eff": 0}
        con.execute("INSERT OR REPLACE INTO lens_daily VALUES (?,?,?,?,?,?,?,?)",
                    (day, lens, value, se, meta.get("n_eff"), coverage, published, 1))
        if value is not None:
            lens_values[lens] = (value, se)
            coverage_info[lens] = {"coverage": coverage, "published": published, **meta}
    con.commit()

    # 6. composite + survey gap ----------------------------------------------
    comp = {}
    for view, weights in cmb["lens_weights"].items():
        r = combine.combine_lenses(lens_values, weights, cmb["provisional_band_multiplier"])
        if r and len(lens_values) >= 2:   # composite needs >=2 lenses present
            con.execute("INSERT OR REPLACE INTO composite_daily VALUES (?,?,?,?,?,?,?)",
                        (day, view, r["value"], r["lo"], r["hi"], None, 1))
            comp[view] = r
        elif r:
            print(f"  composite ({view}) withheld: only {len(lens_values)} lens present")
    con.commit()
    gap = None
    if "public" in lens_values:
        gap = combine.survey_gap(combine.to_100(lens_values["public"][0]),
                                 surveys["anchors"])

    # 7. company scores (rolling window) --------------------------------------
    cs = params["company_scores"]
    since = (datetime.date.fromisoformat(day) -
             datetime.timedelta(days=cs["window_days"] - 1)).isoformat()
    field100 = comp.get("societal", {}).get("value")
    if field100 is None:
        # Fallback field reference: weighted mean direction of ALL gated items
        # in the window, rescaled. The published composite may be withheld for
        # lack of lenses; company relativity should not depend on that rule.
        fr = con.execute("""SELECT direction FROM items
            WHERE day >= ? AND relevance >= ?""",
            (since, params["rubric"]["relevance_drop_below"])).fetchall()
        if fr:
            field100 = combine.to_100(sum(r[0] for r in fr) / len(fr))
    rows = con.execute("""
        SELECT i.item_id, i.lens, i.direction, i.topics, i.dimension, ic.company_id
        FROM items i JOIN item_companies ic ON ic.item_id = i.item_id
        WHERE i.day >= ? AND i.relevance >= ?""",
        (since, params["rubric"]["relevance_drop_below"])).fetchall()
    by_co = {}
    for item_id, lens, d, topics, dim, cid in rows:
        by_co.setdefault(cid, []).append((lens, d, topics, dim))
    n_companies = 0
    for cid, recs in by_co.items():
        ds = [r[1] for r in recs]
        n_eff = len(ds)  # unweighted within company window (v0)
        n_lenses = len({r[0] for r in recs})
        score = combine.to_100(sum(ds) / len(ds))
        low = 1 if (n_eff < cs["min_n_eff"] or n_lenses < cs["min_lenses"]) else 0
        topics = [t for r in recs for t in (r[2] or "").split(",") if t]
        top_topic = max(set(topics), key=topics.count) if topics else None
        dims = [r[3] for r in recs if r[3]]
        top_dim = max(set(dims), key=dims.count) if dims else None
        rel = round(score - field100, 1) if field100 is not None else None
        con.execute("INSERT OR REPLACE INTO company_daily VALUES (?,?,?,?,?,?,?,?,?)",
                    (day, cid, round(score, 1), rel, n_eff, n_lenses, low, top_topic, top_dim))
        n_companies += 1
    con.commit()
    print(f"  scored {len(scored)} items after gates | lenses: {sorted(lens_values)} "
          f"| composite(societal): {comp.get('societal')} | companies: {n_companies}")
    if gap:
        print(f"  survey gap (public lens vs {gap['anchor_id']} {gap['anchor_geo']}): "
              f"{gap['gap']:+.1f} pts  [INDICATIVE — uncalibrated]")
    con.close()

if __name__ == "__main__":
    args = sys.argv[1:]
    kw = {}
    if "--day" in args:
        kw["day"] = args[args.index("--day") + 1]
    if "--timespan" in args:
        kw["timespan"] = args[args.index("--timespan") + 1]
    if "--reuse" in args:
        kw["reuse"] = True
    run(**kw)
