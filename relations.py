"""Citation relations for a week's papers (0 tokens: Crossref + OpenAlex data already in the store).

- cites:      paper A's reference list contains paper B (same week)
- coupling:   A and B share >= SHARED_MIN references (likely competing approaches)
- corpus:     A cites a paper already in the local corpus (backfilled or earlier weeks)
- key prior:  A's most-cited references (OpenAlex), cached per paper in `keyrefs`
"""
import json
import re
import urllib.parse
from datetime import date
from difflib import SequenceMatcher

from env_guard import ensure_minisforum_env

ensure_minisforum_env()
import fetcher

SHARED_MIN = 3


def _keys(p):
    return {f"doi:{p['doi']}"} | ({f"oa:{p['oa_id']}"} if p.get("oa_id") else set())


def fill_keyrefs(papers, cfg, store, log=print):
    """Most-cited references per paper via OpenAlex; also adds their DOIs to `refs` for corpus matching."""
    for p in papers:
        if p.get("keyrefs") is not None:
            continue
        ids = [r[3:] for r in p.get("refs") or [] if r.startswith("oa:")]
        if not ids:
            continue  # references not indexed yet (typical for Early Access); retried next run
        try:
            works = fetcher.openalex_works(ids, cfg)
        except Exception as e:
            log(f"  [keyrefs] {p['doi']}: {e}")
            continue
        works.sort(key=lambda w: -(w.get("cited_by_count") or 0))
        top = []
        for w in works[:3]:
            first = ((w.get("authorships") or [{}])[0].get("author") or {}).get("display_name", "")
            src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
            top.append({"title": w.get("display_name"), "year": w.get("publication_year"), "first_author": first,
                        "venue": src, "cited_by": w.get("cited_by_count"),
                        "doi": (w.get("doi") or "").replace("https://doi.org/", "")})
        refs = set(p.get("refs") or []) | {f"doi:{w['doi'].replace('https://doi.org/', '').lower()}" for w in works if w.get("doi")}
        store.update(p["doi"], {"keyrefs": top, "refs": sorted(refs)})
        p["keyrefs"], p["refs"] = top, sorted(refs)


def week_relations(papers, store):
    """Returns (edges, per-paper notes). Edges: (i, j, kind, label) with 1-based paper numbers."""
    edges, notes = [], {p["doi"]: [] for p in papers}
    num = {p["doi"]: i for i, p in enumerate(papers, 1)}
    for a in papers:
        ra = set(a.get("refs") or [])
        for b in papers:
            if a is b:
                continue
            if ra & _keys(b):
                edges.append((num[a["doi"]], num[b["doi"]], "cites", "cites"))
                notes[a["doi"]].append(f"cites #{num[b['doi']]}")
            if num[a["doi"]] < num[b["doi"]]:
                shared = len(ra & set(b.get("refs") or []))
                if shared >= SHARED_MIN:
                    edges.append((num[a["doi"]], num[b["doi"]], "shared", f"{shared} shared refs"))
                    notes[a["doi"]].append(f"shares {shared} references with #{num[b['doi']]}")
                    notes[b["doi"]].append(f"shares {shared} references with #{num[a['doi']]}")
    # corpus links: refs that point at papers already in the store
    for a in papers:
        dois = [r[4:] for r in a.get("refs") or [] if r.startswith("doi:") and r[4:] not in num]
        hits = []
        for i in range(0, len(dois), 400):
            chunk = dois[i:i + 400]
            hits += store.where(f"doi IN ({','.join('?' * len(chunk))})", chunk)
        for h in hits[:4]:
            notes[a["doi"]].append(f"builds on *{h['title']}* ({h['venue']}, {str(h['published'])[:4]}) — in your corpus")
    return edges, notes


# ---------- Conference ↔ journal lineage ----------

MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
METRIC = re.compile(r"(\d+(?:\.\d+)?)\s?-?\s?(nW|pW|µW|μW|uW|mW|nm|dB|ppm|°C|fJ|pJ|aF|fF|pF|bit|MHz|kHz|GHz|GS/s|MS/s|kS/s|"
                    r"mV|µV|μV|uV|nV|µA|μA|nA|pA|mm2|mm²|%)")
