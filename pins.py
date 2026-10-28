"""Human-controlled pillar curation (2026-10-28): anchors and hand-added papers as visible catalog entries.

  briefing.py --add "<DOI or title words>" [--pillar N] [--cite]

A pinned paper has status 'pinned' (collection, catch-up and Friday's finalize never touch it), `pin` =
'anchor' (from config `anchors`, tagged 🏛️ Classic / Anchor) or 'manual' (--add, tagged 📌 Pinned), and an
optional `pillar` that overrides the keyword/digest guess. Missing papers are fetched from OpenAlex
(free), with one counted IEEE DOI lookup only when OpenAlex has no abstract.
"""
import json
import re
import urllib.parse
from datetime import date
from difflib import SequenceMatcher

from env_guard import ensure_minisforum_env

ensure_minisforum_env()
import curation
import fetcher
import topic

OA_SELECT = ("id,doi,display_name,publication_year,publication_date,authorships,primary_location,"
             "abstract_inverted_index,referenced_works,cited_by_count")


def _oa(params, cfg):
    q = urllib.parse.urlencode({**params, "mailto": cfg["contact_email"], "select": OA_SELECT})
    return json.loads(fetcher._get("https://api.openalex.org/works?" + q, cfg))["results"]


def _from_oa(w, cfg):
    doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
    source = (w.get("primary_location") or {}).get("source") or {}
    src = source.get("display_name") or ""
    issns = set(source.get("issn") or [])  # "Circuits & Systems II" doesn't match the configured name; the ISSN does
    v = topic._venue_of(src, cfg) or next((x for x in cfg["venues"] if issns & set(x["issn"])), None)
    return {"doi": doi, "title": fetcher._clean(w.get("display_name")),
            "venue": v["short"] if v else (src[:20] or "n/a"), "venue_name": v["name"] if v else src,
            "published": w.get("publication_date") or str(w.get("publication_year") or ""),
            "authors": [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []],
            "abstract": fetcher._oa_abstract(w.get("abstract_inverted_index")),
            "oa_id": w["id"].rsplit("/", 1)[-1], "cited_by": w.get("cited_by_count") or 0,
            "refs": ["oa:" + x.rsplit("/", 1)[-1] for x in w.get("referenced_works") or []], "source": "openalex"}


def fetch(dois, cfg, store, log=print):
    """Put DOIs that aren't in the store yet into it (status 'pinned', scored). Returns the DOIs found."""
    todo = [d for d in dict.fromkeys(d.lower() for d in dois) if not store.get(d)]
    found = []
    for i in range(0, len(todo), 50):
        try:
            res = _oa({"filter": "doi:" + "|".join(todo[i:i + 50]), "per-page": 50}, cfg)
        except Exception as e:
            log(f"  [pins/openalex] {e}")
            continue
        for w in res:
            p = _from_oa(w, cfg)
            if p["doi"] in todo:
                store.upsert({**p, "first_seen": date.today().isoformat()}, "pinned")
                found.append(p["doi"])
    for d in [d for d in todo if d not in found]:  # OpenAlex down or rate-limited: Crossref has the metadata
        p = _from_crossref(d, cfg, log)
        if p:
            store.upsert({**p, "first_seen": date.today().isoformat()}, "pinned")
            found.append(d)
    for d in found:
        p = store.get(d)
        if not p.get("abstract") and d.startswith("10.1109/"):
            fetcher.ieee_fill_doi(p, cfg, store, log)  # one counted IEEE call; skipped when the budget is used up
            p = store.get(d)
        s, hits = fetcher.score(p, cfg)
        store.update(d, {"score": s, "hits": hits})
    for d in set(todo) - set(found):
        log(f"  [pins] {d}: not found in OpenAlex or Crossref")
    return found


