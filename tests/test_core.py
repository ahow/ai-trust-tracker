"""Tests: rubric, aggregate, combine, collectors. Run: python3 -m pytest tests/ -q"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import rubric, aggregate, combine, collectors

# ---------------------------------------------------------------- rubric
def test_positive_trust():
    s = rubric.score_item("OpenAI's new model is remarkably reliable and safe",
                          "Users praise the accuracy and helpful alignment work.")
    assert s["direction"] > 0 and s["relevance"] >= 0.5

def test_negative_trust():
    s = rubric.score_item("ChatGPT lawsuit over deepfake scam",
                          "Critics say the AI tool is dangerous and cannot be trusted.")
    assert s["direction"] < 0

def test_passing_mention_dropped():
    s = rubric.score_item("Local council approves budget",
                          "The report mentioned artificial intelligence once in passing.")
    assert s["relevance"] < 0.5          # subject-vs-mention rule
    assert s["direction"] == 0

def test_non_ai_zero_relevance():
    s = rubric.score_item("Football results", "United won 2-1 in a dramatic finish.")
    assert s["relevance"] == 0.0

def test_negation_flips():
    s = rubric.score_item("AI model is not reliable", "The chatbot is not safe to use.")
    assert s["direction"] < 0

def test_direction_clamped():
    s = rubric.score_item("AI disaster: rogue ai, existential threat, catastrophic harm",
                          "dangerous risky biased fraud scam lawsuit banned")
    assert -2 <= s["direction"] <= 2 and s["direction"] == -2

def test_neutral_report_scores_zero():
    s = rubric.score_item("OpenAI announces GPT review", "The company published figures.")
    assert s["direction"] == 0 and s["stance_type"] == "unscored"

def test_company_matching_case_sensitivity():
    comps = [{"id": "apple", "name": "Apple", "aliases_ci": ["apple intelligence"],
              "aliases_cs": ["Apple"]}]
    assert rubric.match_companies("Apple Intelligence launches", "", comps) == [("apple", "title")]
    assert rubric.match_companies("How to grow apple trees with AI", "", comps) == []

# ---------------------------------------------------------------- aggregate
def _it(iid, reach, direction, author="a", title="AI news", url=None):
    return {"item_id": str(iid), "url": url or f"https://x.com/{iid}", "title": title,
            "reach": reach, "author_hash": author, "direction": direction, "_drop": False}

def test_n_eff_formula():
    items = [_it(1, 1, 1, "a"), _it(2, 1, -1, "b")]
    for it in items:
        it["weight"] = 1.0
    s = aggregate.series_for(items)
    assert abs(s["wmean"]) < 1e-9 and abs(s["n_eff"] - 2.0) < 1e-9

def test_author_cap():
    items = [_it(i, 100, 2, "spammy", f"AI story {i}") for i in range(10)]
    kept = aggregate.apply_weights(items, author_cap=5)
    assert sum(1 for it in items if it["weight"] > 0) == 5

def test_dedup_collapses_wire_copies():
    items = [_it(1, 10, 0, "a", "OpenAI faces lawsuit over training data",
                 "https://reuters.com/1?utm_source=x"),
             _it(2, 5, 0, "b", "OpenAI faces lawsuit over training data!",
                 "https://mirror.com/2")]
    all_items, survivors = aggregate.dedup(items)
    assert len(survivors) == 1 and survivors[0]["raw"]["amplification"] == 2

def test_dedup_url_tracking_params():
    items = [_it(1, 1, 0, "a", "AI story A", "https://x.com/a?utm_source=n"),
             _it(2, 1, 0, "b", "Different title entirely", "https://x.com/a")]
    _, survivors = aggregate.dedup(items)
    assert len(survivors) == 1  # same canonical URL

# ---------------------------------------------------------------- combine
def test_source_weight_cap():
    rows = [dict(source="big", wmean=1.0, se=0.01, n_eff=1000),
            dict(source="s1", wmean=0.0, se=0.5, n_eff=10),
            dict(source="s2", wmean=0.0, se=0.5, n_eff=10)]
    value, se, meta = combine.blend_lens(rows, cap=0.40)
    assert meta["weights"]["big"] <= 0.40 + 1e-9

def test_composite_band_widening():
    lv = {"public": (0.0, 0.1), "media": (0.0, 0.1)}
    w = {"public": 0.5, "media": 0.5}
    narrow = combine.combine_lenses(lv, w, band_mult=1.0)
    wide = combine.combine_lenses(lv, w, band_mult=2.0)
    assert (wide["hi"] - wide["lo"]) > (narrow["hi"] - narrow["lo"])

def test_survey_gap_same_family_only():
    anchors = [{"id": "a1", "metric_family": "trust-in-ai", "value": 32,
                "fieldwork_end": "2025-10-27", "geo": "US"},
               {"id": "a2", "metric_family": "benefits-outweigh", "value": 59,
                "fieldwork_end": "2025-04-04", "geo": "GLOBAL"}]
    g = combine.survey_gap(45.0, anchors, metric_family="trust-in-ai")
    assert g["anchor_id"] == "a1" and abs(g["gap"] - 13.0) < 1e-9

def test_rescale_bounds():
    assert combine.to_100(-2) == 0 and combine.to_100(2) == 100

# ---------------------------------------------------------------- collectors
def test_parse_timeline():
    payload = {"timeline": [
        {"data": [{"date": "20261125000000", "value": -1.23},
                  {"date": "20261125010000", "value": -1.10}]},
        {"data": [{"date": "20261125020000", "value": 0.5}]},
    ]}
    pts = collectors.parse_timeline(payload)
    assert len(pts) == 3
    assert pts[0] == {"date": "20261125000000", "value": -1.23}
    assert pts[-1]["value"] == 0.5

def test_parse_timeline_empty_and_malformed():
    assert collectors.parse_timeline({}) == []
    assert collectors.parse_timeline({"timeline": [{"data": []}]}) == []

def test_proxies_env_toggle(monkeypatch):
    """GDELT proxy is opt-in via EVOMI_PROXY_URL; absent -> direct connection."""
    monkeypatch.delenv("EVOMI_PROXY_URL", raising=False)
    assert collectors._proxies() is None
    monkeypatch.setenv("EVOMI_PROXY_URL", "http://u:p@proxy.example:1000")
    p = collectors._proxies()
    assert p == {"http": "http://u:p@proxy.example:1000",
                 "https": "http://u:p@proxy.example:1000"}

# ---------------------------------------------------------------- GKG (Route B)
def test_gkg_terms_regex():
    assert collectors._GKG_RE.search("OpenAI announces new model")
    assert collectors._GKG_RE.search("Concerns about LLMs in classrooms")
    assert collectors._GKG_RE.search("EU passes AI regulation")
    # word boundaries: 'said'/'again'/'climate' must not trip on ai/llm
    assert not collectors._GKG_RE.search("He said again that climate is key")
    # ambiguous tokens we deliberately excluded
    assert not collectors._GKG_RE.search("The Gemini constellation and Claude Shannon")

def test_gkg_bare_ai_title_only():
    # v0.3.1: bare 'AI' matches case-sensitively on the TITLE only
    assert collectors._GKG_TITLE_AI_RE.search("Patients turning to social media, AI for help")
    assert collectors._GKG_TITLE_AI_RE.search("The long road to a post-AI world")
    # case-insensitive junk we must NOT match
    assert not collectors._GKG_TITLE_AI_RE.search("Ai Weiwei exhibition opens")
    assert not collectors._GKG_TITLE_AI_RE.search("Hot ticket sales for Barn Fire Jam")
    # parse-level: bare-AI title passes the filter with no other term present
    row = ["x", "20261126214500", "1", "example.com",
           "https://example.com/news/local-story"] + [""] * 10 \
          + ["1.5,2,0.5,2.5,3,1,800"] + [""] * 10 \
          + ['<PAGE_TITLE>Court discussing AI in sentencing</PAGE_TITLE>']
    assert len(row) == 27
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("t.gkg.csv", "\t".join(row))
    recs = collectors._gkg_parse_batch(buf.getvalue())
    assert len(recs) == 1 and "AI" in recs[0]["title"]
    # ...but bare 'AI' in URL/names alone (title clean) does NOT pass
    row2 = list(row)
    row2[4] = "https://example.com/ai/local-story"
    row2[26] = "<PAGE_TITLE>Hot ticket sales for Barn Fire Jam</PAGE_TITLE>"
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as z:
        z.writestr("t.gkg.csv", "\t".join(row2))
    assert collectors._gkg_parse_batch(buf2.getvalue()) == []

def test_company_window_excludes_future_days(tmp_path, monkeypatch):
    """Regression (v0.3.1): the 7-day company window had no upper bound, so
    backfilled days counted all FUTURE items (openai n_eff hit ~19k on days
    with 1 actual item). Window must be [day-6, day], never beyond day."""
    import store, daily_update
    db = str(tmp_path / "t.db")
    con = store.connect(db)
    for day, n in (("2026-11-10", 3), ("2026-11-26", 5)):
        for i in range(n):
            con.execute(
                "INSERT INTO items (item_id, source, lens, url, title, text, day, reach)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (f"{day}-{i}", "gdelt", "media", f"http://x/{day}/{i}",
                 "OpenAI faces trust questions", "ai safety debate", day, 1))
    con.commit(); con.close()
    monkeypatch.setattr(daily_update, "DB", db)
    daily_update.run(day="2026-11-10", reuse=True, timelines=False)
    con = store.connect(db)
    row = con.execute("SELECT n_eff FROM company_daily"
                      " WHERE day='2026-11-10' AND company_id='openai'").fetchone()
    con.close()
    assert row is not None, "openai should be scored on 2026-11-10"
    assert row[0] == 3, f"future items leaked into window: n_eff={row[0]}, want 3"

def test_gkg_batch_times_exact_day():
    import datetime as dt
    end = dt.datetime(2026, 11, 21, 0, 0, tzinfo=dt.UTC)
    ts = collectors._gkg_batch_times(24, end)
    assert len(ts) == 96                       # 24h x 4 batches
    assert ts[-1] == dt.datetime(2026, 11, 20, 0, 0, tzinfo=dt.UTC)   # oldest
    assert ts[0] == dt.datetime(2026, 11, 20, 23, 45, tzinfo=dt.UTC)  # newest

def test_gkg_parse_batch():
    import io, zipfile
    fields = ["123456789", "20261126170000", "1", "Reuters.com",
              "https://reuters.com/tech/openai-trust-2026"]   # 0-4
    fields += [""] * 10                                       # 5-14
    fields += ["1.5,3.0,1.5,3.0,10,1,800"]                    # 15 V2Tone
    fields += [""] * 10                                       # 16-25
    fields += ["<PAGE_TITLE>OpenAI faces trust questions &#x2014; again</PAGE_TITLE>"]  # 26
    assert len(fields) == 27
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("20261126170000.gkg.csv",
                   "\t".join(fields) + "\n" + "\t".join(["x"] * 5) + "\n")
    recs = collectors._gkg_parse_batch(buf.getvalue())
    assert len(recs) == 1                      # short row skipped
    r = recs[0]
    assert r["title"] == "OpenAI faces trust questions — again"   # HTML-unescaped
    assert r["tone"] == 1.5 and r["wc"] == 800
    assert r["published_utc"] == "2026-11-26T17:00:00Z"
    assert r["domain"] == "reuters.com"
