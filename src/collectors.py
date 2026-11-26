"""Collectors for free sources. Contract: each returns (items, status, detail).
Sources fail soft — the pipeline records source_status and continues; the lens
coverage rule in combine.py decides whether a lens publishes without them.
"""
import requests, hashlib, time, datetime, os

UA = {"User-Agent": "ai-trust-tracker/0.1 (research; contact: local user)"}
TIMEOUT = 40

def _day(s=None):
    return (s or datetime.datetime.now(datetime.UTC).date().isoformat())

def _id(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:24]

def _ah(a):
    return hashlib.sha256((a or "unknown").encode()).hexdigest()[:16]

# ---------------------------------------------------------------- GDELT (media)
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_FIELD_Q = '("artificial intelligence" OR chatgpt OR "generative ai" OR openai OR "ai safety")'
GDELT_BIZ_DOMAINS = ["reuters.com", "bloomberg.com", "ft.com", "cnbc.com",
                     "marketwatch.com", "businessinsider.com", "fortune.com", "finance.yahoo.com"]

def _gdelt_query(query, timespan="1d", maxrecords=250, retries=4):
    """GDELT rate-limits to 1 req / 5s; shared IPs may see 429 -> long backoff."""
    params = {"query": query, "mode": "ArtList", "maxrecords": maxrecords,
              "format": "json", "timespan": timespan, "sort": "dateasc"}
    wait = 20
    for attempt in range(retries):
        r = requests.get(GDELT_API, params=params, headers=UA, timeout=TIMEOUT)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            return r.json().get("articles", [])
        if r.status_code == 429 and attempt < retries - 1:
            time.sleep(wait); wait *= 2; continue
        raise RuntimeError(f"GDELT HTTP {r.status_code}: {r.text[:120]}")
    return []

def parse_timeline(payload):
    """Extract [{date, value}] from a GDELT timeline-mode JSON payload."""
    out = []
    for series in payload.get("timeline", []):
        for pt in series.get("data", []):
            out.append({"date": pt.get("date"), "value": pt.get("value")})
    return out

def _gdelt_timeline(query, mode, timespan="1d", retries=4):
    """Timeline modes (TimelineTone / TimelineVolRaw) are computed server-side
    across ALL matching coverage — no 250-record cap (playbook section 3.1)."""
    params = {"query": query, "mode": mode, "format": "json", "timespan": timespan}
    wait = 20
    for attempt in range(retries):
        r = requests.get(GDELT_API, params=params, headers=UA, timeout=TIMEOUT)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            return parse_timeline(r.json())
        if r.status_code == 429 and attempt < retries - 1:
            time.sleep(wait); wait *= 2; continue
        raise RuntimeError(f"GDELT {mode} HTTP {r.status_code}")
    return []

def collect_gdelt_timelines(day=None, timespan="1d"):
    """Native GDELT tone + volume series for the field, media and business scopes.
    Tone is a word-list measure with a known negative lean — use day-over-day
    change, never the absolute level (playbook sections 1 and 6)."""
    day = _day(day)
    biz_q = GDELT_FIELD_Q + " (" + " OR ".join(f"domain:{d}" for d in GDELT_BIZ_DOMAINS) + ")"
    rows = []
    try:
        for source, q in (("gdelt", GDELT_FIELD_Q), ("gdelt_biz", biz_q)):
            tone = _gdelt_timeline(q, "timelinetone", timespan)
            time.sleep(6)
            vol = _gdelt_timeline(q, "timelinevolraw", timespan)
            time.sleep(6)
            tones = {p["date"]: p["value"] for p in tone if p.get("value") is not None}
            vols = {p["date"]: p["value"] for p in vol if p.get("value") is not None}
            tot_v = sum(vols.values())
            avg = (sum(tones.get(d, 0.0) * v for d, v in vols.items()) / tot_v
                   if tot_v else None)
            rows.append({"day": day, "source": source, "scope": "field",
                         "avg_tone": avg, "article_count": int(tot_v),
                         "raw": {"tone": tone[-48:], "vol": vol[-48:]}})
        return rows, ("ok" if any(r["article_count"] for r in rows) else "empty"), \
            f"{sum(r['article_count'] for r in rows)} articles across timelines"
    except Exception as e:
        return rows, "unavailable", str(e)[:200]

