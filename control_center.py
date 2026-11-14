"""Setup & Radar Control Center (v2.21): STARTUP.html next to DASHBOARD.html, and the small local API behind it.

  python briefing.py --gui [PORT]   local server on http://127.0.0.1:18766 (another free port if that one is taken);
                                    opens STARTUP.html in the default browser. Ctrl+C stops it.
  Start_Radar_GUI.cmd / .command    the same by double-click (Starter Edition)
  radar_sync_server.py              serves the same /api/* on the Minisforum radar (X-Radar-Token, like /mark)

STARTUP.html is rewritten together with DASHBOARD.html (html_renderer.write_all). It shows a setup checklist (paper
store, pillars, IEEE key / claude CLI / contact e-mail as yes-no flags only), edits the research settings of
config.json (pillars, keywords, negative keywords, VIP authors, anchors, sharing, arXiv), shows the shared corpus
repo and its peers, and runs four fixed actions. Opened as a plain file it still shows all of that, saves the edited
config.json as a download and lists the commands to run; served by --gui or the sync server it runs them itself.

API (JSON):
  GET  /api/config        → {"ok", "editable", "status", "job"}: the editable settings and the read-only status
  POST /api/config        ← {"config": {...}}: validated, then only the changed keys are written into config.json
                            (unknown keys and the file's own layout are kept; the previous file goes to
                            _system/config.backup.json)
  POST /api/run           ← {"action": "rescore_and_seed" | "pull_data_repo" | "sync_data_repo" | "daily",
                             "config"?: {...}, "clone_url"?, "clone_dir"?}: saves the config, then runs briefing.py
                            in a background worker (one job at a time)
  GET  /api/job?since=N   → {"id", "running", "action", "rc", "lines": [...], "next"}: the job's output from line N
  GET  /api/active?since=B → {"active", "id", "what", "lines", "next"}: a run this server didn't start (07:00 task,
                            Friday sync, a terminal) from .run.log byte B (run_lock.py)
POST /api/run never overlaps a run: while one holds .run.lock (run_lock.py) it answers 409 {"error": "already_running",
"already_running": true, "job" | "active": …}, and the page streams that run instead.

Secrets never leave the machine: the status holds only booleans (has_ieee_key, has_claude), never a key's value.
The --gui server listens on 127.0.0.1 only and checks the Host header (no DNS rebinding). It needs a key made at
each launch: the launch link (/?k=<key>) stores it in an HttpOnly, SameSite=Strict cookie, and every /api call
must also carry the header X-Radar-GUI. It sends no CORS headers (except on /ping, which returns no data), so
another website can neither read its pages nor send it a request with that header.
"""
import http.cookies
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
STARTER = (HERE / "config_file.py").exists()  # Starter Edition (public repo); else the Minisforum radar
PAGE = "STARTUP.html"
GUI_PORT = 18766
DATA_URL = "https://github.com/jdong-p/ic-paper-radar-data.git"
MAX_PILLARS = 9

# editable field → its path in config.json ("data_repo" and "arxiv" are objects of such fields)
PATHS = {"pillars": ["pillars"], "pillar_short": ["pillar_short"], "positive_keywords": ["positive_keywords"],
         "negative_keywords": ["negative_keywords"], "negative_override": ["negative_override"],
         "key1_themes": ["beyond_ieee", "key1_themes"], "min_score": ["min_score"], "vip_authors": ["vip_authors"],
         "vip_boost": ["vip_boost"], "anchors": ["anchors"], "contact_email": ["contact_email"],
         "data_repo_dir": ["paths", "data_repo_dir"]}
DATA_REPO_KEYS = ("peer_id", "share_curation", "share_notes", "adopt_external")
ARXIV_KEYS = ("enabled", "share", "queries", "categories", "must_all", "exclude_any")
STARTER_ONLY = {"pillars", "pillar_short", "arxiv"}  # the Minisforum radar's pillars are fixed in catalog.py

DOI_RX = re.compile(r"^10\.\d{4,9}/[^\s\"<>]+$")
EMAIL_RX = re.compile(r"^[^@\s\"<>]+@[^@\s\"<>]+\.[A-Za-z]{2,}$")
ARXIV_CAT_RX = re.compile(r"^[a-z-]+(\.[A-Za-z-]+)?$")
MARKER_RX = re.compile(r"^_pillar(\d+)")
# a clone URL without user info (no token can end up in .git/config); the repo name must be the data repo's
CLONE_RX = re.compile(r"^(https://[A-Za-z0-9.-]+(:\d+)?/|git@[A-Za-z0-9.-]+:)[\w.-]+/[\w.-]+?(\.git)?/?$")
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW: no console flashes under pythonw


# ---------- config.json: read, validate, write only what changed ----------

def raw_config():
    """config.json exactly as stored (Starter Edition: created from config.example.json first if missing)."""
    if STARTER:
        import config_file
        config_file.ensure()
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def load_cfg():
    import fetcher
    return fetcher.load_config()


def editable(cfg):
    """The fields STARTUP.html edits, from the effective config (Starter: config.json over the template)."""
    import catalog
    dr, ax = cfg.get("data_repo") or {}, cfg.get("arxiv") or {}
    ks = sorted(k for k in catalog.PILLARS if k)
    out = {"pillars": list(cfg.get("pillars") or []) if STARTER else [catalog.PILLARS[k] for k in ks],
           "pillar_short": (list(cfg.get("pillar_short") or []) if STARTER
                            else [getattr(catalog, "PILLAR_SHORT", {}).get(k, "") for k in ks]),
           "positive_keywords": [[k, v] for k, v in (cfg.get("positive_keywords") or {}).items()],
           "negative_keywords": list(cfg.get("negative_keywords") or []),
           "negative_override": cfg.get("negative_override") or "",
           "key1_themes": list((cfg.get("beyond_ieee") or {}).get("key1_themes") or []),
           "min_score": cfg.get("min_score", 5), "vip_authors": list(cfg.get("vip_authors") or []),
           "vip_boost": cfg.get("vip_boost", 3), "anchors": list(cfg.get("anchors") or []),
           "contact_email": cfg.get("contact_email") or "",
           "data_repo": {"peer_id": dr.get("peer_id") or "", "share_curation": dr.get("share_curation", True) is not False,
                         "share_notes": dr.get("share_notes", True) is not False,
                         "adopt_external": dr.get("adopt_external", True) is not False},
           "data_repo_dir": (cfg.get("paths") or {}).get("data_repo_dir") or ""}
    if STARTER:
        out["arxiv"] = {k: ax.get(k, False if k in ("enabled", "share") else []) for k in ARXIV_KEYS}
    return out


def _texts(v, what, maxn=2000, maxlen=300, dedupe=True, allow_empty=False):
    if not isinstance(v, list) or len(v) > maxn:
        raise ValueError(f"{what}: expected a list of at most {maxn} texts")
    out = []
    for x in v:
        if not isinstance(x, str) or "\n" in x or "\r" in x or len(x.strip()) > maxlen:
            raise ValueError(f"{what}: {str(x)[:40]!r} is not a one-line text of at most {maxlen} characters")
        x = x.strip()
        if not x and not allow_empty:
            continue
        if not dedupe or x not in out:
            out.append(x)
    return out


def _num(v, what, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ValueError(f"{what}: expected a number from {lo} to {hi}")
    return int(v) if float(v).is_integer() else float(v)


def _bool(v, what):
    if not isinstance(v, bool):
        raise ValueError(f"{what}: expected true or false")
    return v


def _fail(msg):
    raise ValueError(msg)


def _regex(s, what):
    try:
        re.compile(s)
    except re.error as e:
        raise ValueError(f"{what}: not a valid regular expression ({e})")
    return s


def _keywords(v):
    """[[key, weight], …] in the order shown (pillar headings _pillarN_… included) → an ordered dict."""
    if not isinstance(v, list) or len(v) > 3000:
        raise ValueError("positive_keywords: expected a list of [keyword, weight] pairs")
    out = {}
    for item in v:
        if not (isinstance(item, list) and len(item) == 2 and isinstance(item[0], str)):
            raise ValueError("positive_keywords: every entry must be [keyword, weight]")
        k = item[0].strip()
        if not k or len(k) > 300 or "\n" in k:
            raise ValueError(f"positive_keywords: {k[:40]!r} is empty, too long or has a line break")
        if k in out:
            raise ValueError(f"positive_keywords: {k!r} appears twice (a keyword belongs to one pillar)")
        w = _num(item[1], f"positive_keywords[{k!r}] weight", -50, 50)
        if k.startswith("re:"):
            label, sep, rx = k[3:].partition("::")
            if not (sep and label.strip() and rx):
                raise ValueError(f"positive_keywords: {k!r} must look like re:<label>::<regex>")
            _regex(rx, f"positive_keywords[{label}]")
        out[k] = 0 if MARKER_RX.match(k) else w
    return out


def validate(upd, cfg):
    """STARTUP.html's fields → [(config path, value)], or ValueError listing every problem."""
    if not isinstance(upd, dict):
        raise ValueError("config must be a JSON object")
    errs, out = [], []

    def put(path, fn):
        try:
            out.append((path, fn()))
        except ValueError as e:
            errs.append(str(e))

    n_pillars = len(upd["pillars"]) if STARTER and isinstance(upd.get("pillars"), list) else len(cfg.get("pillars") or [])
    for k, v in upd.items():
        if k in STARTER_ONLY and not STARTER:
            errs.append(f"{k}: fixed on this radar (catalog.py), not editable here")
        elif k == "pillars":
            def pillars(v=v):
                names = _texts(v, "pillars", maxn=MAX_PILLARS, maxlen=120, dedupe=False)
                if len(set(n.lower() for n in names)) < len(names):
                    raise ValueError("pillars: two pillars have the same name")
                return names
            put(PATHS[k], pillars)
        elif k == "pillar_short":
            def short(v=v):
                s = _texts(v, "pillar_short", maxn=MAX_PILLARS, maxlen=24, dedupe=False, allow_empty=True)
                if len(s) > n_pillars:
                    raise ValueError("pillar_short: more labels than pillars")
                while s and not s[-1]:
                    s.pop()
                return s
            put(PATHS[k], short)
        elif k == "positive_keywords":
            put(PATHS[k], lambda v=v: _keywords(v))
        elif k in ("negative_keywords", "key1_themes", "vip_authors"):
            put(PATHS[k], lambda v=v, k=k: _texts(v, k, maxlen=200))
        elif k == "negative_override":
            put(PATHS[k], lambda v=v: _regex(v.strip(), "negative_override") if isinstance(v, str) and "\n" not in v
                else _fail("negative_override: expected a one-line regular expression"))
        elif k in ("min_score", "vip_boost"):
            put(PATHS[k], lambda v=v, k=k: _num(v, k, 0, 1000 if k == "min_score" else 50))
        elif k == "anchors":
            def anchors(v=v):
                dois = _texts(v, "anchors", maxn=500, maxlen=200)
                bad = [d for d in dois if not DOI_RX.match(d)]
                if bad:
                    raise ValueError(f"anchors: not a DOI: {', '.join(bad[:3])}")
                return dois
            put(PATHS[k], anchors)
        elif k == "contact_email":
            put(PATHS[k], lambda v=v: v.strip() if isinstance(v, str) and (not v.strip() or EMAIL_RX.match(v.strip()))
                else _fail("contact_email: not an e-mail address"))
        elif k == "data_repo_dir":
            put(PATHS[k], lambda v=v: v.strip() if isinstance(v, str) and len(v) < 500 and not re.search(r"[\r\n\0]", v)
                else _fail("data_repo_dir: expected a folder path"))
        elif k == "data_repo":
            if not isinstance(v, dict):
                errs.append("data_repo: expected an object")
                continue
            for kk, vv in v.items():
                if kk == "peer_id":
                    import store as store_mod
                    put(["data_repo", kk], lambda vv=vv: vv.strip() if isinstance(vv, str) and (
                        not vv.strip() or store_mod.PEER_ID_RX.match(vv.strip())) else _fail(
                            "data_repo.peer_id: letters, digits, '.', '_' or '-' (≤ 39), starting with a letter or digit"))
                elif kk in DATA_REPO_KEYS:
                    put(["data_repo", kk], lambda vv=vv, kk=kk: _bool(vv, f"data_repo.{kk}"))
                else:
                    errs.append(f"data_repo.{kk}: not editable here")
        elif k == "arxiv":
            if not isinstance(v, dict):
                errs.append("arxiv: expected an object")
                continue
            for kk, vv in v.items():
                if kk in ("enabled", "share"):
                    put(["arxiv", kk], lambda vv=vv, kk=kk: _bool(vv, f"arxiv.{kk}"))
                elif kk in ("queries", "exclude_any"):
                    put(["arxiv", kk], lambda vv=vv, kk=kk: _texts(vv, f"arxiv.{kk}", maxn=50, maxlen=500))
                elif kk == "categories":
                    def cats(vv=vv):
                        c = _texts(vv, "arxiv.categories", maxn=40, maxlen=30)
                        bad = [x for x in c if not ARXIV_CAT_RX.match(x)]
                        if bad:
                            raise ValueError(f"arxiv.categories: not an arXiv category: {', '.join(bad[:3])}")
                        return c
                    put(["arxiv", kk], cats)
                elif kk == "must_all":
                    def groups(vv=vv):
                        if not isinstance(vv, list) or len(vv) > 10:
                            raise ValueError("arxiv.must_all: expected up to 10 groups of terms")
                        g = [_texts(x, "arxiv.must_all group", maxn=100, maxlen=100) for x in vv]
                        return [x for x in g if x]
                    put(["arxiv", kk], groups)
                else:
                    errs.append(f"arxiv.{kk}: not editable here")
        else:
            errs.append(f"{k}: not an editable setting")
    if errs:
        raise ValueError("; ".join(errs))
    return out


MISSING = object()


def _get(obj, path):
    for k in path:
        if not isinstance(obj, dict) or k not in obj:
            return MISSING
        obj = obj[k]
    return obj


def _set(obj, path, value):
    for k in path[:-1]:
        obj = obj.setdefault(k, {})
    obj[path[-1]] = value


def _same(a, b):
    """Equal including the order of dict keys (moving a keyword to another pillar heading is a change)."""
    return a is not MISSING and json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)


