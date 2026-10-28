"""Zero-token collection for IC Paper Radar: everything lands in the SQLite store (store.py).

Order of each daily run (all public/free; IEEE capped at ieee_daily_budget calls/day):
  1. IEEE Xplore Metadata API, one query per venue for the lookback window (abstracts, citation counts)
  2. Crossref per venue (catches DOIs IEEE didn't return; reference lists as DOIs)
  3. IEEE API per-DOI lookups for papers still without an abstract
  4. OpenAlex: abstracts, OpenAlex id, references, cited-by counts
  5. classify pending papers (score → candidate / skipped / still pending)
  6. backfill: spend the remaining IEEE budget pulling older months into the corpus (status archive)

IEEE pages themselves sit behind an AWS WAF bot challenge: never scrape them, use the API.
"""
import html
import http.cookiejar
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from env_guard import ensure_minisforum_env

ensure_minisforum_env()
HERE = Path(__file__).resolve().parent
IEEE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles?"


def load_config():
    import catalog  # here, not at the top: catalog imports this module
    import paths
    cfg = paths.resolve(json.loads((HERE / "config.json").read_text(encoding="utf-8")))
    catalog.configure(cfg)  # pillar names from config.json
    return cfg


def pillars_ready(cfg):
    """Starter Edition: research pillars and at least one weighted keyword are configured."""
    return bool(cfg.get("pillars")) and any(w for k, w in cfg.get("positive_keywords", {}).items() if not k.startswith("_"))


SETUP_MSG = ("[SETUP REQUIRED] No research pillars configured in config.json! Please read README.md (copy the AI "
             "Setup Prompt in README.md into Claude / ChatGPT / Gemini to generate your config.json).")
STORE_TIP = ("[TIP] Local paper store is currently empty. You can either fetch papers directly via OpenAlex/IEEE, or "
             "contact the author to request the pre-built 1,400+ IC paper database (paper_store.sqlite) and place it "
             "in the project root.")


def store_paper_count(path):
    """Papers in the store file, 0 if it's missing or not a paper store yet (read-only, never creates it)."""
    import sqlite3
    if not Path(path).exists():
        return 0
    try:
        db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            return db.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        finally:
            db.close()
    except sqlite3.Error:
        return 0


def ieee_notice(log=print):
    if not os.environ.get("IEEE_API_KEY", "").strip():
        log("[INFO] No IEEE_API_KEY set: using OpenAlex + Crossref only (free, no key needed). Abstracts and "
            "IEEE citation counts may be missing for the newest papers; see README.md for a free key.")


def week_of(d):
    """Weekly report key: the Friday on or after `d` (a week runs Saturday..Friday)."""
    fri = d + timedelta(days=(4 - d.weekday()) % 7)
    y, w, _ = fri.isocalendar()
    return f"{y}-W{w:02d}", fri


def _get(url, cfg, data=None, timeout=40):
    ua = f"IC-Paper-Radar/2.0 (mailto:{cfg['contact_email']})"
    req = urllib.request.Request(url, data=data, headers={"User-Agent": ua})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if attempt == 2 or "403" in str(e) or _budget_gone(e):
                raise
            time.sleep((10 if "429" in str(e) else 3) * (attempt + 1))


def _budget_gone(e):
    """A 429 whose Retry-After is more than a minute: a daily budget, not a burst limit. OpenAlex gives
    key-less search requests a daily budget per IP; when it's used up it says Retry-After: ~hours."""
    try:
        return getattr(e, "code", None) == 429 and int(e.headers.get("Retry-After") or 0) > 60
    except (TypeError, ValueError):
        return False


TEX = {"cdot": "·", "times": "×", "pm": "±", "mu": "µ", "sigma": "σ", "Omega": "Ω", "deg": "°", "circ": "°",
       "approx": "≈", "le": "≤", "ge": "≥", "leq": "≤", "geq": "≥", "sim": "~", "infty": "∞", "alpha": "α",
       "beta": "β", "Delta": "Δ", "delta": "δ", "lambda": "λ", "pi": "π"}


def tidy_tex(text):
    """Inline LaTeX left in IEEE/Crossref titles ('100fJ ${\\cdot}$ K2', '$\\mu$W') → plain Unicode."""
    if "\\" not in (text or "") and "$" not in (text or ""):
        return text
    text = re.sub(r"\\(\w+)", lambda m: TEX.get(m[1], m[0]), text)
    text = re.sub(r"\^\{?(\d)\}?", lambda m: "⁰¹²³⁴⁵⁶⁷⁸⁹"[int(m[1])], text)
    text = re.sub(r"\^\{([^{}]*)\}|\^(\S)", lambda m: m[1] if m[1] is not None else m[2], text)  # ^{°} → °
    text = re.sub(r"\$\s*\{?\s*([^${}]{1,40}?)\s*\}?\s*\$", r"\1", text)  # $…$ and ${…}$
    return re.sub(r"\s*·\s*", "·", text)


