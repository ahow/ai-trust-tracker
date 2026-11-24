"""SQLite storage for the AI Trust Tracker. Schema is the contract:
any DB evolution must be committed back here immediately (controversy-project lesson)."""
import sqlite3, os, json

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    lens TEXT NOT NULL,
    url TEXT,
    title TEXT,
    text TEXT,
    author_hash TEXT,
    author_type TEXT DEFAULT 'unknown',
    country TEXT,
    language TEXT DEFAULT 'en',
    reach INTEGER DEFAULT 0,
    published_utc TEXT,
    day TEXT NOT NULL,               -- UTC date of publication, YYYY-MM-DD
    cluster_id TEXT,                 -- near-duplicate / syndication cluster
    relevance REAL,
    direction INTEGER,               -- -2..+2
    dimension TEXT,
    topics TEXT,                     -- comma list
    stance_type TEXT DEFAULT 'unscored',
    confidence REAL,
    review_flag INTEGER DEFAULT 0,
    rubric_version TEXT,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS item_companies (
    item_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    match_field TEXT,                -- 'title' or 'text'
    PRIMARY KEY (item_id, company_id)
);
CREATE TABLE IF NOT EXISTS series (
    day TEXT NOT NULL,
    source TEXT NOT NULL,
    lens TEXT NOT NULL,
    target TEXT NOT NULL,            -- 'field' or company_id
    wmean REAL,                      -- weighted mean direction, -2..+2
    n_eff REAL,
    se REAL,
    n_items INTEGER,
    PRIMARY KEY (day, source, target)
);
CREATE TABLE IF NOT EXISTS lens_daily (
    day TEXT NOT NULL,
    lens TEXT NOT NULL,
    value REAL,                      -- blended direction -2..+2
    se REAL,
    n_eff REAL,
    coverage REAL,                   -- share of lens sources reporting
    published INTEGER,               -- 0 if below min coverage
    provisional INTEGER DEFAULT 1,
    PRIMARY KEY (day, lens)
);
CREATE TABLE IF NOT EXISTS composite_daily (
    day TEXT NOT NULL,
    view TEXT NOT NULL,              -- 'societal' | 'investor'
    value REAL,                      -- 0-100
    lo REAL, hi REAL,                -- 90% band (provisional-widened)
    divergence REAL,                 -- cross-lens SD of z-scores; NULL when THIN
    provisional INTEGER DEFAULT 1,
    PRIMARY KEY (day, view)
);
CREATE TABLE IF NOT EXISTS company_daily (
    day TEXT NOT NULL,
    company_id TEXT NOT NULL,
    score REAL,                      -- 0-100 rescaled direction
    rel_to_field REAL,               -- score minus composite (societal)
    n_eff REAL,
    n_lenses INTEGER,
    low_confidence INTEGER,
    top_topic TEXT,
    top_dimension TEXT,
    PRIMARY KEY (day, company_id)
);
CREATE TABLE IF NOT EXISTS anchors (
    id TEXT PRIMARY KEY,
    provider TEXT, wave TEXT, fieldwork_end TEXT, geo TEXT,
    metric_family TEXT, question TEXT, value REAL, scale TEXT, lens TEXT, url TEXT
);
CREATE TABLE IF NOT EXISTS source_status (
    day TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,            -- ok | unavailable | empty | error
    detail TEXT,
    n_items INTEGER DEFAULT 0,
    PRIMARY KEY (day, source)
);
"""

def connect(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con

def upsert_item(con, it):
    con.execute("""INSERT OR REPLACE INTO items
        (item_id, source, lens, url, title, text, author_hash, author_type, country,
         language, reach, published_utc, day, cluster_id, relevance, direction,
         dimension, topics, stance_type, confidence, review_flag, rubric_version, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (it["item_id"], it["source"], it["lens"], it.get("url"), it.get("title"),
         it.get("text"), it.get("author_hash"), it.get("author_type", "unknown"),
         it.get("country"), it.get("language", "en"), it.get("reach", 0),
         it.get("published_utc"), it["day"], it.get("cluster_id"),
         it.get("relevance"), it.get("direction"), it.get("dimension"),
         it.get("topics"), it.get("stance_type", "unscored"), it.get("confidence"),
         it.get("review_flag", 0), it.get("rubric_version"),
         json.dumps(it.get("raw", {}))[:20000]))

def link_company(con, item_id, company_id, match_field):
    con.execute("INSERT OR IGNORE INTO item_companies VALUES (?,?,?)",
                (item_id, company_id, match_field))

def set_status(con, day, source, status, detail="", n_items=0):
    con.execute("INSERT OR REPLACE INTO source_status VALUES (?,?,?,?,?)",
                (day, source, status, detail[:500], n_items))

def load_anchors(con, anchors):
    for a in anchors:
        con.execute("""INSERT OR REPLACE INTO anchors
            (id, provider, wave, fieldwork_end, geo, metric_family, question, value, scale, lens, url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (a["id"], a.get("provider"), a.get("wave"), a.get("fieldwork_end"),
             a.get("geo"), a.get("metric_family"), a.get("question"), a.get("value"),
             a.get("scale"), a.get("lens"), a.get("url")))