def _gdelt_items(articles, source, lens, day):
    items = []
    for a in articles:
        items.append({
            "item_id": _id(source, a.get("url", "")),
            "source": source, "lens": lens,
            "url": a.get("url"), "title": a.get("title", ""),
            "text": (a.get("title", "") + " " + a.get("seendate", "")),
            "author_hash": _ah(a.get("domain")), "author_type": "journalist",
            "country": a.get("sourcecountry"), "language": a.get("language", "en"),
            "reach": 1,  # GDELT ArtList gives no audience figures; outlet = 1 voice
            "published_utc": a.get("seendate"), "day": day,
            "raw": {"domain": a.get("domain"), "socialimage": a.get("socialimage", "")[:200]},
        })
    return items

def collect_gdelt(day=None, timespan="1d"):
    day = _day(day)
    try:
        arts = _gdelt_query(GDELT_FIELD_Q, timespan)
        time.sleep(6)  # respect 1 req / 5 s
        biz_q = GDELT_FIELD_Q + " (" + " OR ".join(f"domain:{d}" for d in GDELT_BIZ_DOMAINS) + ")"
        biz = _gdelt_query(biz_q, timespan, maxrecords=150)
        items = _gdelt_items(arts, "gdelt", "media", day) + _gdelt_items(biz, "gdelt_biz", "business", day)
        return items, ("ok" if items else "empty"), f"{len(arts)} media + {len(biz)} business articles"
    except Exception as e:
        return [], "unavailable", str(e)[:200]

# ------------------------------------------------------- Hacker News (technical)
def _hn_clean(s):
    """Algolia returns HTML-escaped text with <p>/<i> tags; normalise once."""
    import html as _h, re as _r
    return _r.sub(r"\s+", " ", _r.sub(r"<[^>]+>", " ", _h.unescape(s or ""))).strip()