def _clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"^\s*Abstract\s*[:.]?\s*", "", html.unescape(text), flags=re.I)
    return tidy_tex(re.sub(r"\s+", " ", text).strip())


# ---------- IEEE Xplore Metadata API ----------

def _ieee(params, cfg, store, log, api="ieee", budget=None):
    """One counted API call, or None when the budget is used up / no key. `api` names the counter in
    api_usage: 'ieee' = daily collection (ieee_daily_budget), 'ieee_topic' = --topic reserve."""
    key = os.environ.get("IEEE_API_KEY", "").strip()
    budget = cfg["ieee_daily_budget"] if budget is None else budget
    if not key or store.calls_today(api) >= budget:
        return None
    store.count_call(api)
    q = urllib.parse.urlencode({**params, "apikey": key, "format": "json"})
    try:
        return json.loads(_get(IEEE_URL + q, cfg))
    except Exception as e:
        log(f"  [ieee] {params}: {str(e).replace(key, '***')}")
        return {}


def _from_ieee(a, venue):
    doi = (a.get("doi") or "").lower()
    terms = a.get("index_terms") or {}
    kw = [t for grp in terms.values() for t in (grp.get("terms") or [])]
    d = a.get("insert_date") or ""
    return {"doi": doi, "title": _clean(a.get("title")),
            "authors": [x.get("full_name", "") for x in (a.get("authors") or {}).get("authors", [])],
            "venue": venue["short"], "venue_name": venue["name"],
            "published": a.get("publication_date") or (f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else str(a.get("publication_year", ""))),
            "abstract": _clean(a.get("abstract")), "source": "ieee-api", "article_number": a.get("article_number"),
            "index_terms": kw[:20], "ieee_cites": a.get("citing_paper_count")}


def ieee_venue_window(venue, cfg, store, start, end, log, start_record=1):
    """All papers IEEE inserted for `venue` between start..end. Returns (papers, next_start_record|None)."""
    out = []
    while True:
        r = _ieee({**venue["ieee_query"], "start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d"),
                   "max_records": 200, "start_record": start_record}, cfg, store, log)
        if r is None:
            return out, start_record  # budget gone mid-window: resume here next time
        arts = r.get("articles") or []
        for a in arts:
            if not a.get("doi"):
                continue
            if venue.get("container_regex") and not re.search(venue["container_regex"], a.get("publication_title", ""), re.I):
                continue
            out.append(_from_ieee(a, venue))
        start_record += len(arts)
        if not arts or start_record > (r.get("total_records") or 0):
            return out, None


def ieee_fill_doi(p, cfg, store, log):
    r = _ieee({"doi": p["doi"]}, cfg, store, log)
    arts = (r or {}).get("articles") or []
    if arts and arts[0].get("abstract"):
        a = _from_ieee(arts[0], {"short": p["venue"], "name": p["venue_name"]})
        store.update(p["doi"], {k: a[k] for k in ("abstract", "article_number", "index_terms", "ieee_cites")})
        return True
    return False


# ---------- Crossref ----------

def crossref_venue(venue, cfg, since):
    base = "https://api.crossref.org/works?"
    fields = "DOI,title,author,abstract,published-print,published-online,issued,created,container-title,reference"
    common = {"rows": cfg["crossref_rows_per_venue"], "select": fields, "mailto": cfg["contact_email"]}
    queries = [{"filter": ",".join([f"issn:{i}" for i in venue["issn"]] + [f"from-created-date:{since}"]), **common}] \
        if venue["issn"] else []  # no ISSN (ESSERC): an ISSN-less filter would return all of Crossref
    if venue["type"] == "conference":
        queries.append({"query.container-title": venue.get("title_query", venue["name"]),
                        "filter": f"prefix:10.1109,type:proceedings-article,from-created-date:{since}", **common})
    out = {}
    for q in queries:
        for it in json.loads(_get(base + urllib.parse.urlencode(q), cfg))["message"].get("items", []):
            ct = " ".join(it.get("container-title") or [])
            if venue.get("container_regex") and not re.search(venue["container_regex"], ct, re.I):
                continue
            if not (it.get("DOI") and it.get("title")):
                continue
            doi = it["DOI"].lower()
            parts = next(((it.get(k) or {}).get("date-parts") or [[None]] for k in
                          ("published-print", "published-online", "issued", "created") if it.get(k)), [[None]])[0]
            out[doi] = {"doi": doi, "title": _clean(" ".join(it["title"])),
                        "authors": [" ".join(x for x in (a.get("given"), a.get("family")) if x) for a in it.get("author", [])],
                        "venue": venue["short"], "venue_name": venue["name"],
                        "published": "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts) if p),
                        "abstract": _clean(it.get("abstract", "")), "source": "crossref",
                        "refs": sorted({f"doi:{r['DOI'].lower()}" for r in it.get("reference", []) if r.get("DOI")})}
    return list(out.values())