def _dump_style(raw, text):
    """(indent, ensure_ascii) when the file is exactly json.dumps output (a fresh Starter config.json), else None."""
    t = text.replace("\r\n", "\n")
    for indent in (4, 2):
        for ea in (True, False):
            s = json.dumps(raw, indent=indent, ensure_ascii=ea)
            if t in (s, s + "\n"):
                return indent, ea
    return None


_WS = re.compile(r"\s*")


def _members(text, start):
    """The members of the JSON object whose '{' is at `start`: [(key, key_start, value_start, value_end)], close."""
    dec, out = json.JSONDecoder(), []
    i = _WS.match(text, start + 1).end()
    if text[i] == "}":
        return out, i
    while True:
        ks = i
        key, i = dec.raw_decode(text, i)
        i = _WS.match(text, i).end()
        if text[i] != ":":
            raise ValueError("config.json: unexpected layout")
        vs = _WS.match(text, i + 1).end()
        _, ve = dec.raw_decode(text, vs)
        out.append((key, ks, vs, ve))
        i = _WS.match(text, ve).end()
        if text[i] == ",":
            i = _WS.match(text, i + 1).end()
            continue
        if text[i] != "}":
            raise ValueError("config.json: unexpected layout")
        return out, i


def _col(text, pos):
    return pos - (text.rfind("\n", 0, pos) + 1)


def _lines(tokens, width):
    """tokens joined by ', ' into lines of at most `width` characters."""
    lines, cur = [], ""
    for t in tokens:
        if cur and len(cur) + 2 + len(t) > width:
            lines.append(cur)
            cur = ""
        cur = f"{cur}, {t}" if cur else t
    return lines + [cur] if cur else lines


def _fmt(value, indent, col, width=118):
    """A JSON value laid out like the hand-written config.json: short values on one line, long lists wrapped,
    positive_keywords as one paragraph per pillar heading (_pillarN_… on its own line)."""
    dumps = lambda x: json.dumps(x, ensure_ascii=False)
    one, inner = dumps(value), indent + "  "
    avail = max(width - len(inner), 40)
    if isinstance(value, dict) and value:
        marked = any(MARKER_RX.match(k) for k in value)
        if col + len(one) <= width and not marked:
            return one
        paras, cur = [], []
        for k, v in value.items():
            if MARKER_RX.match(k) and cur:
                paras.append(cur)
                cur = []
            cur.append((k, f"{dumps(k)}: {dumps(v)}"))
        paras.append(cur)
        out = []
        for n, para in enumerate(paras):
            head = [para[0][1]] if MARKER_RX.match(para[0][0]) else []
            out += ([""] if n else []) + head + _lines([t for _, t in para[len(head):]], avail)
        last = max(i for i, ln in enumerate(out) if ln)
        body = "\n".join(inner + ln + ("," if i != last else "") if ln else "" for i, ln in enumerate(out))
        return "{\n" + body + "\n" + indent + "}"
    if isinstance(value, list) and value and col + len(one) > width:
        body = ",\n".join(inner + ln for ln in _lines([dumps(x) for x in value], avail))
        return "[\n" + body + "\n" + indent + "]"
    return one


def _paragraphs(items):
    """[(key, value)] split at the pillar headings: each _pillarN_… key starts a new paragraph."""
    out = []
    for k, v in items:
        if MARKER_RX.match(k) or not out:
            out.append([])
        out[-1].append((k, v))
    return out


def _fmt_paragraphs(text, vs, value, indent):
    """positive_keywords with every paragraph (pillar heading + its keywords) that didn't change kept exactly as
    it was written, so adding one keyword shows up as a change to that pillar only."""
    members, _ = _members(text, vs)
    old = {}
    for para in _paragraphs([(k, (ks, s, e)) for k, ks, s, e in members]):
        sig = json.dumps([(k, json.loads(text[s:e])) for k, (_, s, e) in para], ensure_ascii=False)
        old.setdefault(sig, text[para[0][1][0]:para[-1][1][2]])
    inner = indent + "  "
    blocks = []
    for para in _paragraphs(list(value.items())):
        sig = json.dumps(para, ensure_ascii=False)
        if sig in old:
            blocks.append(old[sig])
            continue
        toks = [f"{json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}" for k, v in para]
        head = toks[:1] if MARKER_RX.match(para[0][0]) else []
        lines = head + _lines(toks[len(head):], max(118 - len(inner), 40))
        blocks.append((",\n" + inner).join(lines))
    return "{\n" + inner + (",\n\n" + inner).join(blocks) + "\n" + indent + "}"


def patch_text(text, path, value):
    """config.json text with the value at `path` replaced (or the member added), everything else byte for byte."""
    m = re.search(r"\{", text)
    start = m.start()
    for depth, key in enumerate(path):
        members, close = _members(text, start)
        hit = next((x for x in members if x[0] == key), None)
        if hit is None:
            sub = value
            for k in reversed(path[depth + 1:]):
                sub = {k: sub}
            if members:
                ks, ve = members[-1][1], members[-1][3]
                indent = " " * _col(text, ks)
                if text.rfind("\n", 0, ks) < start:  # all members on the '{' line: next one on a new line
                    indent = " " * (_col(text, start) + 2)
                ins = f",\n{indent}{json.dumps(key, ensure_ascii=False)}: {_fmt(sub, indent, len(indent) + len(key) + 4)}"
                return text[:ve] + ins + text[ve:]
            indent = " " * (_col(text, start) + 2)
            ins = f"\n{indent}{json.dumps(key, ensure_ascii=False)}: {_fmt(sub, indent, len(indent) + len(key) + 4)}\n" \
                  + " " * _col(text, start)
            return text[:start + 1] + ins + text[close:]
        _, ks, vs, ve = hit
        if depth == len(path) - 1:
            indent = " " * _col(text, ks)
            if isinstance(value, dict) and value and text[vs] == "{" and any(MARKER_RX.match(k) for k in value):
                return text[:vs] + _fmt_paragraphs(text, vs, value, indent) + text[ve:]
            return text[:vs] + _fmt(value, indent, _col(text, vs)) + text[ve:]
        if text[vs] != "{":
            raise ValueError(f"config.json: {'.'.join(path[:depth + 1])} is not an object")
        start = vs


