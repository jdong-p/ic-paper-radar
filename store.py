"""SQLite paper store: one row per DOI, the single source of truth for what was already done.

status: archive   backfilled corpus paper (for relations; recent ones can join a week as catch-up)
        pending   new, no abstract yet and not a title match; re-checked daily
        skipped   scored below min_score (or no abstract after abstract_give_up_days)
        candidate matched; belongs to `week`; digest cached in `digest`
        reported  shown in a finalized weekly report; never shown again
        topic     found by a --topic deep-dive
        pinned    anchor or --add-ed paper (pins.py): always in the catalog, never re-scored or finalized
        pool      Beyond-IEEE paper that passed the gate, waiting for a slot on the 10-paper board
        external  brought in by --merge-store from someone else's store (v2.16): shared corpus for --topic /
                  --recall / relations, never pulled into this radar's pillars or board; this radar's own
                  collection adopts it (upsert) when it finds the same DOI
        external_ro  (v3.0.3) the same, but merged from a data_repo.read_repos entry (someone else's repo, read
                  only, e.g. a bio_med friend's corpus): left out of this radar's exports, so it never re-uploads
                  them into its own data repo, until adopted (≥ min_score → archive), found by this radar's own
                  collection, or also merged from the primary shared repo (→ external)
user_mark (stage): normal (📋 Candidate) | selected (✅) | archived (🗄️); cited 0/1 (⭐), independent of the
stage since v2.9 — see curation.py; user_note = the 🏷️ Tech note typed in the dashboard (v2.15)
"""
import json
import os
import re
import sqlite3
from datetime import date
from pathlib import Path

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
CREATE TABLE IF NOT EXISTS peer_curation (peer_id TEXT, doi TEXT, pillar TEXT, score REAL, user_mark TEXT,
  cited INTEGER, user_note TEXT, PRIMARY KEY (peer_id, doi));
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


# ---------- full-text search (v3.0): SQLite FTS5 over the papers table ----------
# An external-content index (no second copy of the text): papers_fts's rowid is papers.rowid, kept in sync by
# three triggers, so every insert, update (upsert, merge, note, marks) and delete updates it, and scoring
# updates (score, hits, status) don't touch it at all. The store is never VACUUMed (that could renumber rowids);
# export_clean_share_db() drops the index from the share copy, so shared files stay plain v2.19 databases.
FTS_COLS = ("title", "abstract", "authors", "index_terms", "user_note")
# bm25 weights in column order: doi (UNINDEXED), title, abstract, authors, index_terms, user_note
FTS_WEIGHTS = (0.0, 5.0, 1.0, 2.0, 2.5, 3.0)
FTS_TRIGGERS = ("papers_fts_ai", "papers_fts_ad", "papers_fts_au")
_ALL = ", ".join(("doi",) + FTS_COLS)
_NEW = ", ".join(f"new.{c}" for c in ("doi",) + FTS_COLS)
_OLD = ", ".join(f"old.{c}" for c in ("doi",) + FTS_COLS)
FTS_SQL = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5({_ALL.replace('doi', 'doi UNINDEXED', 1)},
  content='papers', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS papers_fts_ai AFTER INSERT ON papers BEGIN
  INSERT INTO papers_fts(rowid, {_ALL}) VALUES (new.rowid, {_NEW});
END;
CREATE TRIGGER IF NOT EXISTS papers_fts_ad AFTER DELETE ON papers BEGIN
  INSERT INTO papers_fts(papers_fts, rowid, {_ALL}) VALUES ('delete', old.rowid, {_OLD});
END;
CREATE TRIGGER IF NOT EXISTS papers_fts_au AFTER UPDATE OF {_ALL} ON papers BEGIN
  INSERT INTO papers_fts(papers_fts, rowid, {_ALL}) VALUES ('delete', old.rowid, {_OLD});
  INSERT INTO papers_fts(rowid, {_ALL}) VALUES (new.rowid, {_NEW});
END;
"""
_FTS5 = None


def fts5_available():
    """True if this Python's SQLite has FTS5 (python.org builds and most distributions do)."""
    global _FTS5
    if _FTS5 is None:
        try:
            c = sqlite3.connect(":memory:")
            c.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
            c.close()
            _FTS5 = True
        except sqlite3.Error:
            _FTS5 = False
    return _FTS5


def drop_fts(db):
    """Remove the index and its triggers (the share copy; or a store opened by a Python without FTS5)."""
    for t in FTS_TRIGGERS:
        db.execute(f"DROP TRIGGER IF EXISTS {t}")
    if fts5_available():
        db.execute("DROP TABLE IF EXISTS papers_fts")
    db.commit()


def ensure_fts(db):
    """Create papers_fts + triggers and fill it once ('rebuild', a few seconds for 10,000 papers) when missing.
    Returns whether full-text search is available. Without FTS5 the triggers are dropped, because they would
    make every write fail; searches then fall back to LIKE."""
    if not fts5_available():
        for t in FTS_TRIGGERS:
            db.execute(f"DROP TRIGGER IF EXISTS {t}")
        db.commit()
        return False
    have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name IN (?,?,?,?)",
                                     ("papers_fts", *FTS_TRIGGERS))}
    if len(have) == 4:
        return True
    try:
        if "papers_fts" in have:  # a half-made index (an interrupted first open): start over
            drop_fts(db)
        db.executescript(FTS_SQL)
        db.execute("INSERT INTO papers_fts(papers_fts) VALUES('rebuild')")
        db.commit()
    except sqlite3.OperationalError:  # another process created it at the same moment
        db.rollback()
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name='papers_fts'")} == {"papers_fts"}