# ---------- Beyond IEEE: Nature / Science portfolio (OpenAlex + Crossref, 0 IEEE calls) ----------

def _oa_abstract(inv):
    return _clean(" ".join(w for _, w in sorted((i, w) for w, ps in (inv or {}).items() for i in ps)))


def nature_rss(bv, cfg, since, log):
    """Nature's public RSS (RDF). Faster than the indexes and has a one-sentence editorial summary in
    content:encoded. Redirects through idp.nature.com's session-cookie handshake are followed with a
    cookie jar. If a feed answers with a bot challenge (natelectron.rss served Fastly's `_fs-ch` page
    to Python on 2026-10-27), it fails to parse and is skipped: never work around the challenge."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    req = urllib.request.Request(bv["rss"], headers={"User-Agent": f"IC-Paper-Radar/2.0 (mailto:{cfg['contact_email']})"})
    try:
        with opener.open(req, timeout=40) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        log(f"  [beyond/rss] {bv['short']}: {e}")
        return []
    out = []
    for it in (e for e in root.iter() if e.tag.endswith("item")):
        f = {}
        for c in it:
            f.setdefault(c.tag.split("}")[-1], []).append((c.text or "").strip())
        doi = (f.get("doi") or [""])[0].lower()
        day = (f.get("date") or [""])[0][:10]
        if not doi or (day and day < since):
            continue
        summary = _clean((f.get("encoded") or [""])[0])
        summary = re.sub(r"^.*?Published online:.*?doi:\S+\s*", "", summary)  # drop the "Journal, Published online: …; doi:…" prefix
        out.append({"doi": doi, "title": _clean((f.get("title") or [""])[0]), "venue": bv["short"], "venue_name": bv["name"],
                    "authors": f.get("creator") or [], "published": day, "abstract": summary, "source": "nature-rss"})
    return out


def beyond_fetch(bv, cfg, since, log):
    """All research articles of one Nature/Science venue since `since`, merged from OpenAlex and Crossref
    (Springer Nature restricts abstracts in OpenAlex; Crossref sometimes has them, sometimes neither does)."""
    out = {}
    page = 1
    while page:
        # page numbers, not cursors: cursor paging returned HTTP 401 for Nature Communications (2026-10-27)
        q = urllib.parse.urlencode({"filter": f"primary_location.source.issn:{bv['issn']},from_publication_date:{since},type:article",
                                    "per-page": 200, "page": page, "mailto": cfg["contact_email"],
                                    "select": "id,doi,title,authorships,publication_date,abstract_inverted_index,referenced_works,cited_by_count"})
        try:
            r = json.loads(_get(f"https://api.openalex.org/works?{q}", cfg))
        except Exception as e:
            log(f"  [beyond/openalex] {bv['short']} page {page}: {e}")
            break
        for w in r["results"]:
            doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
            if doi and w.get("title"):
                out[doi] = {"doi": doi, "title": _clean(w["title"]), "venue": bv["short"], "venue_name": bv["name"],
                            "authors": [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []],
                            "published": w.get("publication_date") or "", "abstract": _oa_abstract(w.get("abstract_inverted_index")),
                            "oa_id": w["id"].rsplit("/", 1)[-1], "cited_by": w.get("cited_by_count"), "source": "openalex",
                            "refs": ["oa:" + x.rsplit("/", 1)[-1] for x in w.get("referenced_works") or []]}
        page = page + 1 if len(r["results"]) == 200 and page < 10 else None
    try:
        q = urllib.parse.urlencode({"filter": f"issn:{bv['issn']},from-created-date:{since},type:journal-article", "rows": 500,
                                    "select": "DOI,title,author,abstract,created", "mailto": cfg["contact_email"]})
        for it in json.loads(_get("https://api.crossref.org/works?" + q, cfg))["message"].get("items", []):
            doi = it["DOI"].lower()
            p = out.setdefault(doi, {"doi": doi, "title": _clean(" ".join(it.get("title") or [""])), "venue": bv["short"],
                                     "venue_name": bv["name"], "source": "crossref", "abstract": "",
                                     "authors": [" ".join(x for x in (a.get("given"), a.get("family")) if x) for a in it.get("author", [])],
                                     "published": it["created"]["date-time"][:10]})
            if not p["abstract"] and it.get("abstract"):
                p["abstract"] = _clean(it["abstract"])
    except Exception as e:
        log(f"  [beyond/crossref] {bv['short']}: {e}")
    if bv.get("rss"):
        for p in nature_rss(bv, cfg, since, log):
            q = out.setdefault(p["doi"], p)
            if q is not p and not q.get("abstract") and p["abstract"]:
                q["abstract"] = p["abstract"]  # editorial summary only where no real abstract exists
            if q is not p and not q.get("authors"):
                q["authors"] = p["authors"]
    return [p for p in out.values() if p["title"]]


def _any(terms, text):
    return [t.split("::")[0][3:] if t.startswith("re:") else t for t in terms if _kw_hit(t, text)]


def beyond_gate(p, bv, cfg):
    """Dual-key gate: Key 1 (application theme) AND Key 2 (hardware/IC proof); Nature Electronics needs
    Key 1 or any pillar keyword only. Returns (passed, key1_hits, key2_hits, reason)."""
    b = cfg["beyond_ieee"]
    text = f"{p['title']} {p.get('abstract') or ''}"
    if any(re.search(rf"\b{re.escape(x)}", text, re.I) for x in b["exclude"]):
        return False, [], [], "excluded (pure physics/chemistry/biology)"
    k1, k2 = _any(b["key1_themes"], text), _any(b["key2_hardware"], text)
    if not bv["two_key"]:
        ok = bool(k1) or score(p, cfg)[0] > 0
        return ok, k1, k2, "electronics venue: theme or pillar keyword" if ok else "no theme/pillar keyword"
    if k1 and k2:
        return True, k1, k2, "both keys"
    return False, k1, k2, "key 1 only" if k1 else ("key 2 only" if k2 else "no key")


def beyond_score(p, bv, cfg):
    """(passed, score, hits): beyond papers rank by pillar score + gate strength; silicon/simulation tags don't apply."""
    ok, k1, k2, _ = beyond_gate(p, bv, cfg)
    if not ok:
        return False, 0, []
    s, hits = score(p, cfg)
    gate_hits = [f"theme:{x}" for x in k1[:3]] + [f"hw:{x}" for x in k2[:3]]
    return True, max(s, 0) + len(k1) + len(k2), [h for h in hits if h not in ("silicon_verified", "simulation_only")] + gate_hits