def write_config(changes, cfg=None):
    """Write [(path, value)] into config.json; returns the dotted paths that really changed. Only those values are
    rewritten (a json.dumps-formatted file is re-dumped in its own style), so unknown keys, comments-as-keys and a
    hand-made layout survive. The previous file goes to _system/config.backup.json."""
    with open(CONFIG, encoding="utf-8", newline="") as fh:
        text = fh.read()
    raw = json.loads(text)
    todo = [(p, v) for p, v in changes if not _same(_get(raw, p), v)]
    if not todo:
        return []
    crlf = "\r\n" in text
    style = _dump_style(raw, text)
    if style:
        for p, v in todo:
            _set(raw, p, v)
        new = json.dumps(raw, indent=style[0], ensure_ascii=style[1]) + "\n"
    else:
        new = text.replace("\r\n", "\n")
        for p, v in todo:
            new = patch_text(new, p, v)
    check = json.loads(new)
    if any(not _same(_get(check, p), v) for p, v in todo):
        raise RuntimeError("config.json not written: the edited file did not read back the same")
    if crlf:
        new = new.replace("\r\n", "\n").replace("\n", "\r\n")
    try:
        import curation
        (curation.system_dir(cfg or load_cfg()) / "config.backup.json").write_text(text, encoding="utf-8", newline="")
    except Exception:
        pass
    tmp = CONFIG.with_name("config.json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(new)
    os.replace(tmp, CONFIG)
    return [".".join(p) for p, _ in todo]


# ---------- read-only status (booleans only for secrets) ----------

def _ro(path):
    """Read-only, and patient while a run or a click writes (the store is never created or locked by the page)."""
    return sqlite3.connect(f"file:{urllib.parse.quote(Path(path).as_posix(), safe='/:')}?mode=ro", uri=True, timeout=10)


def store_status(cfg):
    sp = HERE / cfg["paths"]["store_file"]
    out = {"file": sp.name, "exists": sp.exists(), "papers": 0, "by_status": {}, "candidates": 0, "external": 0,
           "selected": 0, "cited": 0, "notes": 0, "anchors": {}}
    if not sp.exists():
        return out
    c = _ro(sp)
    try:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='papers'").fetchone():
            return out
        by = dict(c.execute("SELECT COALESCE(status,'?'), COUNT(*) FROM papers GROUP BY status").fetchall())
        cols = {r[1] for r in c.execute("PRAGMA table_info(papers)")}
        out.update(papers=sum(by.values()), by_status=by, candidates=by.get("candidate", 0), external=by.get("external", 0))
        one = lambda sql: c.execute(sql).fetchone()[0]
        if "user_mark" in cols:
            out["selected"] = one("SELECT COUNT(*) FROM papers WHERE user_mark='selected'")
        if "cited" in cols:
            out["cited"] = one("SELECT COUNT(*) FROM papers WHERE cited=1")
        if "user_note" in cols:
            out["notes"] = one("SELECT COUNT(*) FROM papers WHERE TRIM(COALESCE(user_note,''))<>''")
        dois = [str(d).lower() for d in cfg.get("anchors") or []]
        if dois:
            pin = "pin" if "pin" in cols else "NULL"
            q = f"SELECT doi, title, venue, published, {pin} FROM papers WHERE lower(doi) IN ({','.join('?' * len(dois))})"
            for d, t, v, pub, p in c.execute(q, dois):
                out["anchors"][str(d).lower()] = {"title": t, "venue": v, "year": (pub or "")[:4], "pin": p}
    finally:
        c.close()
    return out


def data_repo_status(cfg):
    import data_repo
    import store as store_mod
    repo = data_repo.repo_dir(cfg)
    out = {"dir": str(repo), "custom_dir": bool((cfg.get("paths") or {}).get("data_repo_dir")), "connected": False,
           "reason": "", "papers": 0, "missing_here": None, "commit": None, "peers": [], "me": "",
           "default_dir": str(HERE.parent / data_repo.REMOTE_MARK)}
    try:
        why = data_repo.check_clone(repo)
    except RuntimeError as e:
        why = str(e)
    out["reason"], out["connected"] = why or "", not why
    root = Path(cfg["paths"]["onedrive_root"])
    seen = {}
    if not why:
        out["me"] = data_repo.peer_id(cfg, repo)
        r = data_repo._git(repo, "log", "-1", "--format=%h%x09%cI%x09%s", check=False)
        parts = r.stdout.strip().split("\t", 2)
        if len(parts) == 3:
            out["commit"] = {"hash": parts[0], "date": parts[1], "subject": parts[2][:160]}
        db = repo / data_repo.DB_NAME
        if db.exists():
            out["papers"] = data_repo._count(db)
            sp = HERE / cfg["paths"]["store_file"]
            if sp.exists():
                c = _ro(sp)
                try:
                    c.execute("ATTACH DATABASE ? AS s",
                              (f"file:{urllib.parse.quote(db.as_posix(), safe='/:')}?mode=ro",))
                    out["missing_here"] = c.execute("SELECT COUNT(*) FROM s.papers WHERE lower(doi) NOT IN "
                                                    "(SELECT lower(doi) FROM main.papers)").fetchone()[0]
                except sqlite3.Error:
                    pass
                finally:
                    c.close()
        for f in sorted((repo / data_repo.PEERS_DIR).glob("*.json")):
            if not store_mod.PEER_ID_RX.match(f.stem):
                continue
            try:
                ov = json.loads(f.read_text(encoding="utf-8"))
                rows = ov.get("rows") or {}
                seen[f.stem] = {"id": f.stem, "rows": len(rows), "updated": str(ov.get("updated") or "")[:19],
                                "pillars": [str(x)[:80] for x in (ov.get("pillars") or [])][:MAX_PILLARS],
                                "me": f.stem == out["me"],
                                "selected": sum(1 for r in rows.values() if r.get("user_mark") == "selected"),
                                "cited": sum(1 for r in rows.values() if r.get("cited"))}
            except (OSError, ValueError, AttributeError):
                continue
    else:
        out["me"] = data_repo.peer_id(cfg, None)
    for f in sorted((root / "Peers").glob("DASHBOARD_*.html")) if (root / "Peers").exists() else []:
        pid = f.stem[len("DASHBOARD_"):]
        seen.setdefault(pid, {"id": pid, "rows": None, "updated": "", "pillars": [], "me": False})
    for p in seen.values():
        page = root / "Peers" / f"DASHBOARD_{p['id']}.html"
        p["href"] = f"Peers/DASHBOARD_{p['id']}.html" if page.exists() else None
    out["peers"] = sorted(seen.values(), key=lambda p: (not p["me"], p["id"].lower()))
    return out


def has_claude(cfg):
    return shutil.which((cfg.get("claude") or {}).get("command") or "claude") is not None


def status(cfg):
    import fetcher
    try:
        st = store_status(cfg)
    except sqlite3.Error as e:
        st = {"file": cfg["paths"]["store_file"], "exists": True, "papers": 0, "by_status": {}, "candidates": 0,
              "external": 0, "selected": 0, "cited": 0, "notes": 0, "anchors": {}, "error": str(e)}
    pk = cfg.get("positive_keywords") or {}
    n_kw = sum(1 for k, w in pk.items() if not k.startswith("_") and w)
    ready = fetcher.pillars_ready(cfg) if hasattr(fetcher, "pillars_ready") else bool(n_kw)
    try:
        dr = data_repo_status(cfg)
    except Exception as e:  # never let the status page fail on the optional repo
        dr = {"dir": "", "connected": False, "reason": f"status not available: {e}", "papers": 0, "peers": [],
              "me": "", "commit": None, "missing_here": None, "custom_dir": False, "default_dir": ""}
    import catalog
    return {"edition": "starter" if STARTER else "radar", "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "store": st, "pillars": {"count": len([k for k in catalog.PILLARS if k]), "ready": bool(ready),
                                     "keywords": n_kw},
            "env": {"has_ieee_key": bool(os.environ.get("IEEE_API_KEY", "").strip()), "has_claude": has_claude(cfg),
                    "claude_command": (cfg.get("claude") or {}).get("command") or "claude",
                    "has_git": shutil.which("git") is not None,
                    "contact_email_set": bool(EMAIL_RX.match((cfg.get("contact_email") or "").strip()))},
            "data_repo": dr,
            "sharing": {"selected": st["selected"], "cited": st["cited"], "notes": st["notes"],
                        "share_curation": (cfg.get("data_repo") or {}).get("share_curation", True) is not False,
                        "share_notes": (cfg.get("data_repo") or {}).get("share_notes", True) is not False}}


# ---------- the four actions, one at a time, in a background worker ----------

ACTIONS = {"rescore_and_seed": "▶ Run & Update My Dashboard", "pull_data_repo": "📥 Read from Private Repo",
           "sync_data_repo": "🔄 Full Sync with Private Repo", "daily": "🌐 Fetch New Papers Now"}


def plan(action, cfg):
    """briefing.py argument lists for an action (run in order; a failed step doesn't stop the next one).
    Run & Update first adopts the merged ('external') papers that score ≥ min_score with the keywords just saved
    (data_repo.adopt_external), so a collaborator who read the shared corpus before setting pillars gets them."""
    adopt = [["--adopt-external"]] if (cfg.get("data_repo") or {}).get("adopt_external", True) is not False else []
    return {"rescore_and_seed": adopt + [["--rescore", "--seed-pillars", "5", "--no-claude"]],
            "pull_data_repo": [["--pull-data-repo"]],
            "sync_data_repo": [["--sync"], ["--sync-data-repo"]],
            "daily": [[] if has_claude(cfg) else ["--no-claude"]]}[action]


def python_exe():
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))  # the sync server runs under pythonw: children need a stdout
    return str(exe)


def python_hint():
    if STARTER:
        return "python3" if sys.platform == "darwin" else "python"
    try:
        import env_guard
        return f'"{env_guard.MINISFORUM_PYTHON}"'
    except Exception:
        return "python"


def commands(cfg):
    """The same actions as command lines, for the static page (copy & paste)."""
    py = python_hint()
    return {a: [f"{py} briefing.py {' '.join(args)}".rstrip() for args in plan(a, cfg)] for a in ACTIONS}


class Jobs:
    """One background job at a time; its output lines are kept for GET /api/job."""

    def __init__(self):
        self.lock = threading.Lock()
        self.n = 0
        self.child = None  # pid of the briefing.py this worker is running now
        self.st = {"id": 0, "action": None, "running": False, "rc": None, "lines": [], "base": 0,
                   "started": None, "finished": None}

    def view(self, since=0):
        with self.lock:
            st = self.st
            i = max(int(since) - st["base"], 0)
            return {k: st[k] for k in ("id", "action", "running", "rc", "started", "finished")} | {
                "label": ACTIONS.get(st["action"] or "", ""), "lines": st["lines"][i:],
                "next": st["base"] + len(st["lines"])}

    def log(self, line):
        with self.lock:
            self.st["lines"].append(str(line).rstrip("\r\n")[:4000])
            if len(self.st["lines"]) > 4000:
                del self.st["lines"][:1000]
                self.st["base"] += 1000

    def start(self, action, opts=None):
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        with self.lock:
            if self.st["running"]:
                raise RuntimeError(f"busy: {ACTIONS[self.st['action']]} is still running")
            self.n += 1
            self.st = {"id": self.n, "action": action, "running": True, "rc": None, "lines": [], "base": 0,
                       "started": datetime.now().isoformat(timespec="seconds"), "finished": None}
        threading.Thread(target=self._run, args=(action, opts or {}), daemon=True).start()
        return self.view()

    def _proc(self, cmd, show):
        self.log(f"$ {show}")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", GIT_TERMINAL_PROMPT="0")
        p = subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", env=env, creationflags=NO_WINDOW)
        self.child = p.pid
        try:
            for line in p.stdout:
                self.log(line)
            return p.wait()
        finally:
            self.child = None

    def _clone(self, opts):
        import data_repo
        url = str(opts.get("clone_url") or "").strip()
        if not CLONE_RX.match(url) or data_repo.REMOTE_MARK not in url:
            raise ValueError(f"not a clone URL of {data_repo.REMOTE_MARK} (https://… or git@…, no user name or token)")
        cfg = load_cfg()
        d = str(opts.get("clone_dir") or "").strip()
        target = Path(d).expanduser() if d else data_repo.repo_dir(cfg)
        if not target.is_absolute():
            target = HERE / target
        target = target.resolve()
        if target.exists() and any(target.iterdir()):
            why = data_repo.check_clone(target)
            if why:
                raise ValueError(f"{target} exists and is not a clone of {data_repo.REMOTE_MARK}: choose another folder")
            self.log(f"Already cloned: {target}")
        else:
            rc = self._proc(["git", "clone", "--", url, str(target)], f"git clone {url} {target}")
            if rc:
                self.log("git clone failed: check the URL and that your GitHub account can read the repo "
                         "(on Windows, Git Credential Manager asks you to sign in once)")
                return rc
        if target != data_repo.repo_dir(cfg).resolve():
            write_config([(["paths", "data_repo_dir"], str(target))], cfg)
            self.log(f"config.json: paths.data_repo_dir = {target}")
        return 0

    def _run(self, action, opts):
        rc = 0
        try:
            if action == "pull_data_repo" and opts.get("clone_url"):
                rc = self._clone(opts)
            if not rc:
                for args in plan(action, load_cfg()):
                    r = self._proc([python_exe(), "-u", str(HERE / "briefing.py"), *args],
                                   f"python briefing.py {' '.join(args)}".rstrip())
                    rc = r or rc  # like run_data_repo_sync.cmd: the last failure's code, else 0
                    self.log(f"(exit {r})")
        except Exception as e:
            self.log(f"[ERROR] {e}")
            rc = 1
        finally:
            with self.lock:
                self.st.update(running=False, rc=rc, finished=datetime.now().isoformat(timespec="seconds"))
            try:
                write_startup(load_cfg(), log=lambda m: None)  # the status on the static page, after the job
            except Exception:
                pass


