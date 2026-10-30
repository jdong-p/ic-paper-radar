"""SQLite paper store: one row per DOI, the single source of truth for what was already done.

status: archive   backfilled corpus paper (for relations; recent ones can join a week as catch-up)
        pending   new, no abstract yet and not a title match; re-checked daily
        skipped   scored below min_score (or no abstract after abstract_give_up_days)
        candidate matched; belongs to `week`; digest cached in `digest`
        reported  shown in a finalized weekly report; never shown again
        topic     found by a --topic deep-dive
        pinned    anchor or --add-ed paper (pins.py): always in the catalog, never re-scored or finalized
        pool      Beyond-IEEE paper that passed the gate, waiting for a slot on the 10-paper board
user_mark (stage): normal (📋 Candidate) | selected (✅) | archived (🗄️); cited 0/1 (⭐), independent of the
stage since v2.9 — see curation.py; user_note = the 🏷️ Tech note typed in the dashboard (v2.15)
"""
import json
import sqlite3
from datetime import date

from env_guard import ensure_minisforum_env

ensure_minisforum_env()

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  doi TEXT PRIMARY KEY, title TEXT, authors TEXT, venue TEXT, venue_name TEXT, published TEXT,
  abstract TEXT, source TEXT, article_number TEXT, index_terms TEXT,
  score INTEGER DEFAULT 0, hits TEXT, status TEXT, first_seen TEXT, week TEXT,
  refs TEXT, oa_id TEXT, cited_by INTEGER, ieee_cites INTEGER, keyrefs TEXT, related TEXT,
  digest TEXT, digest_ver TEXT
);
CREATE INDEX IF NOT EXISTS ix_status ON papers(status);
CREATE INDEX IF NOT EXISTS ix_week ON papers(week);
CREATE INDEX IF NOT EXISTS ix_oa ON papers(oa_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS api_usage (day TEXT, api TEXT, calls INTEGER, PRIMARY KEY (day, api));
"""
JSON_COLS = {"authors", "index_terms", "hits", "refs", "keyrefs", "related", "lineage"}
# columns added after v2; created in place on older stores
MIGRATIONS = {"grp": "TEXT DEFAULT 'ieee'",      # 'ieee' or 'beyond' (Nature/Science portfolio)
              "lineage": "TEXT",                  # [{type, doi, venue, year, title, signal}]
              "lineage_checked": "TEXT",          # date of the last lineage search
              "user_mark": "TEXT DEFAULT 'normal'",  # stage: 'normal' | 'selected' | 'archived' (curation.py)
              "cited": "INTEGER DEFAULT 0",        # ⭐ Cite, independent of the stage (v2.9)
              "user_silicon": "TEXT",              # user's call after reading the PDF: 'silicon_verified' |
                                                   # 'simulation_only'; NULL = automatic guess (v2.10)
              "catchup": "TEXT",                  # week an archive paper was pulled into as catch-up
              "pin": "TEXT",                      # 'anchor' | 'manual' (pins.py)
              "pillar": "INTEGER",                # user-chosen pillar (--add --pillar); overrides the guess
              "user_note": "TEXT"}                # 🏷️ Tech note: the user's key technique / takeaway (v2.15)


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(papers)")}
        for col, decl in MIGRATIONS.items():
            if col not in have:
                self.db.execute(f"ALTER TABLE papers ADD COLUMN {col} {decl}")
        # v2.9: ⭐ is its own flag; a pre-v2.9 'cite' mark becomes Selected + Cited (idempotent)
        self.db.execute("UPDATE papers SET user_mark='selected', cited=1 WHERE user_mark='cite'")
        self.db.commit()

    def _row(self, r):
        if r is None:
            return None
        d = dict(r)
        for k in JSON_COLS:
            d[k] = json.loads(d[k]) if d.get(k) else ([] if k != "keyrefs" else None)
        return d

    def get(self, doi):
        return self._row(self.db.execute("SELECT * FROM papers WHERE doi=?", (doi,)).fetchone())

    def where(self, sql="1=1", args=()):
        return [self._row(r) for r in self.db.execute(f"SELECT * FROM papers WHERE {sql}", args)]

    def upsert(self, p, status_if_new):
        """Insert a new paper, or fill empty fields of a known one. Returns True if it was new."""
        old = self.get(p["doi"])
        if old is None:
            row = {**p, "status": status_if_new, "first_seen": p.get("first_seen") or date.today().isoformat()}
            self.update(p["doi"], row, insert=True)
            return True
        fill = {k: v for k, v in p.items() if v and not old.get(k) and k not in ("status", "first_seen")}
        if fill:
            self.update(p["doi"], fill)
        return False

    def update(self, doi, fields, insert=False):
        fields = {k: (json.dumps(v, ensure_ascii=False) if k in JSON_COLS else v) for k, v in fields.items()
                  if k in COLS}
        if insert:
            fields["doi"] = doi
            cols = ",".join(fields)
            self.db.execute(f"INSERT INTO papers ({cols}) VALUES ({','.join('?' * len(fields))})", list(fields.values()))
        elif fields:
            self.db.execute(f"UPDATE papers SET {','.join(k + '=?' for k in fields)} WHERE doi=?",
                            [*fields.values(), doi])
        self.db.commit()

    def meta(self, key, value=None):
        if value is None:
            r = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return json.loads(r[0]) if r else None
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def calls_today(self, api):
        r = self.db.execute("SELECT calls FROM api_usage WHERE day=? AND api=?", (date.today().isoformat(), api)).fetchone()
        return r[0] if r else 0

    def count_call(self, api):
        self.db.execute("INSERT INTO api_usage VALUES (?,?,1) ON CONFLICT(day, api) DO UPDATE SET calls=calls+1",
                        (date.today().isoformat(), api))
        self.db.commit()

    def counts(self):
        return dict(self.db.execute("SELECT status, COUNT(*) FROM papers GROUP BY status").fetchall())


COLS = {"doi", "title", "authors", "venue", "venue_name", "published", "abstract", "source", "article_number",
        "index_terms", "score", "hits", "status", "first_seen", "week", "refs", "oa_id", "cited_by",
        "ieee_cites", "keyrefs", "related", "digest", "digest_ver", *MIGRATIONS}