def _pool_add(papers, bv, cfg, store, today):
    """Gate-passing papers → store as status 'pool' (the board is filled by beyond_replenish). Returns #passed."""
    passed = 0
    for p in papers:
        ok, s, hits = beyond_score(p, bv, cfg)
        if not ok:
            continue
        passed += 1
        if store.upsert({**p, "grp": "beyond", "first_seen": today.isoformat()}, "pool"):
            store.update(p["doi"], {"score": s, "hits": hits})
    return passed


def collect_beyond(cfg, store, today, week, log=print):
    since = (today - timedelta(days=cfg["beyond_ieee"]["lookback_days"])).isoformat()
    st = {}
    for bv in cfg["beyond_ieee_venues"]:
        got = beyond_fetch(bv, cfg, since, log)
        passed = _pool_add(got, bv, cfg, store, today)
        st[bv["short"]] = (len(got), passed)
        log(f"  {bv['short']:<12} {len(got):>4} articles, {passed} passed the gate")
    pool_search(cfg, store, today, log)
    return st


def pool_search(cfg, store, today, log=print, force=False):
    """The 1-year Beyond-IEEE pool: per venue, one OpenAlex search (OR of key1_themes) over the last pool_days,
    every pool_refresh_days (meta 'beyond_pool_searched'). 0 IEEE calls. Returns #gate-passing papers seen."""
    b = cfg["beyond_ieee"]
    if not b.get("key1_themes"):  # Starter Edition: no Beyond-IEEE themes configured yet
        return 0
    last = store.meta("beyond_pool_searched")
    if not force and last and (today - date.fromisoformat(last)).days < b.get("pool_refresh_days", 7):
        return 0
    since = (today - timedelta(days=b.get("pool_days", 365))).isoformat()
    search = " OR ".join(f'"{t}"' for t in b["key1_themes"])
    total, failed = 0, False
    for bv in cfg["beyond_ieee_venues"]:
        got, page, waits = [], 1, 0
        while page:
            q = urllib.parse.urlencode({"filter": f"primary_location.source.issn:{bv['issn']},from_publication_date:{since},type:article",
                                        "search": search, "per-page": 200, "page": page, "mailto": cfg["contact_email"],
                                        "select": "id,doi,title,authorships,publication_date,abstract_inverted_index,"
                                                  "referenced_works,cited_by_count"})
            time.sleep(1.5)  # OpenAlex answered 429 to ~30 back-to-back search pages (2026-10-28)
            try:
                r = json.loads(_get(f"https://api.openalex.org/works?{q}", cfg))
            except Exception as e:
                if _budget_gone(e):  # 2026-10-28: waiting this out kept a run asleep for 40 min
                    log(f"  [beyond/pool] OpenAlex search budget used up (Retry-After {e.headers.get('Retry-After')} s); "
                        "the pool is searched again on the next run")
                    failed = True
                    break
                if "429" in str(e) and waits < 2:
                    waits += 1
                    log(f"  [beyond/pool] {bv['short']} page {page}: 429, waiting {30 * waits} s")
                    time.sleep(30 * waits)
                    continue
                log(f"  [beyond/pool] {bv['short']} page {page}: {e}")
                failed = True
                break
        if failed and not got:
            break  # budget gone: don't try the other venues today
            for w in r["results"]:
                doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
                if doi and w.get("title"):
                    got.append({"doi": doi, "title": _clean(w["title"]), "venue": bv["short"], "venue_name": bv["name"],
                                "authors": [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []],
                                "published": w.get("publication_date") or "", "abstract": _oa_abstract(w.get("abstract_inverted_index")),
                                "oa_id": w["id"].rsplit("/", 1)[-1], "cited_by": w.get("cited_by_count"), "source": "openalex",
                                "refs": ["oa:" + x.rsplit("/", 1)[-1] for x in w.get("referenced_works") or []]})
            page = page + 1 if len(r["results"]) == 200 and page < 30 else None
        n = _pool_add(got, bv, cfg, store, today)
        total += n
        log(f"  pool {bv['short']:<12} {len(got):>5} matched the themes ({b.get('pool_days', 365)} d), {n} passed the gate")
    if not failed:  # a venue that failed is searched again on the next run
        store.meta("beyond_pool_searched", today.isoformat())
    return total