def fts_query(text, prefix=False):
    """User text → an FTS5 query: every word (or hyphenated / dotted run, e.g. 'sub-100nW', '0.5-V') as a quoted
    phrase, all of them required. Quotes and operators in the text can't break the query."""
    terms = []
    for t in re.findall(r"[^\W_]+(?:[-.·][^\W_]+)*", text or ""):
        terms.append('"' + " ".join(re.split(r"[-.·]", t)) + '"')
    if prefix and terms:
        terms[-1] += "*"
    return " ".join(terms)


def fts_any(terms):
    """[term, …] → one FTS5 query matching any of them (each a phrase, its last word as a prefix, so 'energy
    harvester' also finds 'energy harvesters'); regex terms (re:…) are left out; '' if none."""
    q = [fts_query(t, prefix=True) for t in terms if not str(t).startswith("re:")]
    return " OR ".join(f"({x})" for x in q if x)


class Store:
    def __init__(self, path, fts=True):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(papers)")}
        for col, decl in MIGRATIONS.items():
            if col not in have:
                self.db.execute(f"ALTER TABLE papers ADD COLUMN {col} {decl}")
        have = {r[1] for r in self.db.execute("PRAGMA table_info(peer_curation)")}
        for col in ("status", "user_silicon"):  # v2.19: a peer's radar state and Si call, for its dashboard page
            if col not in have:
                self.db.execute(f"ALTER TABLE peer_curation ADD COLUMN {col} TEXT")
        # v2.9: ⭐ is its own flag; a pre-v2.9 'cite' mark becomes Selected + Cited (idempotent)
        self.db.execute("UPDATE papers SET user_mark='selected', cited=1 WHERE user_mark='cite'")
        self.db.commit()
        self.fts = ensure_fts(self.db) if fts else False  # v3.0: papers_fts, created and filled once

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
        if old is not None and old["status"] in EXTERNAL:  # a peer's paper this radar found itself: now ours
            self.update(p["doi"], {**{k: v for k, v in p.items() if v and not old.get(k)},
                                   "status": status_if_new, "first_seen": p.get("first_seen") or date.today().isoformat()})
            return True
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

    def fts_search(self, query, limit=50, prefix=False, match=None):
        """Full-text search, best first: bm25 with title ×5, 🏷️ notes ×3, index terms ×2.5, authors ×2,
        abstract ×1 (FTS_WEIGHTS). `match` is a ready FTS5 query (fts_any). Each row also gets 'rank' (lower is
        better) and 'snip' (the abstract around the hit, matches in [brackets]). Without FTS5: every word must
        appear in the title, abstract, authors or note (LIKE), newest first."""
        if self.fts:
            q = match or fts_query(query, prefix)
            if not q:
                return []
            w = ", ".join(str(x) for x in FTS_WEIGHTS)
            try:
                rows = self.db.execute(
                    f"SELECT p.*, bm25(papers_fts, {w}) AS rank, snippet(papers_fts, 2, '[', ']', '…', 14) AS snip "
                    "FROM papers_fts JOIN papers p ON p.rowid = papers_fts.rowid WHERE papers_fts MATCH ? "
                    "ORDER BY rank LIMIT ?", (q, int(limit))).fetchall()
                return [self._row(r) for r in rows]
            except sqlite3.OperationalError:
                return []
        words = re.findall(r"[^\W_]+", query or "")[:8]
        if not words:
            return []
        cond = " AND ".join("(title LIKE ? OR abstract LIKE ? OR authors LIKE ? OR COALESCE(user_note,'') LIKE ?)"
                            for _ in words)
        args = [f"%{x}%" for x in words for _ in range(4)]
        rows = self.db.execute(f"SELECT *, 0 AS rank, '' AS snip FROM papers WHERE {cond} ORDER BY published DESC LIMIT ?",
                               (*args, int(limit))).fetchall()
        return [self._row(r) for r in rows]

    def counts(self):
        return dict(self.db.execute("SELECT status, COUNT(*) FROM papers GROUP BY status").fetchall())