def _save(req):
    cfg = load_cfg()
    changed = write_config(validate(req.get("config") or {}, cfg), cfg) if req.get("config") else []
    if changed:
        cfg = load_cfg()
        try:
            write_startup(cfg, log=lambda m: None)
        except Exception:
            pass
    return cfg, changed


def external_run(jobs):
    """The run holding .run.lock when it isn't this server's own job: {id, what, pid, args, started}, else None."""
    import run_lock
    if jobs.view()["running"]:
        return None
    h = run_lock.holder()
    if not h or (jobs.child and h.get("pid") == jobs.child):
        return None
    return {"id": f"{h.get('pid')}-{h.get('started')}", "what": run_lock.describe(h), "pid": h.get("pid"),
            "args": h.get("args") or [], "started": h.get("started")}


def api_get(path, query, jobs):
    """(http code, JSON object) for GET /api/config and /api/job."""
    if path == "/api/config":
        cfg = load_cfg()
        return 200, {"ok": True, "editable": editable(cfg), "status": status(cfg), "job": jobs.view(10 ** 9),
                     "active": external_run(jobs)}
    if path == "/api/job":
        try:
            since = int((query.get("since") or ["0"])[0])
        except ValueError:
            since = 0
        return 200, {"ok": True} | jobs.view(since)
    if path == "/api/active":
        import run_lock
        try:
            since = int((query.get("since") or ["0"])[0])
        except ValueError:
            since = 0
        ext = external_run(jobs)
        lines, nxt = run_lock.read_log(since, finished=not ext)
        return 200, {"ok": True, "active": bool(ext), "id": ext and ext["id"], "what": ext["what"] if ext else "",
                     "lines": lines, "next": nxt}
    return 404, {"ok": False, "error": "not found"}


def api_post(path, req, jobs):
    """(http code, JSON object) for POST /api/config and /api/run."""
    if not isinstance(req, dict):
        return 400, {"ok": False, "error": "expected a JSON object"}
    try:
        if path == "/api/config":
            cfg, changed = _save(req)
            return 200, {"ok": True, "changed": changed, "editable": editable(cfg), "status": status(cfg)}
        if path == "/api/run":
            action = req.get("action")
            if action not in ACTIONS:
                return 400, {"ok": False, "error": f"unknown action {action!r}"}
            if jobs.view()["running"]:  # a double click, or a second tab
                return 409, {"ok": False, "error": "already_running", "already_running": True, "job": jobs.view()}
            ext = external_run(jobs)
            if ext:  # the 07:00 run, the Friday sync, a terminal or another Control Center window
                return 409, {"ok": False, "error": "already_running", "already_running": True, "active": ext}
            if action == "pull_data_repo" and req.get("clone_url"):
                import data_repo
                url = str(req["clone_url"]).strip()
                if not CLONE_RX.match(url) or data_repo.REMOTE_MARK not in url:
                    return 400, {"ok": False, "error": f"not a clone URL of {data_repo.REMOTE_MARK} "
                                                       "(https://… or git@…, without a user name or token)"}
            _, changed = _save(req)
            job = jobs.start(action, {k: req.get(k) for k in ("clone_url", "clone_dir")})
            return 200, {"ok": True, "changed": changed, "job": job}
    except ValueError as e:
        return 400, {"ok": False, "error": str(e)}
    except RuntimeError as e:
        return 409, {"ok": False, "error": str(e)}
    return 404, {"ok": False, "error": "not found"}


# ---------- STARTUP.html ----------

def page_data(cfg):
    import curation
    sync = curation.page_sync_config(cfg)
    return {"edition": "starter" if STARTER else "radar", "editable": editable(cfg), "status": status(cfg),
            "raw": raw_config(), "paths": PATHS, "here": str(HERE), "gui_port": GUI_PORT, "data_url": DATA_URL,
            "commands": commands(cfg), "actions": ACTIONS, "max_pillars": MAX_PILLARS,
            "sync": sync if sync.get("hosts") else {}}


def write_startup(cfg, log=print):
    """IC_Paper_Radar/STARTUP.html (Starter: output/STARTUP.html), next to DASHBOARD.html."""
    path = Path(cfg["paths"]["onedrive_root"]) / PAGE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(PAGE + ".tmp")
    tmp.write_text(render(page_data(cfg)), encoding="utf-8")
    os.replace(tmp, path)
    log(f"Control center: {path}")
    return path


def render(data):
    import html_renderer
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5">
<title>IC Paper Radar — Setup &amp; Control Center</title><style>{html_renderer.CSS}{CSS}</style></head>
<body><header class="bar"><h1>⚙️ Setup &amp; Control Center</h1>
<a class="btn" href="DASHBOARD.html">📊 Open Dashboard ↗</a>
<span id="mode" class="btn pill" title="">⏳ Connecting…</span>
<span id="dirty" class="dirty" hidden>● unsaved changes</span>
<button class="btn primary" id="savebtn" onclick="save()">💾 Save config.json</button>
<button class="btn sec" onclick="theme()" title="light/dark">◐</button></header>
<main class="cc">
<section class="card" id="c-status"></section>
<section class="card" id="c-run"></section>
<section class="card" id="c-console" hidden></section>
<section class="card" id="c-themes"></section>
<section class="card" id="c-people"></section>
<section class="card" id="c-repo"></section>
<p class="muted foot">Generated <span id="gen"></span>. Secrets (IEEE key, tokens, <code>.env</code>) are never shown or
stored here: only whether they are set.</p>
</main><div id="toast" class="toast" hidden></div>
<script id="cc-data" type="application/json">{blob}</script>
<script>{JS}</script></body></html>"""


CSS = r"""
main.cc{max-width:1180px}.cc .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:14px 0}
.cc h2{font-size:16px;margin:0 0 10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}.cc h3{font-size:14px;margin:14px 0 6px}
.muted{color:var(--muted)}.ok{color:var(--ok)}.warn{color:var(--warn)}.small{font-size:12.5px}.foot{font-size:12.5px;text-align:center}
.dirty{color:var(--warn);font-size:13px;font-weight:600}.btn.small{padding:2px 8px;font-size:12.5px}.btn[disabled]{opacity:.5;cursor:default}
.btn.danger:hover{border-color:var(--warn);color:var(--warn)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px 18px}
.steps{list-style:none;margin:0;padding:0;display:grid;gap:6px}.steps li{display:flex;gap:8px;align-items:baseline}
.steps .ic{width:1.4em;text-align:center;flex:none}.steps .sub{color:var(--muted);font-size:13px}
.prog{height:9px;background:var(--chip);border-radius:99px;overflow:hidden;margin:6px 0 12px}.prog>i{display:block;height:100%;background:var(--ok);transition:width .3s}
.runbar{display:flex;flex-wrap:wrap;gap:8px}.runbar .btn{padding:8px 14px;font-size:14px}
pre.console{background:#0f1115;color:#d8dee9;border-radius:10px;padding:10px 12px;max-height:380px;overflow:auto;margin:0;
font:12.5px/1.45 ui-monospace,SFMono-Regular,Consolas,Menlo,monospace;white-space:pre-wrap;word-break:break-word}
.chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.chip{display:inline-flex;align-items:center;gap:2px;background:var(--chip);border:1px solid var(--line);border-radius:999px;padding:1px 3px 1px 10px;font-size:13px;max-width:100%}
.chip .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.chip.rx .t{font-style:italic}
.chip button{border:0;background:none;color:var(--muted);cursor:pointer;padding:0 4px;font:inherit;font-size:12px;border-radius:99px}
.chip button:hover{color:var(--fg)}.chip button.w{background:var(--card);border:1px solid var(--line);min-width:24px;color:var(--fg);font-weight:600;margin-left:4px}
.chip button.w.neg{color:var(--warn)}.adder{display:inline-flex;gap:4px;align-items:center;flex-wrap:wrap}
.in{padding:4px 8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);font:inherit;font-size:13px;min-width:0}
.in.w{width:62px}.in.wide{width:100%}.in.mono,textarea.in{font-family:ui-monospace,SFMono-Regular,Consolas,Menlo,monospace;font-size:12.5px}
textarea.in{width:100%;min-height:58px;resize:vertical}
.pillar{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:10px 0}
.pillar .ph{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:8px}.pillar .ph .num{font-weight:700;min-width:1.6em}
.pillar .ph .name{flex:1 1 260px}.pillar .ph .short{width:120px}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:5px 14px;font-size:14px;align-items:baseline}.kv>b{font-weight:600}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0}.row label{display:inline-flex;gap:6px;align-items:center}
table.mini{border-collapse:collapse;width:100%;background:none}table.mini td,table.mini th{padding:5px 6px;font-size:13.5px;border-bottom:1px solid var(--line)}
.tag{display:inline-block;font-size:11.5px;border:1px solid var(--line);border-radius:6px;padding:0 6px;color:var(--muted)}
.tip{cursor:help;border-bottom:1px dotted var(--muted)}
.toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:var(--fg);color:var(--bg);padding:8px 14px;border-radius:10px;z-index:50;font-size:14px;max-width:90vw}
.cmd{display:flex;gap:6px;align-items:flex-start;margin:4px 0}.cmd code{flex:1;white-space:pre-wrap;word-break:break-all;padding:4px 8px;display:block}
@media (max-width:700px){.pillar .ph .short{width:90px}.kv{grid-template-columns:1fr}}
"""

JS = r"""
const D = JSON.parse(document.getElementById('cc-data').textContent);
const STARTER = D.edition === 'starter';
const clone = x => JSON.parse(JSON.stringify(x));
const $ = (s, el) => (el || document).querySelector(s);
const fmt = n => (n == null ? '–' : Number(n).toLocaleString('en-US'));
let S = clone(D.editable), ST = D.status, API = null, KW = null, BASE = '', JOB = {id: null, next: 0, running: false}, ACT = null;

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k === 'value') e.value = v;
    else if (k === 'checked') e.checked = !!v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(9)) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