def beyond_replenish(cfg, store, week, log=print):
    """Keep board_size undocumented Beyond papers on the board: the best 'pool' papers (score, then newest)
    become this week's candidates. Returns how many were promoted."""
    board = store.where("grp='beyond' AND status IN ('candidate','reported') AND COALESCE(user_mark,'normal')='normal' "
                        "AND COALESCE(cited,0)=0")
    need = cfg["beyond_ieee"].get("board_size", 10) - len(board)
    if need <= 0:
        return 0
    pool = store.where("grp='beyond' AND status='pool' AND COALESCE(user_mark,'normal')='normal' AND COALESCE(cited,0)=0")
    pool.sort(key=lambda p: str(p.get("published") or ""), reverse=True)  # newest first …
    pool.sort(key=lambda p: -(p["score"] or 0))                             # … within each score (stable sort)
    for p in pool[:need]:
        store.update(p["doi"], {"status": "candidate", "week": week})
        log(f"  Beyond board +1: {p['venue']} {p['published']} ({p['score']}) {p['title'][:70]}")
    return len(pool[:need])


def rescore_all(cfg, store, log=print):
    """Re-score every paper after a keyword/pillar change (0 calls). Skipped IEEE papers that now reach
    min_score go back to 'candidate' this week; Beyond papers are re-gated (a pool paper that no longer
    passes stays in the store, ranked 0). Returns {'changed': n, 'unskipped': n}."""
    anchors = anchor_refs(cfg, store, log)
    week, _ = week_of(date.today())
    bvs = {bv["short"]: bv for bv in cfg["beyond_ieee_venues"]}
    changed = unskipped = 0
    for p in store.where("1=1"):
        if p.get("grp") == "beyond":
            bv = bvs.get(p["venue"])
            if not bv:
                continue
            ok, s, hits = beyond_score(p, bv, cfg)
            s = s if ok else 0
        else:
            s, hits = score(p, cfg, anchors)
        upd = {}
        if (s, hits) != (p["score"], p["hits"]):
            upd.update(score=s, hits=hits)
            changed += 1
        if p.get("grp") != "beyond" and p["status"] == "skipped" and s >= cfg["min_score"]:
            upd.update(status="candidate", week=week, related=find_related(p, store))
            unskipped += 1
        if upd:
            store.update(p["doi"], upd)
    log(f"Re-score: {changed} scores changed, {unskipped} skipped papers back as candidates")
    return {"changed": changed, "unskipped": unskipped}