COLS = {"doi", "title", "authors", "venue", "venue_name", "published", "abstract", "source", "article_number",
        "index_terms", "score", "hits", "status", "first_seen", "week", "refs", "oa_id", "cited_by",
        "ieee_cites", "keyrefs", "related", "digest", "digest_ver", *MIGRATIONS}


# ---------- sharing (v2.16): a clean copy for others, and merging someone else's store ----------

# the personal / radar-specific part of a row: curation, scoring and this radar's weekly state
PERSONAL_RESET = ("status='archive', week=NULL, catchup=NULL, user_mark='normal', cited=0, user_silicon=NULL, "
                  "user_note=NULL, pin=NULL, pillar=NULL, score=0, hits=NULL")
PILLAR_LINE = re.compile(r"^\s*-\s*\*\*Pillar:\*\*.*\n?", re.M)  # a digest's pillar names this radar's pillars
FORBIDDEN = re.compile(r"(?i)[A-Z]:\\Users\\|/Users/[^/\s]+/|/home/[^/\s]+/|radar_token")  # local user paths, the sync token file
# this radar's own arXiv preprints that the user has not selected or cited (left out of what it shares)
ARXIV_PRIVATE = ("doi LIKE '10.48550/arxiv.%' AND status != 'external' AND COALESCE(user_mark,'normal') != 'selected' "
                 "AND COALESCE(cited,0)=0")
# objective fields a merge may fill in when empty here (never curation, scores or this radar's weekly state)
OBJECTIVE = ("title", "authors", "venue", "venue_name", "published", "abstract", "source", "article_number",
             "index_terms", "refs", "oa_id", "keyrefs", "related", "lineage", "grp")
# bookkeeping a merge fills when empty here too: the date of the last lineage search (relations.py), so a
# collaborator does not repeat a search someone else already did
BOOKKEEPING = ("lineage_checked",)
# "nothing here" in a stored value; the share file keeps it as NULL, whichever radar wrote it
EMPTY = (None, "", "[]", "null")
EMPTY_TO_NULL = ("authors", "index_terms", "refs", "keyrefs", "related", "lineage", "abstract", "digest", "oa_id")
EXTERNAL = ("external", "external_ro")  # merged from someone else's store; external_ro: from a read-only repo
SETTLED = ("archive", *EXTERNAL)  # a merge may only move first_seen earlier on these (not on pending / skipped)
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _first_seen(value, today):
    """A first_seen worth taking over from another store: an ISO day, never later than today."""
    return value if isinstance(value, str) and ISO_DAY.match(value) and value <= today else None


def _strip_pillar(digest):
    return PILLAR_LINE.sub("", digest) if digest else digest