function fill(el, ...kids) {  // replaceChildren, but nested arrays flattened and null/false skipped (like h)
  el.replaceChildren(...kids.flat(9).filter(c => c != null && c !== false).map(c => c.nodeType ? c : document.createTextNode(String(c))));
  return el;
}
function theme() {
  const r = document.documentElement;
  const dark = r.dataset.theme ? r.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  r.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('paper_radar_theme', r.dataset.theme); } catch (e) {}
}
try { const t = localStorage.getItem('paper_radar_theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
function toast(msg, ms) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, ms || 3500);
}

// ---------- keywords grouped under their pillar headings (_pillarN_…) ----------
function slug(s) { return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40) || 'pillar'; }
function buildKW() {
  const by = {}, markers = {}, extra = [], loose = []; let cur = 0;
  for (const [k, w] of S.positive_keywords) {
    const m = /^_pillar(\d+)/.exec(k);
    if (m) { cur = +m[1]; if (!markers[cur]) markers[cur] = k; by[cur] = by[cur] || []; continue; }
    if (k.startsWith('_')) { extra.push([k, w]); continue; }
    (cur ? (by[cur] = by[cur] || []) : loose).push([k, w]);
  }
  const n = S.pillars.length;
  KW = {extra, loose,
        pillars: S.pillars.map((name, i) => ({name, short: S.pillar_short[i] || '', marker: markers[i + 1] || null, kws: by[i + 1] || []})),
        orphans: Object.keys(by).map(Number).filter(k => k > n || k < 1).sort((a, b) => a - b).map(k => ({n: k, marker: markers[k], kws: by[k]}))};
}
function kwPairs() {
  const out = [...KW.extra, ...KW.loose];
  KW.pillars.forEach((p, i) => {
    const n = i + 1, keep = p.marker && (p.marker === `_pillar${n}` || p.marker.startsWith(`_pillar${n}_`));
    out.push([keep ? p.marker : `_pillar${n}_${slug(p.name)}`, 0], ...p.kws);
  });
  KW.orphans.forEach(o => out.push([o.marker, 0], ...o.kws));
  return out;
}
function collect() {
  const u = {positive_keywords: kwPairs(), negative_keywords: S.negative_keywords, negative_override: S.negative_override,
             key1_themes: S.key1_themes, min_score: S.min_score, vip_authors: S.vip_authors, vip_boost: S.vip_boost,
             anchors: S.anchors, contact_email: S.contact_email, data_repo: S.data_repo, data_repo_dir: S.data_repo_dir};
  if (STARTER) {
    u.pillars = KW.pillars.map(p => p.name.trim());
    const sh = KW.pillars.map(p => (p.short || '').trim());
    while (sh.length && !sh[sh.length - 1]) sh.pop();
    u.pillar_short = sh; u.arxiv = S.arxiv;
  }
  return u;
}
let baseline = '';
function snapshot() { return JSON.stringify(collect()); }
function changed() { const d = snapshot() !== baseline; $('#dirty').hidden = !d; return d; }
function isDirty() { return snapshot() !== baseline; }

// ---------- a chip list: strings, or [key, weight] pairs ----------
function chips(list, o) {
  o = o || {};
  const box = h('div', {class: 'chips'});
  const draw = (focus) => {
    box.replaceChildren(...list.map((it, i) => {
      const k = o.weights ? it[0] : it, rx = o.weights && k.startsWith('re:');
      const shown = rx ? k.slice(3).split('::')[0] : (o.label ? o.label(k) : k);
      return h('span', {class: 'chip' + (rx ? ' rx' : ''), title: rx ? 'regex: ' + k.split('::').slice(1).join('::') : (o.tip ? o.tip(k) : k)},
        h('span', {class: 't'}, shown),
        o.weights ? h('button', {class: 'w' + (it[1] < 0 ? ' neg' : ''), title: 'Weight (click to change)', onclick: () => {
          const v = prompt(`Weight for “${shown}” (−20 … 20; higher = stronger match):`, it[1]);
          if (v === null) return; const n = Number(v);
          if (v.trim() === '' || !isFinite(n) || n < -20 || n > 20) return alert('Please enter a number from −20 to 20.');
          it[1] = n; draw(); changed(); }}, String(it[1])) : null,
        o.move ? h('button', {title: 'Move to another pillar', onclick: () => o.move(i)}, '⇄') : null,
        h('button', {title: 'Remove', onclick: () => { list.splice(i, 1); draw(); changed(); if (o.after) o.after(); }}, '✕'));
    }), adder());
    if (focus) { const f = box.querySelector('input.in'); if (f) f.focus(); }
  };
  const adder = () => {
    const inp = h('input', {class: 'in', placeholder: o.placeholder || 'add…', size: o.size || 22});
    const w = o.weights ? h('input', {class: 'in w', type: 'number', value: o.defw == null ? 3 : o.defw, min: -20, max: 20, step: 1, title: 'weight'}) : null;
    const go = () => {
      let v = inp.value.trim(); if (!v) return;
      if (o.clean) v = o.clean(v);
      const err = o.check && o.check(v); if (err) return alert(err);
      const keys = list.map(x => (o.weights ? x[0] : x).toLowerCase());
      if (keys.includes(v.toLowerCase())) { inp.value = ''; return toast('Already in the list'); }
      if (o.weights) {
        const n = Number(w.value);
        if (w.value === '' || !isFinite(n) || n < -20 || n > 20) return alert('The weight must be a number from −20 to 20.');
        if (o.taken) { const t = o.taken(v); if (t) return alert(t); }
        list.push([v, n]);
      } else list.push(v);
      draw(true); changed(); if (o.after) o.after();
    };
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); go(); } });
    return h('span', {class: 'adder'}, inp, w, h('button', {class: 'btn small', onclick: go}, '＋ Add'));
  };
  draw(false);
  return box;
}

// ---------- 1. setup progress ----------
function renderStatus() {
  const st = ST.store, env = ST.env, dr = ST.data_repo, p = ST.pillars;
  const steps = [
    {ok: st.papers > 0, req: true, t: 'Paper store', s: st.papers > 0
      ? `${fmt(st.papers)} papers in ${st.file} · ${fmt(st.candidates)} active candidates · ${fmt(st.external)} external`
        + (dr.connected ? (dr.missing_here ? ` · ⚠️ ${fmt(dr.missing_here)} shared papers not loaded yet (📥 Read from Private Repo)` : ' · ✅ shared corpus loaded') : '')
      : 'empty: fetch papers (🌐 Fetch New Papers Now), or connect the private data repo below to load the shared corpus'},
    {ok: p.ready, req: true, t: 'Research pillars', s: p.ready ? `✅ ${p.count} pillars active · ${fmt(p.keywords)} weighted keywords`
      : '⚠️ Setup required: add your pillars and keywords below, then ▶ Run & Update My Dashboard'},
    {ok: env.contact_email_set, req: true, t: 'Contact e-mail', s: env.contact_email_set ? '🟢 set (the polite Crossref / OpenAlex pool)'
      : '⚪ not set: add it below (Crossref and OpenAlex answer faster with a mailto)'},
    {ok: env.has_ieee_key, req: false, t: 'IEEE API key', s: env.has_ieee_key ? '🟢 Configured (IEEE_API_KEY is set)'
      : '⚪ Using the Crossref / OpenAlex fallback (optional: set the IEEE_API_KEY environment variable)'},
    {ok: env.has_claude, req: false, t: 'Claude CLI', s: env.has_claude ? `🟢 Ready (${env.claude_command})`
      : '⚪ No-LLM mode: scoring, dashboard and seeding work; digests and the weekly synthesis are skipped'},
    {ok: dr.connected, req: false, t: 'Private data repo', s: dr.connected ? `🟢 Connected to ic-paper-radar-data · ${fmt(dr.papers)} papers · ${dr.peers.length} peer(s)`
      : '⚪ Not cloned yet (optional, for collaborators): see “Private Shared Repo” below'},
  ];
  const req = steps.filter(x => x.req), done = req.filter(x => x.ok).length;
  const all = steps.filter(x => x.ok).length;
  fill($('#c-status'), 
    h('h2', {}, '🧭 Setup Progress & Readiness', h('span', {class: 'muted small'}, `${done}/${req.length} required · ${all}/${steps.length} overall`)),
    h('div', {class: 'prog'}, h('i', {style: `width:${Math.round(100 * (done + 0.25 * (all - done)) / (req.length + 0.25 * (steps.length - req.length)))}%`})),
    h('ul', {class: 'steps'}, steps.map(x => h('li', {}, h('span', {class: 'ic'}, x.ok ? '✅' : (x.req ? '⚠️' : '⚪')),
      h('div', {}, h('b', {}, x.t), ' ', h('span', {class: 'sub'}, x.s))))),
    !env.has_git ? h('p', {class: 'warn small'}, '⚠️ git is not on PATH: the private data repo needs Git (https://git-scm.com).') : null);
  $('#gen').textContent = ST.generated + (API ? ' (live)' : ' (snapshot in this file)');
}

// ---------- run bar + console ----------
const RUN_TIPS = {
  rescore_and_seed: 'Saves your settings, re-scores every paper with your keywords/authors (--rescore), tops up each pillar to 10 candidates (--seed-pillars 5 --no-claude) and rebuilds DASHBOARD.html. 0 tokens, no API calls except a small Beyond-IEEE search.',
  daily: 'One collection pass now (IEEE / Crossref / OpenAlex) and this week\'s report' + (ST.env.has_claude ? ' with digests (claude -p).' : ' (--no-claude: no Claude CLI found).') + ' On the report day it also finalizes the week.',
  pull_data_repo: 'Read-only: fetch origin/main of ic-paper-radar-data, import every peer overlay, merge new/enriched papers into your store, adopt the external ones ≥ min_score, rebuild the dashboards. Nothing is pushed.',
  sync_data_repo: '--sync (offline Save-Marks files) then --sync-data-repo: pull, merge, export the clean union, write peers/<you>.json and push a real gain to ic-paper-radar-data.'};