# ---------- OpenAlex ----------

def openalex_enrich(papers, cfg, store, log):
    """OpenAlex id, references (oa:W…), cited-by count and missing abstracts; 50 DOIs per request."""
    n = 0
    for i in range(0, len(papers), 50):
        chunk = {p["doi"]: p for p in papers[i:i + 50]}
        q = urllib.parse.urlencode({"filter": "doi:" + "|".join(chunk), "per-page": 50, "mailto": cfg["contact_email"],
                                    "select": "id,doi,abstract_inverted_index,referenced_works,cited_by_count"})
        try:
            res = json.loads(_get(f"https://api.openalex.org/works?{q}", cfg))["results"]
        except Exception as e:
            log(f"  [openalex] {e}")
            continue
        for r in res:
            p = chunk.get((r.get("doi") or "").replace("https://doi.org/", "").lower())
            if not p:
                continue
            upd = {"oa_id": r["id"].rsplit("/", 1)[-1], "cited_by": r.get("cited_by_count")}
            refs = set(p.get("refs") or []) | {"oa:" + w.rsplit("/", 1)[-1] for w in r.get("referenced_works") or []}
            if refs:
                upd["refs"] = sorted(refs)
            inv = r.get("abstract_inverted_index")
            if inv and not p.get("abstract"):
                upd["abstract"] = _clean(" ".join(w for _, w in sorted((i, w) for w, ps in inv.items() for i in ps)))
                n += 1
            store.update(p["doi"], upd)
    return n


def openalex_works(ids, cfg):
    """Metadata for up to 50 OpenAlex work ids (used for 'key prior work')."""
    if not ids:
        return []
    q = urllib.parse.urlencode({"filter": "openalex_id:" + "|".join(ids[:50]), "per-page": 50, "mailto": cfg["contact_email"],
                                "select": "id,doi,display_name,publication_year,publication_date,cited_by_count,authorships,"
                                          "primary_location,abstract_inverted_index"})
    return json.loads(_get(f"https://api.openalex.org/works?{q}", cfg))["results"]


# ---------- scoring, dedup ----------

def _fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[.\s]+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip().lower()


def _name_key(name):
    """('kofi', 'makinwa') from 'Kofi A. A. Makinwa'; ('d', 'blaauw') from 'D. Blaauw'; (None, 'makinwa') from 'Makinwa'."""
    parts = _fold(name).split(" ")
    return (parts[0] if len(parts) > 1 else None), parts[-1]


def vip_match(authors, vips):
    """Exact first-given-name + surname match. An initial-only VIP entry ('T. Jang') matches only authors
    listed with an initial, so a common surname never triggers on an unrelated full name
    ('Taehoon Jang' ≠ 'T. Jang'). A surname-only entry ('Makinwa') matches the surname alone."""
    keys = [_name_key(a) for a in authors or []]
    hits = []
    for v in vips:
        vg, vf = _name_key(v)
        if any(f == vf and (vg is None or g == vg) for g, f in keys):
            hits.append(v)
    return hits


def verification(p, cfg):
    """silicon_verified / simulation_only / unclear, from the title + abstract."""
    vc = cfg["verification"]
    text = f"{p['title']} {p.get('abstract') or ''}".lower()
    si = any(c.lower() in text for c in vc["silicon_cues"])
    sim = any(c.lower() in text for c in vc["simulation_cues"])
    if si:
        return "silicon_verified"
    if sim:
        return "simulation_only"
    return "unclear"


def _kw_hit(kw, text):
    if kw.startswith("re:"):
        return re.search(kw.split("::", 1)[1], text)
    flags = 0 if kw.isupper() else re.I  # acronyms (AFE, OTA, CDC, MPPT) must match case
    # "energy harvester" also matches "Energy-Harvesters"; "rectifier" matches "rectifiers"
    body = r"[\s-]".join(re.escape(w) for w in re.split(r"[\s-]+", kw))
    return re.search(rf"(?<![\w-]){body}(?:e?s)?(?![\w-])", text, flags)


def _kw_norm(kw):
    return re.sub(r"[\s-]+", " ", kw.lower())