def collect_hackernews(day=None, hours=26):
    day = _day(day)
    try:
        cutoff = int(time.time()) - hours * 3600
        seen, items = set(), []
        for q in ["AI", "artificial intelligence", "LLM", "OpenAI", "Claude", "ChatGPT"]:
            r = requests.get("https://hn.algolia.com/api/v1/search_by_date",
                             params={"query": q, "tags": "(story,comment)",
                                     "hitsPerPage": 100,
                                     "numericFilters": f"created_at_i>{cutoff}"},
                             headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            for h in r.json().get("hits", []):
                oid = h.get("objectID")
                if oid in seen:
                    continue
                seen.add(oid)
                is_story = h.get("title") is not None
                items.append({
                    "item_id": _id("hackernews", oid),
                    "source": "hackernews", "lens": "technical",
                    "url": h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                    "title": _hn_clean(h.get("title") or (h.get("comment_text") or "")[:400])[:200],
                    "text": _hn_clean(h.get("comment_text") or h.get("story_text") or h.get("title") or ""),
                    "author_hash": _ah(h.get("author")), "author_type": "developer",
                    "country": None, "language": "en",
                    "reach": h.get("points") or 1,
                    "published_utc": h.get("created_at"), "day": day,
                    "raw": {"hn_id": oid, "kind": "story" if is_story else "comment"},
                })
            time.sleep(1)
        return items, ("ok" if items else "empty"), f"{len(items)} unique HN items"
    except Exception as e:
        return [], "unavailable", str(e)[:200]

# ------------------------------------------------------------ Bluesky (public)
def collect_bluesky(day=None, hours=26):
    """Unauthenticated public search. Live-only API: capture must run daily."""
    day = _day(day)
    try:
        since = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        items, cursor = [], None
        for _ in range(4):  # 4 pages x 50 = 200 max/day
            params = {"q": "AI", "lang": "en", "limit": 50, "since": since, "sort": "latest"}
            if cursor:
                params["cursor"] = cursor
            r = requests.get("https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts",
                             params=params, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            posts = data.get("posts", [])
            if not posts:
                break
            for p in posts:
                rec = p.get("record", {})
                items.append({
                    "item_id": _id("bluesky", p.get("uri", "")),
                    "source": "bluesky", "lens": "public",
                    "url": "https://bsky.app/profile/" + p.get("author", {}).get("handle", "") +
                           "/post/" + p.get("uri", "").rsplit("/", 1)[-1],
                    "title": (rec.get("text") or "")[:200],
                    "text": rec.get("text") or "",
                    "author_hash": _ah(p.get("author", {}).get("handle")),
                    "author_type": "individual", "country": None, "language": "en",
                    "reach": (p.get("likeCount") or 0) + (p.get("repostCount") or 0) + 1,
                    "published_utc": rec.get("createdAt"), "day": day,
                    "raw": {"uri": p.get("uri")},
                })
            cursor = data.get("cursor")
            if not cursor:
                break
            time.sleep(1)
        return items, ("ok" if items else "empty"), f"{len(items)} posts"
    except Exception as e:
        return [], "unavailable", str(e)[:200]

# -------------------------------------------------------------- Reddit (public)
REDDIT_SUBS = ["artificial", "ArtificialInteligence", "singularity", "ChatGPT",
               "OpenAI", "LocalLLaMA", "technology", "Futurology"]

def collect_reddit(day=None, hours=26):
    """OAuth if REDDIT_CLIENT_ID/SECRET set; else public JSON attempt.
    TERMS: free tier is for non-commercial use — review before production."""
    day = _day(day)
    try:
        cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
        headers = dict(UA)
        if cid and secret:
            auth = requests.auth.HTTPBasicAuth(cid, secret)
            tok = requests.post("https://www.reddit.com/api/v1/access_token", auth=auth,
                                data={"grant_type": "client_credentials"},
                                headers=UA, timeout=TIMEOUT).json()
            headers["Authorization"] = f"bearer {tok['access_token']}"
            base = "https://oauth.reddit.com"
        else:
            base = "https://www.reddit.com"
        cutoff = time.time() - hours * 3600
        seen, items = set(), []
        for sub in REDDIT_SUBS:
            r = requests.get(f"{base}/r/{sub}/search.json",
                             params={"q": "AI OR trust", "restrict_sr": 1,
                                     "sort": "new", "limit": 50, "t": "day"},
                             headers=headers, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            for ch in r.json().get("data", {}).get("children", []):
                d = ch.get("data", {})
                if d.get("created_utc", 0) < cutoff or d.get("id") in seen:
                    continue
                seen.add(d.get("id"))
                items.append({
                    "item_id": _id("reddit", d.get("id")),
                    "source": "reddit", "lens": "public",
                    "url": "https://www.reddit.com" + d.get("permalink", ""),
                    "title": d.get("title", ""),
                    "text": d.get("title", "") + " " + (d.get("selftext") or "")[:2000],
                    "author_hash": _ah(d.get("author")), "author_type": "individual",
                    "country": None, "language": "en",
                    "reach": max(1, (d.get("score") or 0) + 1),
                    "published_utc": datetime.datetime.fromtimestamp(
                        d.get("created_utc", 0), datetime.UTC).isoformat(),
                    "day": day, "raw": {"subreddit": sub},
                })
            time.sleep(2)
        return items, ("ok" if items else "empty"), f"{len(items)} posts"
    except Exception as e:
        return [], "unavailable", str(e)[:200]

COLLECTORS = {
    "gdelt": collect_gdelt,
    "hackernews": collect_hackernews,
    "bluesky": collect_bluesky,
    "reddit": collect_reddit,
}