function runBtn(a, extra, primary) {
  return h('button', {class: 'btn' + (primary ? ' primary' : ''), title: RUN_TIPS[a], 'data-run': a,
    onclick: () => run(a, extra)}, D.actions[a]);
}
function renderRun() {
  fill($('#c-run'), h('h2', {}, '🚀 Run', h('span', {class: 'muted small'}, API ? 'runs on this computer; output below'
      : 'static page: shows the commands to run (or start Start_Radar_GUI for one-click runs)')),
    h('div', {class: 'runbar'}, runBtn('rescore_and_seed', null, true), runBtn('daily'), runBtn('pull_data_repo'), runBtn('sync_data_repo')));
  lockRun();
}
function lockRun() { document.querySelectorAll('[data-run]').forEach(b => { b.disabled = !!(API && (JOB.running || ACT)); }); }
// a run this page didn't start (scheduled task, terminal, another window): stream .run.log until it ends
function streamActive(a) {
  ACT = {id: a.id, next: 0};
  showConsole(`⏳ Already running: ${a.what}`, ['Another radar run holds the lock, so nothing new was started. Its output:']);
  lockRun(); pollActive();
}
async function pollActive() {
  if (!ACT) return;
  let r;
  try { r = await call('GET', '/api/active?since=' + ACT.next); } catch (e) { setTimeout(pollActive, 3000); return; }
  const pre = $('#console');
  if (r.active && r.id !== ACT.id) { ACT = {id: r.id, next: 0}; if (pre) pre.textContent = ''; return pollActive(); }
  if (pre && r.lines.length) {
    const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
    pre.textContent += (pre.textContent ? '\n' : '') + r.lines.join('\n');
    if (atEnd) pre.scrollTop = pre.scrollHeight;
  }
  ACT.next = r.next;
  if (r.active) return setTimeout(pollActive, 1500);
  ACT = null; lockRun();
  const t = $('#jobtitle'); if (t) t.textContent = '✅ The other run finished: the buttons work again';
  refresh(true);
}
function showConsole(title, lines, cmds) {
  const c = $('#c-console'); c.hidden = false;
  const pre = h('pre', {class: 'console', id: 'console'}, (lines || []).join('\n'));
  fill(c, h('h2', {}, h('span', {id: 'jobtitle'}, title), h('button', {class: 'btn small', onclick: () => { c.hidden = true; }}, 'Hide')),
    cmds ? h('div', {}, cmds) : null, cmds ? null : pre);
  c.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}
function cmdRow(text) {
  return h('div', {class: 'cmd'}, h('code', {}, text), h('button', {class: 'btn small', onclick: () => {
    navigator.clipboard && navigator.clipboard.writeText(text).then(() => toast('Copied'), () => toast('Copy failed: select the text'));
  }}, '📋 Copy'));
}
function showCommands(a, extra) {
  const isWin = /Win/.test(navigator.platform || navigator.userAgent);
  const cd = isWin ? `cd /d "${D.here}"` : `cd "${D.here}"`;
  const lines = [];
  if (extra && extra.clone_url) lines.push(`git clone ${extra.clone_url} "${extra.clone_dir || ST.data_repo.default_dir || '../ic-paper-radar-data'}"`);
  lines.push(...D.commands[a]);
  showConsole(`${D.actions[a]}: run these commands`, null, [
    h('p', {class: 'small'}, isDirty() ? '⚠️ First click 💾 Save config.json and put the file in the radar folder (replace config.json there). ' : '',
      STARTER ? h('span', {}, 'Easiest: double-click ', h('b', {}, isWin ? 'Start_Radar_GUI.cmd' : 'Start_Radar_GUI.command'),
        ' in the radar folder: it opens this page with working buttons. Or, in a terminal:')
        : 'This page could not reach radar_sync_server.py (PaperRadar_SyncServer). Start it, open this page from the server, or run on the Minisforum:'),
    cmdRow(cd), lines.map(cmdRow)]);
}
async function call(method, path, body) {
  const hd = {};
  if (body) hd['Content-Type'] = 'application/json';
  if (API === location.origin) hd['X-Radar-GUI'] = '1';
  if (D.sync && D.sync.token) hd['X-Radar-Token'] = D.sync.token;
  const r = await fetch(API + path, {method, headers: hd, body: body ? JSON.stringify(body) : undefined,
                                     credentials: 'same-origin', cache: 'no-store'});
  let j = {}; try { j = await r.json(); } catch (e) { j = {ok: false, error: `HTTP ${r.status}`}; }
  if (!r.ok && j.ok !== false) j.ok = false;
  return j;
}
async function run(a, extra) {
  if (!API) return showCommands(a, extra);
  if (JOB.running || ACT) return toast('Another radar run is still running');
  if (a === 'sync_data_repo' && !confirm('Full sync pushes your clean corpus and your overlay (peers/' + (ST.data_repo.me || 'you') + '.json) to ic-paper-radar-data. Continue?')) return;
  const body = Object.assign({action: a}, extra || {});
  const dirty = isDirty();
  if (dirty) body.config = collect();
  let r;
  try { r = await call('POST', '/api/run', body); } catch (e) { return alert('The radar server did not answer: ' + e); }
  if (!r.ok && r.already_running) {  // never two runs at once: show the one that is running
    if (r.active) return streamActive(r.active);
    if (r.job) { JOB = {id: r.job.id, next: 0, running: true}; showConsole(`⏳ Already running: ${r.job.label}`, []); lockRun(); return poll(); }
  }
  if (!r.ok) return alert(r.error || 'Failed');
  if (dirty) { baseline = snapshot(); changed(); }
  JOB = {id: r.job.id, next: 0, running: true};
  showConsole(`⏳ ${D.actions[a]}…`, []);
  lockRun(); poll();
}
async function poll() {
  let r;
  try { r = await call('GET', '/api/job?since=' + JOB.next); } catch (e) { setTimeout(poll, 3000); return; }
  if (r.id !== JOB.id) { JOB.id = r.id; JOB.next = 0; return poll(); }
  const pre = $('#console');
  if (pre && r.lines.length) {
    const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
    pre.textContent += (pre.textContent ? '\n' : '') + r.lines.join('\n');
    if (atEnd) pre.scrollTop = pre.scrollHeight;
  }
  JOB.next = r.next; JOB.running = r.running; lockRun();
  if (r.running) return setTimeout(poll, 1000);
  const t = $('#jobtitle'); if (t) t.textContent = (r.rc ? '❌ ' : '✅ ') + (r.label || '') + (r.rc ? ` failed (exit ${r.rc})` : ' finished');
  refresh(true);
}
async function refresh(quiet) {
  if (!API) return;
  const j = await call('GET', '/api/config');
  if (!j.ok) return quiet ? null : toast(j.error || 'Could not reload');
  ST = j.status;
  if (!isDirty()) { S = j.editable; buildKW(); }
  renderAll(); if (!isDirty()) { baseline = snapshot(); changed(); }
}

// ---------- 2. themes & keywords ----------
function movePrompt(list, i) {
  const names = KW.pillars.map((p, n) => `${n + 1} = ${p.name || '(unnamed)'}`).join('\n');
  const v = prompt(`Move “${list[i][0]}” to pillar number (0 = not under a pillar):\n${names}`);
  if (v === null) return; const n = parseInt(v, 10);
  if (!(n >= 0 && n <= KW.pillars.length)) return alert('No such pillar');
  const [it] = list.splice(i, 1);
  (n ? KW.pillars[n - 1].kws : KW.loose).push(it); renderThemes(); changed();
}
function allKeys() { return [KW.loose, ...KW.pillars.map(p => p.kws), ...KW.orphans.map(o => o.kws)].flat().map(x => x[0]); }
function kwOpts(list) {
  return {weights: true, placeholder: 'keyword or re:label::regex', size: 24, move: i => movePrompt(list, i),
    taken: v => allKeys().includes(v) ? `“${v}” is already under another pillar: a keyword belongs to one pillar.` : null,
    check: v => v.startsWith('re:') && !/^re:[^:]+::.+/.test(v) ? 'A regex keyword looks like re:<label>::<regex>' : null,
    after: () => renderPillarCounts()};
}
function renderPillarCounts() { document.querySelectorAll('[data-pcount]').forEach(e => { const k = +e.dataset.pcount; e.textContent = `${(k ? KW.pillars[k - 1].kws : KW.loose).length} keywords`; }); }
function renderThemes() {
  const ps = KW.pillars.map((p, i) => {
    const head = STARTER
      ? [h('span', {class: 'num'}, `P${i + 1}`),
         h('input', {class: 'in name', value: p.name, placeholder: 'Pillar name, e.g. Precision SAR ADCs', oninput: e => { p.name = e.target.value; changed(); }}),
         h('input', {class: 'in short', value: p.short, maxlength: 24, placeholder: 'short label', title: '1–2 words for phones and the Pillar column (optional)', oninput: e => { p.short = e.target.value; changed(); }}),
         h('button', {class: 'btn small', title: 'Move up', disabled: i === 0, onclick: () => { KW.pillars.splice(i - 1, 0, ...KW.pillars.splice(i, 1)); renderThemes(); changed(); }}, '↑'),
         h('button', {class: 'btn small', title: 'Move down', disabled: i === KW.pillars.length - 1, onclick: () => { KW.pillars.splice(i + 1, 0, ...KW.pillars.splice(i, 1)); renderThemes(); changed(); }}, '↓'),
         h('button', {class: 'btn small danger', title: 'Remove this pillar and its keywords', onclick: () => {
           if (!confirm(`Remove pillar ${i + 1} “${p.name}” and its ${p.kws.length} keywords?`)) return;
           KW.pillars.splice(i, 1); renderThemes(); changed(); }}, '✕')]
      : [h('span', {class: 'num'}, `P${i + 1}`), h('b', {class: 'name'}, p.name.replace(/^Pillar\s*\d+\s*[—–-]\s*/, '')), p.short ? h('span', {class: 'tag'}, p.short) : null];
    return h('div', {class: 'pillar'}, h('div', {class: 'ph'}, head, h('span', {class: 'muted small', 'data-pcount': i + 1})), chips(p.kws, kwOpts(p.kws)));
  });
  const loose = (KW.loose.length || !KW.pillars.length) ? h('div', {class: 'pillar'}, h('div', {class: 'ph'}, h('b', {}, 'Not under a pillar'),
      h('span', {class: 'muted small'}, '(they score, but don\'t pick a pillar)'), h('span', {class: 'muted small', 'data-pcount': 0})), chips(KW.loose, kwOpts(KW.loose))) : null;
  const orph = KW.orphans.map(o => h('div', {class: 'pillar'}, h('div', {class: 'ph'}, h('b', {}, `Heading _pillar${o.n}_ (no pillar ${o.n})`),
      h('span', {class: 'muted small'}, 'kept as they are; add a pillar or move them')), chips(o.kws, kwOpts(o.kws))));
  fill($('#c-themes'), 
    h('h2', {}, '🎯 My Research Themes & Keywords'),
    h('p', {class: 'muted small'}, 'A paper\'s score is the sum of the weights of the keywords in its title, abstract and index terms (word match, case-insensitive unless ALL CAPS; a space or hyphen matches either; plurals match). The pillar with the most hits files it. Weights: 5 = defining term, 3–4 = strong, 1–2 = generic. ',
      h('span', {class: 'tip', title: 're:<label>::<regex> is a raw (Python) regular expression, case-sensitive unless it starts with (?i). The label is what the report shows.'}, 'Regex keywords?')),
    STARTER ? null : h('p', {class: 'muted small'}, 'This radar\'s 4 pillar names are fixed in catalog.py; their keywords are editable here.'),
    ps, loose, orph,
    STARTER ? h('div', {class: 'row'}, h('button', {class: 'btn', disabled: KW.pillars.length >= D.max_pillars, onclick: () => {
      KW.pillars.push({name: '', short: '', marker: null, kws: []}); renderThemes(); changed();
      const ins = document.querySelectorAll('.pillar .name'); if (ins.length) ins[ins.length - 1].focus(); }}, '＋ Add pillar'),
      h('span', {class: 'muted small'}, `Up to ${D.max_pillars}. Reordering renumbers the pillars; papers you pinned to a pillar number keep that number.`)) : null,
    h('div', {class: 'grid2'},
      h('div', {}, h('h3', {}, '🚫 Negative keywords ', h('span', {class: 'tip muted small', title: 'Off-topic terms. A negative keyword zeroes a paper with no positive keyword hit; with a hit (or a title matching the override) it only costs negative_penalty.'}, 'ⓘ')),
        chips(S.negative_keywords, {placeholder: 'e.g. phased array'})),
      h('div', {}, h('h3', {}, '🌍 Beyond-IEEE themes ', h('span', {class: 'tip muted small', title: 'beyond_ieee.key1_themes: application themes of your research (e.g. wearable, implantable, 6G). Empty = the Nature/Science board stays off.'}, 'ⓘ')),
        chips(S.key1_themes, {placeholder: 'e.g. wearable'}))),
    h('h3', {}, 'Negative override (regex on the title) ', h('span', {class: 'tip muted small', title: 'When the title matches, a negative keyword only costs negative_penalty instead of zeroing the paper. Python regex; (?i) = case-insensitive. Empty = off.'}, 'ⓘ')),
    h('input', {class: 'in wide mono', value: S.negative_override, placeholder: '(?i)harvest|temperature sensor|…', oninput: e => { S.negative_override = e.target.value; changed(); }}),
    h('div', {class: 'row'}, h('label', {}, 'min_score ', h('input', {class: 'in w', type: 'number', min: 0, max: 1000, step: 1, value: S.min_score,
      oninput: e => { S.min_score = Number(e.target.value); changed(); }})), h('span', {class: 'muted small'}, 'papers below this score never become candidates (default 5).')));
  renderPillarCounts();
}