def score(p, cfg, anchor_refs=frozenset()):
    own = f"{p['title']} {p['title']} {p.get('abstract') or ''}"
    text = f"{own} {' '.join(p.get('index_terms') or [])}"
    total, hits, seen = 0, [], set()
    for kw, w in cfg["positive_keywords"].items():
        if kw.startswith("re:") or _kw_norm(kw) not in seen:
            seen.add(_kw_norm(kw))
        else:
            continue  # "low-noise" / "low noise" count once
        if w and _kw_hit(kw, text):
            total, hits = total + w, hits + [kw[3:].split("::", 1)[0] if kw.startswith("re:") else kw]
    # A negative keyword (telecom / high-speed digital) zeroes only a paper with no pillar keyword at all; with
    # a positive hit, or a title matching negative_override, it costs negative_penalty, once.
    # Not against index terms: IEEE auto-tags bandgaps with "Photonic band gap".
    neg = next((n for n in cfg["negative_keywords"] if re.search(rf"\b{re.escape(n)}\b", own, re.I)), None)
    if neg:
        override = cfg.get("negative_override") and re.search(cfg["negative_override"], p["title"] or "")
        if not hits and not override:
            return 0, []
        total, hits = total + cfg.get("negative_penalty", -5), [f"negative:{neg}"] + hits
    if anchor_refs & set(p.get("refs") or []):
        total, hits = total + cfg["anchor_boost"], hits + ["cites an anchor"]
    for v in vip_match(p.get("authors"), cfg.get("vip_authors", [])):
        total, hits = total + cfg.get("vip_boost", 3), hits + [f"vip_author:{v}"]
        break  # one boost per paper, however many VIP co-authors
    if p.get("abstract") or p.get("user_silicon"):
        status = p.get("user_silicon") or verification(p, cfg)  # the user's call after reading the PDF wins
        if status == "silicon_verified":
            total, hits = total + cfg["verification"]["silicon_bonus"], hits + ["silicon_verified"]
        elif status == "simulation_only":
            total, hits = total + cfg["verification"]["simulation_penalty"], hits + ["simulation_only"]
    return total, hits


def _norm(t):
    return re.sub(r"[^a-z0-9 ]", " ", (t or "").lower()).split()


def find_related(p, store):
    """Same work under another DOI (conference ↔ journal extension, re-deposits)."""
    words = set(_norm(p["title"]))
    fam = (p.get("authors") or [""])[0].split(" ")[-1].lower()
    out = []
    for q in store.where("doi != ?", (p["doi"],)):
        qw = set(_norm(q["title"]))
        if not qw or len(words & qw) / len(words | qw) < 0.5:
            continue
        ratio = SequenceMatcher(None, " ".join(_norm(p["title"])), " ".join(_norm(q["title"]))).ratio()
        same_first = fam and fam == (q.get("authors") or [""])[0].split(" ")[-1].lower()
        if ratio > 0.9 or (ratio > 0.7 and same_first):
            out.append({"doi": q["doi"], "venue": q["venue"], "published": q["published"], "title": q["title"]})
    return out[:3]


def anchor_refs(cfg, store, log):
    """Anchor DOIs as ref keys (doi:… and their OpenAlex oa:W…), resolved once and cached."""
    anchors = [a.lower() for a in cfg.get("anchors", [])]
    keys = {f"doi:{a}" for a in anchors}
    cached = store.meta("anchor_oa") or {}
    todo = [a for a in anchors if a not in cached]
    if todo:
        try:
            q = urllib.parse.urlencode({"filter": "doi:" + "|".join(todo), "select": "id,doi", "mailto": cfg["contact_email"]})
            for r in json.loads(_get(f"https://api.openalex.org/works?{q}", cfg))["results"]:
                cached[r["doi"].replace("https://doi.org/", "").lower()] = r["id"].rsplit("/", 1)[-1]
            store.meta("anchor_oa", cached)
        except Exception as e:
            log(f"  [anchors] {e}")
    return frozenset(keys | {f"oa:{w}" for w in cached.values()})


# ---------- the daily collection ----------