STOP = set("a an the of for with and in on to by via using based low high ultra circuit circuits cmos achieving "
           "featuring technique techniques".split())


def _ym(s):
    """Months since year 0 from '2026-10-21', 'Oct. 2026', '14-18 June 2026', '2026' (mid-year guess).
    The month is 0-based (Jan = 0), so `ym // 12` is the year and `ym % 12 + 1` the month: with a 1-based
    month every December paper came out as the following year (fixed 2026-10-27)."""
    s = str(s or "")
    y = re.search(r"(19|20)\d\d", s)
    if not y:
        return None
    m = re.search(r"(19|20)\d\d-(\d\d)", s)
    if m:
        return int(y[0]) * 12 + int(m[2]) - 1
    mn = next((v for k, v in MONTHS.items() if re.search(rf"\b{k}", s, re.I)), 6)
    return int(y[0]) * 12 + mn - 1


def _surnames(authors):
    return [fetcher._name_key(a)[1] for a in authors or [] if a]


def _metric_tokens(text):
    return {f"{float(n):g}{u.replace('μ', 'µ').replace('u', 'µ') if u in ('uW', 'uV') else u}"
            for n, u in METRIC.findall(text or "")}


def _words(t):
    return {w for w in fetcher._norm(t) if w not in STOP and len(w) > 2}


def lineage_signal(J, C, cfg):
    """'A' (cites it + shared authors), 'B' (author group + topic/metric fingerprint) or None, with a reason."""
    lc = cfg["lineage"]
    sj, sc = _surnames(J.get("authors")), _surnames(C.get("authors"))
    if not sj or not sc:
        return None, ""
    shared = set(sj) & set(sc)
    same_first, same_last = sj[0] == sc[0], sj[-1] == sc[-1]
    tj, tc = _ym(J.get("published")), _ym(C.get("published"))
    dt = tj - tc if tj and tc else None
    if dt is not None and not lc["min_months"] <= dt <= lc["max_months"]:
        return None, ""
    when = f"{dt} months earlier" if dt is not None else "date unknown"
    if _keys(C) & set(J.get("refs") or []) and (len(shared) >= 2 or same_first or same_last):
        return "A", f"journal cites it; {len(shared)} shared authors; {when}"
    if not (same_first or (len(shared) >= 2 and same_last)):
        return None, ""
    wj, wc = _words(J["title"]), _words(C["title"])
    jac = len(wj & wc) / max(1, len(wj | wc))
    sim = SequenceMatcher(None, " ".join(sorted(wj)), " ".join(sorted(wc))).ratio()
    mj = _metric_tokens(f"{J['title']} {J.get('abstract') or ''}")
    mc = _metric_tokens(f"{C['title']} {C.get('abstract') or ''}")
    common = mj & mc
    distinctive = {t for t in common if not t.endswith("nm")}
    if jac >= 0.35 or sim >= 0.6:
        return "B", f"same author group; similar title ({jac:.2f}); {when}"
    if len(common) >= 2 and distinctive:
        return "B", f"same author group; same numbers {', '.join(sorted(common)[:4])}; {when}"
    # renamed journal title (v2.9): same first author and a 2nd shared author (often the PI as last author),
    # plus shared circuit-topic words ("NPN", "temperature", "sensor" …)
    tech = (wj & wc) & set(lc.get("tech_words", []))
    if same_first and (same_last or len(shared) >= 2) and len(tech) >= lc.get("min_tech_shared", 2):
        return "B", f"same first + co-author; topic words {', '.join(sorted(tech)[:4])}; {when}"
    return None, ""


def _conf_of(name, cfg):
    return next((k for k, rx in cfg["lineage"]["conferences"].items() if re.search(rx, name or "", re.I)), None)


def _from_oa(w, cfg):
    src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
    return {"doi": (w.get("doi") or "").replace("https://doi.org/", "").lower(), "oa_id": w["id"].rsplit("/", 1)[-1],
            "title": w.get("display_name") or "", "venue": _conf_of(src, cfg),
            "published": w.get("publication_date") or str(w.get("publication_year") or ""),
            "authors": [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []],
            "abstract": fetcher._oa_abstract(w.get("abstract_inverted_index"))}