// ---------- 3. key authors & anchors ----------
const VIP_TIP = 'Matching: a full name (“Kofi A. A. Makinwa”) matches that first name + surname; an initial form (“T. Jang”) matches only authors listed with that initial, so “Taehoon Jang” doesn’t trigger it; a surname alone (“Makinwa”) matches any author with that surname. Add the spellings you see in IEEE Xplore (accents too).';
function cleanDoi(v) { return v.replace(/^https?:\/\/(dx\.)?doi\.org\//i, '').replace(/^doi:\s*/i, '').trim(); }
function renderPeople() {
  const info = ST.store.anchors || {};
  const rows = S.anchors.map((d, i) => {
    const a = info[d.toLowerCase()];
    return h('tr', {}, h('td', {}, a ? (a.pin === 'anchor' ? '🏛️' : '📌') : '⏳'),
      h('td', {}, h('a', {href: 'https://doi.org/' + d, target: '_blank', rel: 'noopener'}, d)),
      h('td', {}, a ? `${a.title || ''} ` : h('span', {class: 'muted'}, 'not in the store yet: fetched and pinned on the next ▶ Run'), a ? h('span', {class: 'muted small'}, `${a.venue || ''} ${a.year || ''}`) : null),
      h('td', {}, h('button', {class: 'btn small danger', title: 'Remove anchor', onclick: () => { S.anchors.splice(i, 1); renderPeople(); changed(); }}, '✕')));
  });
  const doiIn = h('input', {class: 'in', placeholder: '10.1109/JSSC.2020.1234567 or a doi.org link', size: 38});
  const addDoi = () => {
    const d = cleanDoi(doiIn.value); if (!d) return;
    if (!/^10\.\d{4,9}\/\S+$/.test(d)) return alert('That is not a DOI (it starts with 10.).');
    if (S.anchors.some(x => x.toLowerCase() === d.toLowerCase())) return toast('Already an anchor');
    S.anchors.push(d); renderPeople(); changed();
  };
  doiIn.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addDoi(); } });
  fill($('#c-people'), h('h2', {}, '👤 Key Authors & 🏛️ Classic Anchors'),
    h('div', {class: 'grid2'},
      h('div', {}, h('h3', {}, 'VIP authors ', h('span', {class: 'tip muted small', title: VIP_TIP}, 'ⓘ how names match')),
        chips(S.vip_authors, {placeholder: 'e.g. Kofi A. A. Makinwa', size: 26, tip: () => VIP_TIP}),
        h('div', {class: 'row'}, h('label', {}, 'vip_boost +', h('input', {class: 'in w', type: 'number', min: 0, max: 50, step: 1, value: S.vip_boost,
          oninput: e => { S.vip_boost = Number(e.target.value); changed(); }})), h('span', {class: 'muted small'}, 'added to the score of a paper by a VIP author.'))),
      h('div', {}, h('h3', {}, `Anchor DOIs (${S.anchors.length}) `, h('span', {class: 'tip muted small', title: 'Classic papers always kept in the catalog (🏛️ = pinned as anchor, 📌 = pinned by you, ⏳ = fetched on the next run). They get anchor_boost.'}, 'ⓘ')),
        h('div', {class: 'row'}, doiIn, h('button', {class: 'btn small', onclick: addDoi}, '＋ Add anchor')),
        rows.length ? h('div', {class: 'tablewrap'}, h('table', {class: 'mini'}, h('tbody', {}, rows))) : h('p', {class: 'muted small'}, 'No anchors yet.'))),
    h('div', {class: 'row'}, h('label', {}, 'Contact e-mail ', h('input', {class: 'in', type: 'email', size: 30, value: S.contact_email, placeholder: 'you@example.org',
      oninput: e => { S.contact_email = e.target.value.trim(); changed(); }})), h('span', {class: 'muted small'}, 'sent to Crossref / OpenAlex in the User-Agent (their “polite pool”); never to anyone else.')));
}

// ---------- 4. private shared repo & peers ----------
function toggle(obj, key, label, tip) {
  return h('label', {title: tip || ''}, h('input', {type: 'checkbox', checked: !!obj[key], onchange: e => { obj[key] = e.target.checked; changed(); renderRepoStats(); }}), label);
}
function renderRepoStats() {
  const s = ST.sharing, el = $('#sharestats'); if (!el) return;
  el.textContent = S.data_repo.share_curation
    ? `You share: ✅ ${fmt(s.selected)} Selected · ⭐ ${fmt(s.cited)} Cited · 🏷️ ${S.data_repo.share_notes ? fmt(s.notes) + ' Tech notes' : 'notes kept private'} (in peers/${ST.data_repo.me || 'you'}.json)`
    : 'You share no curation: only the clean corpus (papers, abstracts, digests) goes to the repo.';
}
function linesList(arr) { return h('textarea', {class: 'in', oninput: e => { arr.splice(0, arr.length, ...e.target.value.split('\n').map(x => x.trim()).filter(Boolean)); changed(); }}, arr.join('\n')); }
function renderRepo() {
  const dr = ST.data_repo;
  const head = dr.connected
    ? h('div', {class: 'kv'},
        h('b', {}, 'Status'), h('span', {class: 'ok'}, '🟢 Connected to ic-paper-radar-data'),
        h('b', {}, 'Clone'), h('code', {}, dr.dir),
        h('b', {}, 'Shared corpus'), h('span', {}, `${fmt(dr.papers)} papers in paper_store_clean_share.sqlite`,
          dr.missing_here ? h('span', {class: 'warn'}, ` · ${fmt(dr.missing_here)} not in your store yet`) : (dr.missing_here === 0 ? h('span', {class: 'ok'}, ' · all in your store') : null)),
        h('b', {}, 'Last commit'), dr.commit ? h('span', {}, h('code', {}, dr.commit.hash), ` ${dr.commit.date.replace('T', ' ').slice(0, 16)} · `, h('span', {class: 'muted'}, dr.commit.subject)) : h('span', {class: 'muted'}, '–'),
        h('b', {}, 'You'), h('span', {}, dr.me || '–'))
    : h('div', {},
        h('p', {class: 'warn'}, '⚠️ Not cloned yet', h('span', {class: 'muted small'}, ` (${dr.reason})`)),
        h('p', {class: 'small'}, 'A collaborator with read access to the private repo can clone it here and load the shared corpus (papers, abstracts, digests) without a terminal. Git asks you to sign in to GitHub once.'),
        (() => {
          const url = h('input', {class: 'in wide mono', value: D.data_url, 'aria-label': 'clone URL'});
          const dir = h('input', {class: 'in wide mono', value: S.data_repo_dir || '../ic-paper-radar-data', 'aria-label': 'clone folder'});
          return h('div', {}, h('div', {class: 'row'}, h('span', {class: 'small', style: 'width:6em'}, 'Repo URL'), h('div', {style: 'flex:1'}, url)),
            h('div', {class: 'row'}, h('span', {class: 'small', style: 'width:6em'}, 'Into folder'), h('div', {style: 'flex:1'}, dir)),
            h('div', {class: 'row'}, h('button', {class: 'btn primary', 'data-run': 'clone', onclick: () => {
              const d = dir.value.trim();
              run('pull_data_repo', {clone_url: url.value.trim(), clone_dir: d === '../ic-paper-radar-data' ? '' : d}); }}, '📥 Clone & Connect Private Data Repo'),
              h('span', {class: 'muted small'}, 'relative folders are next to the radar folder’s scripts')));
        })());
  const peers = dr.peers.length ? h('table', {class: 'mini'}, h('thead', {}, h('tr', {}, h('th', {}, 'Peer'), h('th', {}, 'Rows'), h('th', {}, '✅'), h('th', {}, '⭐'), h('th', {}, 'Updated'), h('th', {}, 'Page'))),
      h('tbody', {}, dr.peers.map(p => h('tr', {}, h('td', {}, h('b', {}, p.id), p.me ? h('span', {class: 'tag'}, 'you') : null,
        p.pillars && p.pillars.length ? h('div', {class: 'muted small'}, p.pillars.map(x => String(x).replace(/^Pillar\s*\d+\s*[—–-]\s*/, '')).join(' · ')) : null),
        h('td', {}, fmt(p.rows)), h('td', {}, fmt(p.selected)), h('td', {}, fmt(p.cited)), h('td', {class: 'small'}, (p.updated || '').replace('T', ' ')),
        h('td', {}, p.href ? h('a', {href: p.href}, `👥 ${p.id}'s Radar ↗`) : h('span', {class: 'muted small'}, p.me ? 'your dashboard' : 'after the next Read'))))))
    : h('p', {class: 'muted small'}, 'No peer overlays yet.');
  const dro = S.data_repo;
  const ax = STARTER ? S.arxiv : null;
  fill($('#c-repo'), h('h2', {}, '🤝 Private Shared Repo & Peer Sync'), head,
    h('h3', {}, 'Peers'), peers,
    h('h3', {}, 'My sharing'), h('p', {id: 'sharestats', class: 'small'}),
    h('div', {class: 'row'}, h('label', {}, 'peer_id ', h('input', {class: 'in', size: 18, maxlength: 39, value: dro.peer_id, placeholder: dr.me || 'your-name',
        title: 'Your name in the shared repo (peers/<peer_id>.json). Empty = the clone\'s git user.name.', oninput: e => { dro.peer_id = e.target.value.trim(); changed(); }}))),
    h('div', {class: 'row'}, toggle(dro, 'share_curation', 'share my curation', 'Write peers/<peer_id>.json (pillars, marks, ⭐, notes) so collaborators see your radar'),
      toggle(dro, 'share_notes', 'share my 🏷️ notes', 'Include your Tech notes in the overlay'),
      toggle(dro, 'adopt_external', 'adopt shared papers ≥ min_score', 'Merged papers that score ≥ min_score with your keywords join your archive (and can reach your pillars)')),
    STARTER ? h('div', {}, h('h3', {}, 'arXiv feed (optional)'),
      h('div', {class: 'row'}, toggle(ax, 'enabled', 'enabled', 'Run the arXiv queries on the weekly run'), toggle(ax, 'share', 'share arXiv papers', 'Include them in the shared corpus (selected or cited ones always are)')),
      h('div', {class: 'grid2'},
        h('div', {}, h('div', {class: 'small muted'}, 'Queries (one arXiv search_query per line)'), linesList(ax.queries)),
        h('div', {}, h('div', {class: 'small muted'}, 'must_all: one group per line, terms separated by commas (a paper needs a term of every group)'),
          h('textarea', {class: 'in', oninput: e => { ax.must_all = e.target.value.split('\n').map(l => l.split(',').map(x => x.trim()).filter(Boolean)).filter(g => g.length); changed(); }},
            (ax.must_all || []).map(g => g.join(', ')).join('\n')))),
      h('div', {class: 'grid2'}, h('div', {}, h('div', {class: 'small muted'}, 'Categories (empty = all)'), chips(ax.categories, {placeholder: 'e.g. cs.AR', check: v => /^[a-z-]+(\.[A-Za-z-]+)?$/.test(v) ? null : 'An arXiv category looks like cs.AR or eess.SP'})),
        h('div', {}, h('div', {class: 'small muted'}, 'exclude_any'), chips(ax.exclude_any, {placeholder: 'e.g. quantum'})))) : null,
    h('h3', {}, 'Sync'), h('div', {class: 'runbar'}, runBtn('pull_data_repo'), runBtn('sync_data_repo')),
    h('p', {class: 'muted small'}, dr.connected ? 'Read = pull only (safe any time). Full Sync also pushes; on the Minisforum radar it runs automatically on Fridays at 12:30.' : 'Both need the clone above.'));
  renderRepoStats(); lockRun();
}