def export_clean_share_db(src_db_path, dst_db_path, include_curation=False, secrets=(), skip_arxiv=False):
    """The share database, from a read-only copy of src (SQLite backup API, safe while the radar runs):
    every row reset to an unmarked 'archive' paper (PERSONAL_RESET), digests without their **Pillar:** line,
    meta / api_usage / peer_curation emptied, VACUUM. Unadopted 'external_ro' rows (read_repos papers) are left out. Checked before it replaces dst (atomically, via .tmp):
    no personal column set, no Pillar line, empty meta, and no FORBIDDEN string or any of `secrets` (e.g. the
    sync token) in any text. include_curation=True keeps marks, notes, pillars, scores and meta (for a
    collaborator who should see them); the text check still runs. skip_arxiv=True leaves out this radar's own
    arXiv preprints unless selected or cited (arxiv_source.share_skip), but never one whose DOI the existing dst
    already has (a peer's shared preprint, adopted or found here too), so the export never shrinks below it.
    Returns {papers, digests, abstracts, bytes}."""
    dst = Path(dst_db_path)
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.unlink(missing_ok=True)
    shared = []  # arXiv DOIs the existing share file already has: kept by skip_arxiv
    if skip_arxiv and dst.exists():
        old = sqlite3.connect(f"file:{dst.as_posix()}?mode=ro", uri=True)
        try:
            shared = [(r[0],) for r in old.execute("SELECT doi FROM papers WHERE doi LIKE '10.48550/arxiv.%'")]
        except sqlite3.Error:
            pass
        finally:
            old.close()
    src = sqlite3.connect(f"file:{Path(src_db_path).as_posix()}?mode=ro", uri=True)
    try:
        out = sqlite3.connect(tmp)
        src.backup(out)
        out.close()
    finally:
        src.close()
    try:
        s = Store(tmp, fts=False)  # migrates an older store (adds user_note …) so the reset covers every column
        db = s.db
        drop_fts(db)  # v3.0: the share file is a plain papers table (no FTS index), readable by v2.19 radars
        # v3.0.3: papers merged only from a read_repos entry (someone else's repo) and not adopted stay theirs
        db.execute("DELETE FROM papers WHERE status='external_ro'")
        db.execute("DELETE FROM api_usage")
        db.execute("DELETE FROM peer_curation")
        if skip_arxiv:
            db.execute("CREATE TEMP TABLE shared (doi TEXT PRIMARY KEY)")
            db.executemany("INSERT OR IGNORE INTO shared VALUES (?)", shared)
            db.execute(f"DELETE FROM papers WHERE {ARXIV_PRIVATE} AND doi NOT IN (SELECT doi FROM shared)")
        if not include_curation:
            db.execute(f"UPDATE papers SET {PERSONAL_RESET}")
            for doi, d in db.execute("SELECT doi, digest FROM papers WHERE digest LIKE '%**Pillar:**%'").fetchall():
                db.execute("UPDATE papers SET digest=? WHERE doi=?", (_strip_pillar(d), doi))
            db.execute("DELETE FROM meta")
        for c in EMPTY_TO_NULL:  # one canonical empty (NULL), so radars that stored '[]' or '' export the same file
            db.execute(f"UPDATE papers SET {c}=NULL WHERE {c} IS NOT NULL AND TRIM({c}) IN ('', '[]', 'null')")
        db.commit()
        db.execute("VACUUM")
        problems = []
        if not include_curation:
            n = db.execute(f"SELECT COUNT(*) FROM papers WHERE NOT (status='archive' AND week IS NULL AND catchup IS NULL "
                           "AND user_mark='normal' AND cited=0 AND user_silicon IS NULL AND user_note IS NULL AND pin IS NULL "
                           "AND pillar IS NULL AND score=0 AND hits IS NULL) OR digest LIKE '%**Pillar:**%'").fetchone()[0]
            m = db.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
            if n or m:
                problems.append(f"{n} rows still personal, {m} meta rows")
        bad = [x for x in secrets if x]
        cols = [r[1] for r in db.execute("PRAGMA table_info(papers)") if r[2].upper() == "TEXT"]
        for row in db.execute(f"SELECT doi, {', '.join(cols)} FROM papers"):
            text = "\n".join(str(v) for v in row[1:] if v)
            hit = FORBIDDEN.search(text) or next((x for x in bad if x in text), None)
            if hit:
                problems.append(f"personal string in {row[0]}")
                break
        if problems:
            raise RuntimeError("share database not written: " + "; ".join(problems))
        stats = {"papers": db.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
                 "digests": db.execute("SELECT COUNT(*) FROM papers WHERE COALESCE(digest,'')!=''").fetchone()[0],
                 "abstracts": db.execute("SELECT COUNT(*) FROM papers WHERE COALESCE(abstract,'')!=''").fetchone()[0]}
        db.close()
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dst)
        return {**stats, "bytes": dst.stat().st_size}
    except BaseException:
        try:
            s.db.close()
        except Exception:
            pass
        tmp.unlink(missing_ok=True)
        raise


