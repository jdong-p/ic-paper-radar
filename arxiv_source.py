"""arXiv as a narrow, query-driven paper source, through arXiv's official API (export.arxiv.org/api/query).

Off unless config.json sets "arxiv": {"enabled": true}. The weekly run (fetcher.collect) runs each raw arXiv
search_query in "queries", newest first, page by page back to the lookback window, and keeps only papers that
pass the local filter: at least one term of every group in "must_all" and none of "exclude_any", in the title
or abstract. Everything else is dropped without being stored. Kept papers enter the normal flow (status
'pending', scored like the rest; "pillar" files them under that pillar) with venue 'arXiv'. --topic adds an
arXiv stage only for a topic that itself passes must_all.

arXiv's API terms: at most one request every 3 seconds, one connection at a time. Papers are stored with
their arXiv DOI (10.48550/arxiv.<id>, version stripped); a preprint whose journal DOI is already in the store
is skipped. They stay out of --export-share / --sync-data-repo unless "share" (or selected / cited).
"""
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date

import fetcher

API = "https://export.arxiv.org/api/query?"
NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
_last = [0.0]


def enabled(cfg):
    return bool((cfg.get("arxiv") or {}).get("enabled"))


def share_skip(cfg):
    """True when the share database / peer overlay should leave this radar's arXiv rows out."""
    return enabled(cfg) and not (cfg.get("arxiv") or {}).get("share")


def _query(cfg, search_query, size, store=None, log=print, start=0):
    """One API call (spaced by min_interval_s), parsed into paper dicts for the store."""
    ac = cfg.get("arxiv") or {}
    wait = max(3, ac.get("min_interval_s", 3)) - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    q = urllib.parse.urlencode({"search_query": search_query, "start": start, "max_results": size,
                                "sortBy": "submittedDate", "sortOrder": "descending"})
    try:
        if store is not None:
            store.count_call("arxiv")
        root = ET.fromstring(fetcher._get(API + q, cfg))
    except Exception as e:
        log(f"  [arxiv] {e}")
        return []
    finally:
        _last[0] = time.time()
    out = []
    for e in root.findall("a:entry", NS):
        aid = re.sub(r"v\d+$", "", (e.findtext("a:id", "", NS) or "").rsplit("/abs/", 1)[-1])
        if not aid:
            continue
        pc = e.find("x:primary_category", NS)
        cat = pc.get("term", "") if pc is not None else ""
        out.append({"doi": f"10.48550/arxiv.{aid}".lower(), "title": fetcher._clean(e.findtext("a:title", "", NS)),
                    "authors": [a.findtext("a:name", "", NS) for a in e.findall("a:author", NS)],
                    "venue": "arXiv", "venue_name": f"arXiv ({cat})" if cat else "arXiv",
                    "published": (e.findtext("a:published", "", NS) or "")[:10],
                    "abstract": fetcher._clean(e.findtext("a:summary", "", NS)), "source": "arxiv",
                    "journal_doi": (e.findtext("x:doi", "", NS) or "").lower()})
    return out


def _norm(text):
    return " " + re.sub(r"[\W_]+", " ", text.lower()).strip() + " "


def passes(text, cfg):
    """The local filter: a term of every must_all group and no exclude_any term (whole words, plural -s,
    case and punctuation ignored)."""
    ac, t = cfg.get("arxiv") or {}, _norm(text)
    has = lambda words: any(n in t or n[:-1] + "s " in t for n in map(_norm, words))
    return all(has(g) for g in ac.get("must_all") or [] if g) and not has(ac.get("exclude_any") or [])


def _keep(papers, store, cfg):
    """Papers that pass the filter and whose journal version is not in the store yet; helper field stripped."""
    out = []
    for p in papers:
        jd = p.pop("journal_doi", "")
        if passes(f"{p['title']} {p['abstract']}", cfg) and not (jd and store is not None and store.get(jd)):
            if (cfg.get("arxiv") or {}).get("pillar"):
                p["pillar"] = int(cfg["arxiv"]["pillar"])
            out.append(p)
    return out


def _scoped(cfg, q):
    cats = (cfg.get("arxiv") or {}).get("categories") or []
    return f"({' OR '.join('cat:' + c for c in cats)}) AND ({q})" if cats else q


def weekly(cfg, store, since, log=print):
    """New papers since `since` (a date) from every query, newest first, paged until a page reaches back past
    `since` or max_pages is hit. Returns the kept paper dicts (not stored)."""
    ac = cfg.get("arxiv") or {}
    size, cap = ac.get("max_results", 50), max(1, ac.get("max_pages", 4))
    got = {}
    for i, q in enumerate(ac.get("queries") or [], 1):
        fresh, n, page = [], 0, 0
        while page < cap:
            papers = _query(cfg, _scoped(cfg, q), size, store, log, start=page * size)
            page += 1
            n += len(papers)
            new = [p for p in papers if p["published"] and date.fromisoformat(p["published"]) >= since]
            fresh += new
            if len(papers) < size or len(new) < len(papers):  # the last page, or past `since`
                break
        else:
            log(f"  [arxiv] query {i}: max_pages ({cap}) reached before {since.isoformat()}; older results not fetched")
        kept = _keep(fresh, store, cfg)
        for p in kept:
            got.setdefault(p["doi"], p)
        log(f"  arXiv q{i:<6} {n:>4} records, {len(fresh)} since {since.isoformat()}, {len(kept)} pass the filter")
    return list(got.values())


def topic_search(groups, cfg, store=None, log=print):
    """--topic stage, only for a topic that passes must_all: every concept group must match (title or abstract)."""
    ac = cfg.get("arxiv") or {}
    if not passes(" ".join(t for g in groups for t in g if not t.startswith("re:")), cfg):
        log("  arXiv: skipped (the topic does not match every arxiv.must_all group)")
        return {}
    parts = []
    for g in groups:
        words = [w.replace('"', "") for w in g if not w.startswith("re:")][:4]
        if words:
            parts.append("(" + " OR ".join(f'ti:"{w}" OR abs:"{w}"' for w in words) + ")")
    if not parts:
        return {}
    papers = _keep(_query(cfg, _scoped(cfg, " AND ".join(parts)), ac.get("max_results", 50), store, log), store, cfg)
    log(f"  arXiv: {len(papers)} papers")
    return {p["doi"]: p for p in papers}