function renderAll() { renderStatus(); renderRun(); renderThemes(); renderPeople(); renderRepo(); lockRun(); }
window.addEventListener('beforeunload', e => { if (isDirty()) { e.preventDefault(); e.returnValue = ''; } });

// ---------- saving ----------
function setPath(o, path, v) { for (const k of path.slice(0, -1)) { if (typeof o[k] !== 'object' || o[k] === null) o[k] = {}; o = o[k]; } o[path[path.length - 1]] = v; }
async function save() {
  const u = collect();
  if (STARTER && u.pillars.some(x => !x)) return alert('Every pillar needs a name.');
  if (API) {
    let r; try { r = await call('POST', '/api/config', {config: u}); } catch (e) { return alert('The radar server did not answer: ' + e); }
    if (!r.ok) return alert('Not saved: ' + r.error);
    ST = r.status; S = r.editable; buildKW(); renderAll(); baseline = snapshot(); changed();
    return toast(r.changed.length ? 'Saved config.json: ' + r.changed.join(', ') : 'No changes to save');
  }
  const raw = clone(D.raw);
  for (const [k, v] of Object.entries(u)) {
    if (k === 'data_repo' || k === 'arxiv') for (const [kk, vv] of Object.entries(v)) setPath(raw, [k, kk], vv);
    else setPath(raw, D.paths[k], k === 'positive_keywords' ? Object.fromEntries(v) : v);
  }
  const text = JSON.stringify(raw, null, 4) + '\n';
  if (window.showSaveFilePicker) {
    try {
      const fh = await showSaveFilePicker({suggestedName: 'config.json', types: [{description: 'JSON', accept: {'application/json': ['.json']}}]});
      const w = await fh.createWritable(); await w.write(text); await w.close();
      baseline = snapshot(); changed();
      return toast(`Saved. It must be the config.json in ${D.here}`, 6000);
    } catch (e) { if (e.name === 'AbortError') return; }
  }
  const a = h('a', {href: URL.createObjectURL(new Blob([text], {type: 'application/json'})), download: 'config.json'});
  document.body.append(a); a.click(); a.remove();
  baseline = snapshot(); changed();
  toast(`Downloaded config.json: move it into ${D.here} (replace the old one), then run the radar.`, 8000);
}

// ---------- connect: the page's own server (--gui / sync server), else the radar's sync hosts ----------
async function tryBase(base) {
  try {
    const hd = {}; if (base === location.origin) hd['X-Radar-GUI'] = '1';
    if (D.sync && D.sync.token) hd['X-Radar-Token'] = D.sync.token;
    const r = await fetch(base + '/api/config', {headers: hd, credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(3000)});
    if (!r.ok) return null; const j = await r.json(); return j.ok ? j : null;
  } catch (e) { return null; }
}
async function connect() {
  const bases = [];
  if (/^https?:$/.test(location.protocol)) bases.push(location.origin);
  for (const host of (D.sync && D.sync.hosts) || []) bases.push(`http://${host}:${D.sync.port}`);
  for (const b of [...new Set(bases)]) {
    const j = await tryBase(b);
    if (j) {
      API = b; ST = j.status; S = j.editable; buildKW(); renderAll(); baseline = snapshot(); changed();
      const m = $('#mode'); m.textContent = '🟢 Live'; m.title = 'Connected to ' + b + ': buttons run on the radar computer';
      if (j.job && j.job.running) { JOB = {id: j.job.id, next: 0, running: true}; showConsole(`⏳ ${j.job.label}…`, []); poll(); }
      else if (j.active) streamActive(j.active);
      return;
    }
  }
  const m = $('#mode'); m.textContent = '⚪ Static'; m.title = 'Opened as a file: edits are saved as a downloaded config.json; the run buttons show the commands';
  if (location.protocol === 'file:' && STARTER) {
    try {
      const r = await fetch(`http://127.0.0.1:${D.gui_port}/ping`, {signal: AbortSignal.timeout(1200)});
      if (r.ok) { m.textContent = '🟡 GUI running'; m.title = 'The Control Center server is running: open it from its window, or this link'; m.onclick = () => { location.href = `http://127.0.0.1:${D.gui_port}/STARTUP.html`; }; }
    } catch (e) {}
  }
}
buildKW(); renderAll(); baseline = snapshot(); changed(); connect();
"""


# ---------- the --gui server (127.0.0.1 only, a key per launch) ----------

PAGE_TYPES = {".html": "text/html; charset=utf-8", ".bib": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8"}


def page_file(cfg, path, default=PAGE):
    """URL path → a .html/.bib/.md file in the output folder or its Weekly_Briefings / Topic_Dives / Peers folders."""
    root = Path(cfg["paths"]["onedrive_root"]).resolve()
    allowed = {root, Path(cfg["paths"]["weekly_dir"]).resolve(), Path(cfg["paths"]["topic_dir"]).resolve(),
               (root / "Peers").resolve()}
    rel = urllib.parse.unquote(path).lstrip("/") or default
    if "\\" in rel or ":" in rel or "\0" in rel:
        return None
    try:
        f = (root / rel).resolve()
    except (OSError, ValueError):
        return None
    if f.parent not in allowed or f.suffix.lower() not in PAGE_TYPES or not f.is_file():
        return None
    return f


class GuiHandler(BaseHTTPRequestHandler):
    server_version = "RadarGUI"

    def _send(self, code, body, ctype, headers=()):
        body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _host_ok(self):
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _cookie_ok(self):
        c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return "radar_gui" in c and secrets.compare_digest(c["radar_gui"].value, self.server.key)

    def _api_ok(self):
        return self._cookie_ok() and self.headers.get("X-Radar-GUI") == "1"

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, "Forbidden", "text/plain; charset=utf-8")
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/ping":  # lets a page opened as a file see that the GUI is running; no data
            return self._send(200, '{"ok": true, "gui": true}', "application/json",
                              [("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Private-Network", "true")])
        q = urllib.parse.parse_qs(u.query)
        if q.get("k"):
            if not secrets.compare_digest(q["k"][0], self.server.key):
                return self._send(401, "Wrong key: use the link printed in the Control Center window.", "text/plain; charset=utf-8")
            self.send_response(303)
            self.send_header("Set-Cookie", f"radar_gui={self.server.key}; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Location", "/" + (u.path.lstrip("/") or PAGE))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._cookie_ok():
            return self._send(401, "IC Paper Radar Control Center: open the link printed in its window (it holds this "
                                   "launch's key), or start it again with Start_Radar_GUI / python briefing.py --gui.",
                              "text/plain; charset=utf-8")
        if u.path.startswith("/api/"):
            if not self._api_ok():
                return self._json(403, {"ok": False, "error": "missing X-Radar-GUI header"})
            code, obj = api_get(u.path, q, self.server.jobs)
            return self._json(code, obj)
        cfg = load_cfg()
        if u.path in ("", "/", "/" + PAGE):
            try:
                write_startup(cfg, log=lambda m: None)
            except Exception:
                pass
        f = page_file(cfg, u.path)
        if not f:
            return self._send(404, "Not found.", "text/plain; charset=utf-8")
        self._send(200, f.read_bytes(), PAGE_TYPES[f.suffix.lower()])

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, "Forbidden", "text/plain; charset=utf-8")
        path = urllib.parse.urlsplit(self.path).path
        if not self._api_ok():
            return self._json(403, {"ok": False, "error": "not authorized"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(415, {"ok": False, "error": "expected application/json"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                return self._json(413, {"ok": False, "error": "too large"})
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        code, obj = api_post(path, req, self.server.jobs)
        self._json(code, obj)

    def log_message(self, *args):
        pass


def serve_gui(cfg, port=None, open_browser=True):
    """python briefing.py --gui [PORT]: the Control Center on http://127.0.0.1 until Ctrl+C. Returns 0."""
    write_startup(cfg)
    srv = None
    for p in ([port] if port else [GUI_PORT, 0]):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), GuiHandler)
            break
        except OSError:
            continue
    if srv is None:
        raise SystemExit(f"[ERROR] port {port} on 127.0.0.1 is in use: choose another one (--gui PORT)")
    srv.key, srv.jobs = secrets.token_urlsafe(24), Jobs()
    url = f"http://127.0.0.1:{srv.server_address[1]}/?k={srv.key}"
    print("IC Paper Radar — Setup & Control Center\n"
          f"  {url}\n"
          + ("Opening it in your browser. " if open_browser else "Open this link in your browser. ")
          + "Keep this window open while you use the page; Ctrl+C (or closing it) stops it.\n"
          "The link works only on this computer, and only until this window is closed.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        srv.server_close()
    return 0