def merge_store(store, other_db_path, peer=None, log=print, read_only=False):
    """Bring another researcher's store into this one, one row per DOI (no duplicates):
    - a DOI already here: only empty objective fields (OBJECTIVE) and an empty lineage_checked are filled, the
      larger citation counts are kept, and a missing digest is taken without its **Pillar:** line. first_seen
      only ever moves earlier (the other store saw it first), and only on 'archive' / 'external' rows.
      Curation, scores, pillars, notes and the weekly state here are never touched;
    - a new DOI: inserted as status 'external' (unmarked, score 0) with the other store's first_seen and
      lineage_checked: searchable by --topic / --recall and used for relations, but never pulled into this
      radar's pillars (pillar_replenish reads 'archive') or board;
    - with peer: the other store's own curation (marks, ⭐, notes, chosen pillars) is kept in peer_curation
      under that name (dormant: nothing shows it yet). Without peer it is ignored.
    - read_only (v3.0.3, a data_repo.read_repos entry): new DOIs come in as 'external_ro' (kept out of exports
      until adopted). Without it (the primary shared repo, --merge-store), an 'external_ro' row whose DOI the
      other store has too becomes 'external', so a paper of the primary corpus always goes back out.
    The other file is opened read-only. Returns {'new', 'enriched', 'unchanged', 'peer_rows', 'promoted'}."""
    other = sqlite3.connect(f"file:{Path(other_db_path).as_posix()}?mode=ro", uri=True)
    other.row_factory = sqlite3.Row
    have = {r[1] for r in other.execute("PRAGMA table_info(papers)")}
    stats = {"new": 0, "enriched": 0, "unchanged": 0, "peer_rows": 0, "earlier": 0,  # earlier: first_seen moved back
             "promoted": 0}  # promoted: external_ro → external (the primary repo has it too)
    today = date.today().isoformat()
    try:
        for r in other.execute("SELECT * FROM papers"):
            o = store._row(r)
            doi = str(o.get("doi") or "").lower().strip()
            if not doi:
                continue
            mine = store.get(doi)
            digest = _strip_pillar(o.get("digest"))
            if mine is None:
                row = {k: o.get(k) for k in (*OBJECTIVE, *BOOKKEEPING) if o.get(k)}
                row.update({"status": "external_ro" if read_only else "external", "first_seen": _first_seen(o.get("first_seen"), today) or today,
                            "cited_by": o.get("cited_by"),
                            "ieee_cites": o.get("ieee_cites"), "digest": digest or None,
                            "digest_ver": o.get("digest_ver") if digest else None})
                store.update(doi, row, insert=True)
                stats["new"] += 1
            else:
                fill = {k: o[k] for k in (*OBJECTIVE, *BOOKKEEPING) if o.get(k) and not mine.get(k)}
                theirs, here = _first_seen(o.get("first_seen"), today), _first_seen(mine.get("first_seen"), today)
                if theirs and (not here or (theirs < here and mine.get("status") in SETTLED)):
                    fill["first_seen"] = theirs
                    stats["earlier"] += 1
                for k in ("cited_by", "ieee_cites"):
                    if (o.get(k) or 0) > (mine.get(k) or 0):
                        fill[k] = o[k]
                if digest and not mine.get("digest"):
                    fill.update(digest=digest, digest_ver=o.get("digest_ver"))
                if not read_only and mine.get("status") == "external_ro":
                    fill["status"] = "external"
                    stats["promoted"] += 1
                if fill:
                    store.update(doi, fill)
                stats["enriched" if set(fill) - {"first_seen", "status"} else "unchanged"] += 1  # a date alone isn't news
            if peer:
                cur = {k: o.get(k) if k in have else None
                       for k in ("user_mark", "cited", "user_note", "pillar", "score", "status", "user_silicon")}
                if (cur["user_mark"] or "normal") != "normal" or cur["cited"] or cur["user_note"] or cur["pillar"]:
                    store.db.execute(PEER_INSERT, (peer, doi, None if cur["pillar"] is None else str(cur["pillar"]),
                                                   cur["score"], cur["user_mark"] or "normal", int(bool(cur["cited"])),
                                                   cur["user_note"], cur["status"], cur["user_silicon"]))
                    stats["peer_rows"] += 1
        store.db.commit()
    finally:
        other.close()
    log(f"Merge {Path(other_db_path).name}: {stats['new']} new (status '{'external_ro' if read_only else 'external'}'), "
        f"{stats['enriched']} enriched, "
        f"{stats['unchanged']} unchanged" + (f", {stats['earlier']} first-seen dates moved earlier" if stats["earlier"] else "")
        + (f", {stats['peer_rows']} curation rows kept for peer '{peer}'" if peer else "")
        + (f", {stats['promoted']} read-only papers now shared (the primary repo has them)" if stats["promoted"] else ""))
    return stats