def collect(cfg, store, today, log=print, backfill=True):
    since = today - timedelta(days=cfg["lookback_days"])
    st = {"per_venue": {}, "errors": [], "new": 0}
    week, _ = week_of(today)
    ieee_notice(log)

    for v in cfg["venues"]:
        got = {}
        if v.get("ieee_query"):
            papers, _ = ieee_venue_window(v, cfg, store, since, today, log)
            got.update({p["doi"]: p for p in papers})
        try:
            for p in crossref_venue(v, cfg, since.isoformat()):
                got[p["doi"]] = {**p, **{k: x for k, x in got.get(p["doi"], {}).items() if x}}
        except Exception as e:
            st["errors"].append(f"{v['short']} crossref: {e}")
        new = sum(store.upsert({**p, "first_seen": today.isoformat()}, "pending") for p in got.values())
        st["per_venue"][v["short"]] = (len(got), new)
        st["new"] += new
        log(f"  {v['short']:<8} {len(got):>4} records, {new} new")

    # per-DOI IEEE lookups for papers still missing an abstract (title matches first)
    pend = [p for p in store.where("status IN ('pending','candidate') AND (abstract IS NULL OR abstract='') "
                                   "AND doi LIKE '10.1109/%'")]
    pend.sort(key=lambda p: -score(p, cfg)[0])
    st["ieee_doi"] = sum(ieee_fill_doi(p, cfg, store, log) for p in pend[:cfg["ieee_doi_lookups_max"]])

    recent = store.where("status IN ('pending','candidate') AND (oa_id IS NULL OR oa_id='')")
    st["openalex"] = openalex_enrich(recent, cfg, store, log)

    # classify
    anchors = anchor_refs(cfg, store, log)
    st["new_candidates"] = []
    # skipped papers inside the lookback window are re-scored too, so keyword/config fixes take effect
    for p in store.where("status='pending' OR (status='skipped' AND first_seen >= ?)", (since.isoformat(),)):
        s, hits = score(p, cfg, anchors)
        age = (today - date.fromisoformat(p["first_seen"])).days
        if s >= cfg["min_score"]:
            store.update(p["doi"], {"score": s, "hits": hits, "status": "candidate", "week": week,
                                    "related": find_related(p, store)})
            st["new_candidates"].append(p["doi"])
        elif p.get("abstract") or age > cfg["abstract_give_up_days"]:
            store.update(p["doi"], {"score": s, "hits": hits, "status": "skipped"})
        else:
            store.update(p["doi"], {"score": s, "hits": hits})
    # re-score open candidates (late abstracts, config changes); demote those now below the threshold
    for p in store.where("status='candidate' AND grp='ieee'"):
        s, hits = score(p, cfg, anchors)
        if s < cfg["min_score"] and not p.get("pin"):  # a pinned paper stays, whatever its score
            store.update(p["doi"], {"score": s, "hits": hits, "status": "skipped"})
        elif (s, hits) != (p["score"], p["hits"]):
            store.update(p["doi"], {"score": s, "hits": hits})

    log("  -- beyond IEEE (OpenAlex/Crossref) --")
    st["beyond"] = collect_beyond(cfg, store, today, week, log)
    st["backfill"] = run_backfill(cfg, store, today, log) if backfill else 0
    st["ieee_calls"] = store.calls_today("ieee")
    return st


def run_backfill(cfg, store, today, log):
    """Spend the rest of today's IEEE budget pulling older months into the corpus (status archive)."""
    floor = date.fromisoformat(cfg["backfill_floor"])
    venues = [v for v in cfg["venues"] if v.get("ieee_query")]
    added, idle = 0, 0
    while idle < len(venues) and store.calls_today("ieee") < cfg["ieee_daily_budget"] and os.environ.get("IEEE_API_KEY", "").strip():
        v = venues[(store.meta("backfill_rr") or 0) % len(venues)]
        store.meta("backfill_rr", (store.meta("backfill_rr") or 0) + 1)
        cur = store.meta(f"backfill:{v['short']}") or {
            "end": (today - timedelta(days=cfg["lookback_days"] + 1)).isoformat(), "start_record": 1}
        end = date.fromisoformat(cur["end"])
        if end <= floor:
            idle += 1
            continue
        idle = 0
        start = max(floor, end - timedelta(days=cfg["backfill_chunk_days"] - 1))
        papers, resume = ieee_venue_window(v, cfg, store, start, end, log, cur["start_record"])
        for p in papers:
            p["score"], p["hits"] = score(p, cfg)
            added += store.upsert({**p, "first_seen": today.isoformat()}, "archive")
        store.meta(f"backfill:{v['short']}", {"end": cur["end"], "start_record": resume} if resume else
                   {"end": (start - timedelta(days=1)).isoformat(), "start_record": 1})
    log(f"  backfill: +{added} corpus papers")
    return added


if __name__ == "__main__":
    import sys
    from store import Store
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    s = Store(HERE / cfg["paths"]["store_file"])
    st = collect(cfg, s, date.today(), backfill="--no-backfill" not in sys.argv)
    print(json.dumps(st, indent=1, ensure_ascii=False))
    print(s.counts())