def _from_crossref(doi, cfg, log):
    """One DOI from Crossref (title, authors, venue, date; abstract only when deposited). The OpenAlex id,
    references and a missing abstract are filled later by relations.catalog_lineage()."""
    try:
        it = json.loads(fetcher._get(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}?"
                                     + urllib.parse.urlencode({"mailto": cfg["contact_email"]}), cfg))["message"]
    except Exception as e:
        log(f"  [pins/crossref] {doi}: {e}")
        return None
    src = " ".join(it.get("container-title") or [])
    v = topic._venue_of(src, cfg) or next((x for x in cfg["venues"] if set(it.get("ISSN") or []) & set(x["issn"])), None)
    parts = next(((it.get(k) or {}).get("date-parts") or [[None]] for k in
                  ("published-print", "published-online", "issued") if it.get(k)), [[None]])[0]
    return {"doi": doi, "title": fetcher._clean(" ".join(it.get("title") or [])),
            "authors": [" ".join(x for x in (a.get("given"), a.get("family")) if x) for a in it.get("author", [])],
            "venue": v["short"] if v else (src[:20] or "n/a"), "venue_name": v["name"] if v else src,
            "published": "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts) if p),
            "abstract": fetcher._clean(it.get("abstract", "")), "source": "crossref",
            "refs": sorted({f"doi:{r['DOI'].lower()}" for r in it.get("reference", []) if r.get("DOI")})}


def _pin(store, doi, kind, pillar=None):
    p = store.get(doi)
    upd = {"pin": p.get("pin") or kind}  # an anchor stays an anchor when it is also --add-ed
    if pillar:
        upd["pillar"] = pillar
    if p["status"] not in ("candidate", "reported"):  # this week's / reported papers keep their status
        upd["status"] = "pinned"
    store.update(doi, upd)


def sync_anchors(store, cfg, log=print):
    """Every config anchor becomes a visible 🏛️ catalog entry (fetched once if missing). Returns how many are pinned."""
    anchors = [a.lower() for a in cfg.get("anchors", [])]
    fetch(anchors, cfg, store, log)
    n = 0
    for d in anchors:
        if store.get(d):
            _pin(store, d, "anchor")
            n += 1
    return n


def resolve(needle, cfg, store, log=print):
    """DOI or title words → one DOI, or None (candidates are listed so the user can pass the DOI)."""
    n = needle.strip()
    m = re.search(r"10\.\d{4,9}/\S+", n)
    if m:
        doi = m[0].rstrip(".,;").lower()
        if store.get(doi) or fetch([doi], cfg, store, log):
            return doi
        log(f"No paper with DOI {doi} in the store or OpenAlex.")
        return None
    low = n.lower()
    hits = store.where("lower(title) LIKE ?", (f"%{low}%",))
    if len(hits) == 1:
        return hits[0]["doi"]
    if not hits:
        try:
            res = [_from_oa(w, cfg) for w in _oa({"search": n, "per-page": 5}, cfg)]
        except Exception as e:
            log(f"  [pins/openalex] {e}")
            res = []
        res = [r for r in res if r["doi"]]
        best = [r for r in res if SequenceMatcher(None, low, r["title"].lower()).ratio() > 0.9]
        if len(best) == 1 or len(res) == 1:
            doi = (best or res)[0]["doi"]
            return doi if store.get(doi) or fetch([doi], cfg, store, log) else None
        hits = res
    log(f"'{needle}' matches {len(hits)} papers; pass the DOI instead:")
    for p in hits[:8]:
        log(f"  {p['doi']}  {p['venue']} {p['published']}  {p['title'][:90]}")
    return None


def add(needle, cfg, store, pillar=None, cite=False, log=print):
    """--add: fetch if needed, pin into the active catalog (bypassing min_score and date windows)."""
    doi = resolve(needle, cfg, store, log)
    if not doi:
        return None
    _pin(store, doi, "manual", pillar)
    p = store.get(doi)
    stage = "normal" if p.get("user_mark") == "archived" else p.get("user_mark") or "normal"
    cited = bool(p.get("cited")) or cite
    curation.set_state(store, doi, curation.cite_on(stage) if cite else stage, cited)  # --cite = ✅ Selected + ⭐
    log(f"Pinned {doi} ({p['venue']} {p['published']}): {p['title']}"
        + (f" → Pillar {pillar}" if pillar else "") + (" · ✅ selected + ⭐ cite" if cite else ""))
    return doi