class SearchBudgetGone(Exception):
    """OpenAlex's daily budget for search requests (no API key) is used up; plain filters still work."""


OA_FIELDS = "id,doi,display_name,publication_year,publication_date,authorships,primary_location,abstract_inverted_index"


def _oa_query(params, cfg):
    params = {**params, "mailto": cfg["contact_email"], "select": OA_FIELDS}
    try:
        return json.loads(fetcher._get("https://api.openalex.org/works?" + urllib.parse.urlencode(params), cfg))["results"]
    except Exception as e:
        if fetcher._budget_gone(e):
            raise SearchBudgetGone(str(e)) from e
        raise


def _author_ids(J, cfg):
    """OpenAlex author ids of J's first and last author (one plain request by DOI)."""
    res = _oa_query({"filter": f"doi:{J['doi']}", "per-page": 1}, cfg)
    au = (res[0].get("authorships") or []) if res else []
    ids = [((a.get("author") or {}).get("id") or "").rsplit("/", 1)[-1] for a in (au[:1] + au[-1:])]
    return list(dict.fromkeys(i for i in ids if i))


def _oa_search(J, cfg, log, allow_search=True):
    """OpenAlex: conference papers that could be J's precursor, last N years.
    1) every work of J's first and last author (author-id filter: a plain request, not counted against the
       daily *search* budget, and it finds renamed titles); 2) if allowed, a title-word search by the first
       author's name, then by title words only. Raises SearchBudgetGone when 2) hits the daily budget."""
    y = (_ym(J.get("published")) or 0) // 12 or date.today().year
    years = f"publication_year:{y - cfg['lineage']['openalex_search_years']}-{y}"
    is_conf = lambda w: _conf_of(((w.get("primary_location") or {}).get("source") or {}).get("display_name", ""), cfg)
    out = []
    try:
        for aid in _author_ids(J, cfg):
            out += [w for w in _oa_query({"filter": f"{years},authorships.author.id:{aid}", "per-page": 200}, cfg) if is_conf(w)]
    except SearchBudgetGone:
        raise
    except Exception as e:
        log(f"  [lineage/author] {e}")
    if out or not allow_search:
        return [_from_oa(w, cfg) for w in out]
    words = " ".join(sorted(_words(J["title"]), key=len, reverse=True)[:5])
    author = f"raw_author_name.search:{fetcher._name_key((J.get('authors') or [''])[0])[1]}"
    for flt, n in ((f"{years},{author}", 25), (years, 25)):
        try:
            out += [w for w in _oa_query({"filter": flt, "search": words, "per-page": n}, cfg) if is_conf(w)]
        except SearchBudgetGone:
            raise
        except Exception as e:
            log(f"  [lineage/search] {e}")
            continue
        if out:
            break
    return [_from_oa(w, cfg) for w in out]


def find_precursor(J, cfg, store, log=print, allow_search=True, online=True):
    """Best conference precursor of journal paper J: store → J's references → OpenAlex (author ids, then
    search if allowed); `online=False` uses the store only. Raises SearchBudgetGone when OpenAlex's daily
    budget is used up."""
    confs = cfg["lineage"]["conferences"]
    pools = [[c for c in store.where(f"venue IN ({','.join('?' * len(confs))}) AND doi != ?", (*confs, J["doi"]))]]
    oa_refs = [r[3:] for r in J.get("refs") or [] if r.startswith("oa:")] if online else []
    if oa_refs:
        try:
            pools.append([c for c in (_from_oa(w, cfg) for w in fetcher.openalex_works(oa_refs, cfg)) if c["venue"]])
        except Exception as e:
            if fetcher._budget_gone(e):
                raise SearchBudgetGone(str(e)) from e
            log(f"  [lineage/refs] {e}")
    if online:
        pools.append(lambda: _oa_search(J, cfg, log, allow_search))
    for pool in pools:
        pool = pool() if callable(pool) else pool
        best = None
        for C in pool:
            sig, why = lineage_signal(J, C, cfg)
            if sig and (best is None or sig < best[0]):
                best = (sig, why, C)
        if best:
            sig, why, C = best
            return {"type": "journal_extension_of", "doi": C["doi"], "venue": C["venue"],
                    "year": (_ym(C["published"]) or 0) // 12 or None, "title": C["title"], "signal": f"{sig}: {why}",
                    "abstract": (C.get("abstract") or "")[:2000]}
    return None