# ---------- peer overlays (v2.19): each collaborator's own radar, next to the shared corpus ----------

PEER_INSERT = ("INSERT OR REPLACE INTO peer_curation (peer_id, doi, pillar, score, user_mark, cited, user_note, status, "
               "user_silicon) VALUES (?,?,?,?,?,?,?,?,?)")
PRESET_RX = re.compile(r"^[a-z][a-z0-9_]{0,31}$")  # a domain_preset name in an overlay (presets.PRESETS key)
PEER_ID_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,38}$")  # also a file name: peers/<id>.json, Peers/DASHBOARD_<id>.html
OVERLAY_SQL = ("COALESCE(user_mark,'normal') != 'normal' OR cited = 1 OR COALESCE(user_note,'') != '' "
               "OR pillar IS NOT NULL OR score > 0")


def peer_overlay(store, peer_id, pillars, pillar_of, share_notes=True, skip_arxiv=False, domain_preset=None):
    """This radar's curation as a JSON-ready overlay for collaborators (peers/<peer_id>.json in the shared
    repo): its pillar names, and per DOI with any curation (a mark, ⭐, a note, a chosen pillar or a score > 0)
    the pillar (`pillar_of(row)`, the same rule the dashboard uses), score, stage, ⭐, Si call, note and status.
    Defaults are left out to keep the file small. share_notes=False keeps the 🏷️ notes private.
    skip_arxiv=True leaves out arXiv preprints the user has not selected or cited."""
    rows = {}
    for p in store.where(f"({OVERLAY_SQL}) AND NOT ({ARXIV_PRIVATE})" if skip_arxiv else OVERLAY_SQL):
        r = {"status": p.get("status")}
        k = 0 if p.get("grp") == "beyond" else pillar_of(p)
        if k:
            r["pillar"] = k
        if p.get("score"):
            r["score"] = p["score"]
        if (p.get("user_mark") or "normal") != "normal":
            r["user_mark"] = p["user_mark"]
        if p.get("cited"):
            r["cited"] = 1
        if p.get("user_silicon"):
            r["user_silicon"] = p["user_silicon"]
        if share_notes and p.get("user_note"):
            r["user_note"] = p["user_note"]
        if p.get("grp") == "beyond":
            r["beyond"] = 1
        rows[p["doi"]] = r
    out = {"format": 1, "peer_id": peer_id, "pillars": list(pillars), "custom_tags": [], "rows": rows}
    if domain_preset:  # v3.0.3: the peer page shows that radar's evidence badges (🧬 Wet-Lab … for a bio_med radar)
        out["domain_preset"] = domain_preset
    return out


def import_peer_overlay(store, overlay, peer_id):
    """Replace peer_id's rows in peer_curation with the overlay's, and keep its pillar names (and custom tags)
    in meta['peer_pillars:<peer_id>']. Never touches this radar's own papers. Returns the number of rows."""
    if not PEER_ID_RX.match(peer_id or ""):
        raise ValueError(f"bad peer id {peer_id!r}")
    rows = overlay.get("rows") or {}
    store.db.execute("DELETE FROM peer_curation WHERE peer_id=?", (peer_id,))
    store.db.executemany(PEER_INSERT, [
        (peer_id, str(doi).lower().strip(), str(r["pillar"]) if r.get("pillar") else None, r.get("score"),
         r.get("user_mark") or "normal", int(bool(r.get("cited"))), r.get("user_note"),
         "beyond" if r.get("beyond") else r.get("status"), r.get("user_silicon"))
        for doi, r in rows.items() if isinstance(r, dict)])
    store.db.commit()
    store.meta(f"peer_pillars:{peer_id}", {"pillars": [str(x) for x in overlay.get("pillars") or []],
                                           "custom_tags": overlay.get("custom_tags") or [],
                                           "updated": overlay.get("updated")})
    dp = overlay.get("domain_preset")  # v3.0.3; "" = not given (an older radar): its page keeps this radar's badges
    store.meta(f"peer_preset:{peer_id}", dp if isinstance(dp, str) and PRESET_RX.match(dp) else "")
    return len(rows)


def peer_ids(store):
    """Peers with rows in peer_curation (from --sync-data-repo or --merge-store --peer), sorted."""
    return [r[0] for r in store.db.execute("SELECT DISTINCT peer_id FROM peer_curation ORDER BY peer_id")
            if PEER_ID_RX.match(r[0] or "")]