def update_lineage(papers, cfg, store, today, log=print, recheck_days=0):
    """Look for precursors of journal papers (until one is found), and mark conference papers that already
    have a journal extension in the store. Re-digest on a new link. A paper is re-checked once its last check
    is more than `recheck_days` old (0 = once a day). When OpenAlex's search budget runs out, the remaining
    papers still use the store, their references and the author-id lookup; a paper that found nothing
    without the search isn't marked checked, so the next run searches it."""
    journals, confs = set(cfg["lineage"]["journals"]), set(cfg["lineage"]["conferences"])
    found, search_ok, online = 0, True, True
    for p in papers:
        last = p.get("lineage_checked")
        if p.get("lineage") or (last and (today - date.fromisoformat(last)).days <= recheck_days):
            continue
        link, searched = None, search_ok and online
        if p["venue"] in journals:
            # OpenAlex budget gone → no more searches; gone for plain requests too → store only (one log line
            # each, not one per paper)
            for _ in range(3):  # full → without search → store only (which can't fail)
                try:
                    link = find_precursor(p, cfg, store, log, allow_search=search_ok, online=online)
                    break
                except SearchBudgetGone:
                    searched = False
                    if search_ok:
                        search_ok = False
                        log("  [lineage] OpenAlex search budget used up: no more searches this run")
                    else:
                        online = False
                        log("  [lineage] OpenAlex budget used up for plain requests too: store only this run")
        elif p["venue"] in confs:
            for J in store.where(f"venue IN ({','.join('?' * len(journals))})", tuple(journals)):
                sig, why = lineage_signal(J, p, cfg)
                if sig:
                    link = {"type": "has_journal_extension", "doi": J["doi"], "venue": J["venue"],
                            "year": (_ym(J["published"]) or 0) // 12 or None, "title": J["title"], "signal": f"{sig}: {why}"}
                    break
        upd = {"lineage_checked": today.isoformat()} if link or searched or p["venue"] not in journals else {}
        if link:
            upd["lineage"] = [link]
            if p.get("digest"):
                upd["digest_ver"] = None  # re-digest with the lineage & delta bullet
            found += 1
            log(f"  lineage: {p['venue']} {p['doi']} ← {link['venue']} {link['year']} ({link['signal']})")
        store.update(p["doi"], upd)
        p.update(upd)
    return found


def catalog_lineage(cfg, store, today, log=print):
    """Lineage over every catalog paper (weekly candidates/reported incl. catch-up, 🏛️ anchors / 📌 pinned,
    ✅ selected, ⭐ cited), not only this week's: fills missing OpenAlex ids / reference lists first (plain
    requests), then update_lineage with lineage.recheck_days. Returns #new links."""
    papers = store.where("grp='ieee' AND (status IN ('candidate','reported','pinned') OR pin IS NOT NULL "
                         "OR user_mark='selected' OR cited=1)")
    missing = [p for p in papers if not p.get("oa_id") or not p.get("refs")]
    if missing:
        fetcher.openalex_enrich(missing, cfg, store, log)
        papers = [store.get(p["doi"]) for p in papers]
    return update_lineage(papers, cfg, store, today, log, recheck_days=cfg["lineage"].get("recheck_days", 30))


def mermaid(papers, edges):
    if not edges:
        return ""
    used = sorted({i for e in edges for i in e[:2]})
    short = lambda t: re.sub(r'["\[\]()]', "", t)[:48]
    lines = ["```mermaid", "graph LR"]
    lines += [f'  P{i}["#{i} {papers[i - 1]["venue"]}: {short(papers[i - 1]["title"])}"]' for i in used]
    for i, j, kind, label in edges:
        lines.append(f"  P{i} -->|cites| P{j}" if kind == "cites" else f"  P{i} -.-|{label}| P{j}")
    return "\n".join(lines + ["```"])
