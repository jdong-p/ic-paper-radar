"""On-demand vertical topic deep-dive: briefing.py --topic "<query>" [--max-ieee N]

Stage A (0 IEEE calls): parse the query into concept groups (+ an optional power ceiling such as
  "sub-100nW"), search the local store and OpenAlex across the IC venues — classics by citation count
  and recent (>= recent_from_year) work — and score relevance locally.
Stage B (IEEE reserve): one boolean IEEE query (venue-filtered) + per-DOI lookups to confirm metadata and
  fill abstracts. Draws on `ieee_topic` in api_usage (topic.ieee_topic_reserve per day), separate from
  the daily collection's ieee_daily_budget, so it works even after the 07:00 run used its 50 calls.
Stage C (one claude -p): Executive summary & evolution, Classic-vs-SOTA master table, per-paper digests;
  the Mermaid lineage map is computed locally from OpenAlex references.
"""
import json
import math
import re
import urllib.parse
from datetime import date

from env_guard import ensure_minisforum_env

ensure_minisforum_env()
import curation
import fetcher
import relations

UNIT_NW = {"pW": 1e-3, "nW": 1.0, "µW": 1e3, "μW": 1e3, "uW": 1e3, "mW": 1e6}
POWER_RX = re.compile(r"(\d+(?:\.\d+)?)\s?-?\s?(pW|nW|µW|μW|uW|mW)\b")
TEMP_SENSOR_RX = re.compile(r"(?i)temperature[- ](sensor|to[- ]digital)|thermal sensor")

PROMPT = """You are a senior analog/mixed-signal IC designer writing a longitudinal literature deep-dive in
English for a PhD researcher. Topic: "{query}".
Below are the selected papers (JSON): "group" is "classic" (foundational, highly cited) or "recent" (SOTA),
with title, venue, year, authors, citations, verification hint, extracted power numbers and abstract.
Use ONLY these abstracts; never invent numbers ("not stated" when missing). Measured silicon matters
most; mark simulation-only results with ⚠️ and never present them as state of the art.

Write Markdown starting directly with "## 1. Executive Summary & Evolution of Techniques" and nothing before:

## 1. Executive Summary & Evolution of Techniques
3–6 short paragraphs: the main technique families and how they evolved from the classics to the recent
papers (cite as [C1], [R3] etc. using the "id" field), what limits the state of the art, open problems.
## 2. Master Comparison Table (Classic vs. SOTA)
One Markdown table, all papers, classics first then recent, columns exactly:
Year & Venue | Paper & Authors | Verification | Process & Area | Power | Key Leakage/Low-Power Technique | FoM / Key Metric | DOI
(Paper & Authors = "[id] short title — first author … last author"; Verification = "✅ Silicon" / "⚠️ Sim" / "❔").
## 3. Per-Paper Technical Digests
### Foundational Classics
For each classic: "#### [id] Title (Venue Year)" then 2–4 bullets: core idea, key numbers, why it still matters.
### Recent SOTA
Same format; add one bullet on what it improves over the classics.
For papers with "recalled": true, write ONLY the "#### [id] Title (Venue Year)" heading line and no bullets:
their cached digest is inserted automatically (do still use them in sections 1 and 2).

Papers (JSON):
{papers}
"""


def slugify(q):
    return re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")[:60]


def parse_query(q, cfg):
    """→ (concept groups [[terms]], power ceiling in nW or None)."""
    tc = cfg["topic"]
    limit = None
    m = re.search(r"sub-?\s?(\d+(?:\.\d+)?)\s?(pW|nW|µW|μW|uW)", q, re.I)
    if m:
        unit = next(u for u in UNIT_NW if u.lower() == m[2].lower())
        limit = float(m[1]) * UNIT_NW[unit]
        q = q.replace(m[0], " ")
    groups, seen = [], set()
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9-]+", q):
        base = tok.lower().removeprefix("low-").removeprefix("ultra-")
        if base in tc["generic_words"] or base in seen or len(base) < 3:
            continue
        seen.add(base)
        syn = tc["synonyms"].get(base) or tc["synonyms"].get(base.rstrip("s"))
        groups.append(syn or [base])
    if limit is not None:
        groups.append(["re:power::\\d\\s?-?\\s?(nW|pW)\\b", "nanowatt", "picowatt", "ultra-low-power", "ultra-low power"])
    return groups, limit


def _powers_nw(text):
    return [float(n) * UNIT_NW[u] for n, u in POWER_RX.findall(text or "")]


def relevance(p, groups, limit, cfg):
    text = f"{p['title']} {p.get('abstract') or ''} {' '.join(p.get('index_terms') or [])}"
    hit_groups = sum(1 for g in groups if any(fetcher._kw_hit(t, text) for t in g))
    need = max(1, len(groups) - 1)
    if hit_groups < need:
        return 0, hit_groups
    title_hits = sum(1 for g in groups if any(fetcher._kw_hit(t, p["title"]) for t in g))
    # every concept matters (−4 per miss); a concept in the title says what the paper is *about* (+2)
    r = 3 * hit_groups - 4 * (len(groups) - hit_groups) + 2 * title_hits
    pw = _powers_nw(text)
    if limit is not None:  # the power ceiling is the point of e.g. "sub-100nW" …
        if pw and min(pw) <= limit:
            r += 4
        elif TEMP_SENSOR_RX.search(p["title"]):
            # … but a classic temperature sensor a bit above it (or with no power in the abstract) is still a
            # reference design: −1 up to 10× the ceiling or unstated, −2 beyond (v2.9; was −3 for every paper)
            r -= 1 if not pw or min(pw) <= 10 * limit else 2
        else:
            r -= 3
    v = fetcher.verification(p, cfg) if p.get("abstract") else "unclear"
    r += {"silicon_verified": 1, "simulation_only": -4}.get(v, 0)
    r += min(2, max(0, fetcher.score(p, cfg)[0]) // 6)
    return max(r, 0), hit_groups


def _venue_filter(cfg):
    issns = [i for v in cfg["venues"] for i in v["issn"]]
    return "primary_location.source.issn:" + "|".join(issns)


def _venue_of(name, cfg):
    for v in cfg["venues"]:
        rx = v.get("container_regex") or re.escape(v["name"].replace("IEEE ", ""))
        if re.search(rx, name or "", re.I):
            return v
    return None


def openalex_search(groups, cfg, log):
    """Classics (by citations, before recent_from_year), recent work, and the configured anchor papers
    (they compete on relevance like everything else), in the IC venues."""
    tc = cfg["topic"]
    heads = [next((t for t in g if not t.startswith("re:")), "nanowatt") for g in groups]
    variants = {" ".join(heads)} | {" ".join(heads[:i] + heads[i + 1:]) for i in range(len(heads)) if len(heads) > 2}
    y0 = tc["recent_from_year"]
    queries = [({"filter": f"{_venue_filter(cfg)},{flt}", "search": s, **({"sort": sort} if sort else {})})
               for s in variants for flt, sort in ((f"publication_year:<{y0}", "cited_by_count:desc"),
                                                   (f"publication_year:>{y0 - 1}", None))]
    if cfg.get("anchors"):
        queries.append({"filter": "doi:" + "|".join(a.lower() for a in cfg["anchors"])})
    out = {}
    for base in queries:
        params = {**base, "per-page": tc["openalex_per_query"], "mailto": cfg["contact_email"],
                  "select": "id,doi,display_name,publication_year,publication_date,authorships,primary_location,"
                            "abstract_inverted_index,referenced_works,cited_by_count"}
        try:
            res = json.loads(fetcher._get("https://api.openalex.org/works?" + urllib.parse.urlencode(params), cfg))["results"]
        except Exception as e:
            log(f"  [topic/openalex] '{base.get('search', 'anchors')}': {e}")
            continue
        for w in res:
            doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
            src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
            v = _venue_of(src, cfg)
            if not doi or not v:
                continue
            out.setdefault(doi, {"doi": doi, "title": fetcher._clean(w.get("display_name")), "venue": v["short"],
                                 "venue_name": v["name"], "published": w.get("publication_date") or str(w.get("publication_year")),
                                 "authors": [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []],
                                 "abstract": fetcher._oa_abstract(w.get("abstract_inverted_index")),
                                 "oa_id": w["id"].rsplit("/", 1)[-1], "cited_by": w.get("cited_by_count") or 0,
                                 "refs": ["oa:" + x.rsplit("/", 1)[-1] for x in w.get("referenced_works") or []],
                                 "source": "openalex"})
    log(f"  OpenAlex: {len(out)} papers from {len(queries)} queries (incl. anchors)")
    return out


def ieee_search(groups, cfg, store, budget, log):
    """One boolean query over all of IEEE, filtered to our venues by publication title."""
    def term(t):
        return '"nW" OR "pW" OR "nanowatt"' if t.startswith("re:") else f'"{t}"'
    q = " AND ".join("(" + " OR ".join(term(t) for t in g[:4]) + ")" for g in groups)
    r = fetcher._ieee({"querytext": q, "max_records": 200}, cfg, store, log, api="ieee_topic", budget=budget)
    out = {}
    for a in (r or {}).get("articles") or []:
        v = _venue_of(a.get("publication_title", ""), cfg)
        if a.get("doi") and v:
            p = fetcher._from_ieee(a, v)
            p["cited_by"] = a.get("citing_paper_count") or 0
            out[p["doi"]] = p
    log(f"  IEEE boolean query: {len((r or {}).get('articles') or [])} hits, {len(out)} in our venues")
    return out


def select(papers, cfg):
    tc = cfg["topic"]
    y0 = tc["recent_from_year"]
    year = lambda p: (relations._ym(p["published"]) or 0) // 12
    classic = sorted((p for p in papers if p["rel"] > 0 and 0 < year(p) < y0),
                     key=lambda p: -(p["rel"] + math.log10(1 + (p.get("cited_by") or 0))))  # relevance first, citations break ties
    recent = sorted((p for p in papers if p["rel"] > 0 and year(p) >= y0), key=lambda p: -p["rel"])
    return classic[:tc["n_classic"]], recent[:tc["n_recent"]]


def mermaid(classic, recent):
    nodes = [(f"C{i}", p) for i, p in enumerate(classic, 1)] + [(f"R{i}", p) for i, p in enumerate(recent, 1)]
    keys = {nid: relations._keys(p) for nid, p in nodes}
    edges = [(a, b) for a, pa in nodes for b, _ in nodes if a != b and keys[b] & set(pa.get("refs") or [])]
    if not edges:
        return ""
    short = lambda t: re.sub(r'["\[\]()]', "", t)[:42]
    used = {n for e in edges for n in e}
    L = ["```mermaid", "graph LR"]
    L += [f'  {nid}["{nid} {p["venue"]} {(relations._ym(p["published"]) or 0) // 12}: {short(p["title"])}"]'
          for nid, p in nodes if nid in used]
    L += [f"  {a} -->|cites| {b}" for a, b in edges]
    return "\n".join(L + ["```"])


def _decorate(body, by_id, recalled):
    """After each '#### [id] …' digest heading: ♻️ tag + cached digest for recalled papers; then, before the
    next heading, the paper's ⭐/🗄️ curation line."""
    out, cur = [], None

    def close():
        if cur:
            out.append(curation.line(by_id[cur]))
            out.append("")
    for ln in body.splitlines():
        m = re.match(r"^#{3,4} \[([CR]\d+)\]", ln)
        if m or re.match(r"^#{1,3} ", ln):
            close()
            cur = None
        if m and m[1] in by_id:
            p = by_id[m[1]]
            cur = m[1]
            if p["doi"] in recalled:
                out += [ln + " ♻️ [Recalled from Archive]"] + ([p["digest"]] if p.get("digest") else [])
                continue
        out.append(ln)
    close()
    return "\n".join(out)


def recall(query, cfg, store, log=print, top=25):
    """Local-only search over the whole store (archived marks and the backfilled corpus included):
    0 API calls, 0 tokens. Writes Topic_Dives/<date>_recall_<slug>.md with curation boxes."""
    groups, limit = parse_query(query, cfg)
    hits = []
    for p in store.where("1=1"):
        r = relevance(p, groups, limit, cfg)[0]
        if r > 0:
            hits.append((r, p))
    hits.sort(key=lambda x: (-x[0], str(x[1].get("published") or "")))
    L = [f"# Recall: {query}", "", f"*{date.today():%d %b %Y} · local store only ({len(hits)} matches, top {top} shown) · "
         "0 API calls, 0 tokens*", ""]
    for r, p in hits[:top]:
        tag = " ♻️ [Recalled from Archive]" if (p.get("user_mark") == "archived") else (" 📚 corpus" if p["status"] == "archive" else "")
        L += [f"- **{r}** · {p['venue']} {str(p.get('published') or '')[:10]} · [{p['title']}](https://doi.org/{p['doi']}){tag}",
              f"  {curation.line(p)}"]
        log(f"  {r:>3} {p['venue']:<8} {str(p.get('published') or '')[:10]:<10} {p['title'][:80]}{tag}")
    from pathlib import Path
    out_dir = Path(cfg["paths"]["topic_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{date.today().isoformat()}_recall_{slugify(query)}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    log(f"Wrote {out}")
    return out


def run(query, cfg, store, max_ieee, claude, log=print, use_claude=True):
    tc = cfg["topic"]
    today = date.today()
    groups, limit = parse_query(query, cfg)
    log(f"Topic: {query}\n  concept groups: {[g[:3] for g in groups]}  power ceiling: {limit} nW")

    # Stage A — local store + OpenAlex (0 IEEE calls)
    found = {p["doi"]: p for p in store.where("1=1")}
    found = {d: p for d, p in found.items() if relevance(p, groups, limit, cfg)[0] > 0}
    log(f"  local store: {len(found)} relevant")
    for d, p in openalex_search(groups, cfg, log).items():
        found.setdefault(d, p)

    # Stage B — IEEE reserve (skipped without IEEE_API_KEY: OpenAlex results only)
    fetcher.ieee_notice(log)
    budget = min(tc["ieee_topic_reserve"], store.calls_today("ieee_topic") + (max_ieee or tc["default_max_ieee"]))
    for d, p in ieee_search(groups, cfg, store, budget, log).items():
        q = found.setdefault(d, p)
        for k in ("abstract", "index_terms", "article_number"):
            if p.get(k) and not q.get(k):
                q[k] = p[k]
        q["cited_by"] = max(q.get("cited_by") or 0, p.get("cited_by") or 0)
    for p in found.values():
        p["rel"] = relevance(p, groups, limit, cfg)[0]
    pre_c, pre_r = select(list(found.values()), cfg)
    for p in pre_c + pre_r:  # fill missing abstracts of the shortlist, then re-rank
        if not p.get("abstract") and p["doi"].startswith("10.1109/"):
            r = fetcher._ieee({"doi": p["doi"]}, cfg, store, log, api="ieee_topic", budget=budget)
            arts = (r or {}).get("articles") or []
            if arts and arts[0].get("abstract"):
                p["abstract"] = fetcher._clean(arts[0]["abstract"])
                p["rel"] = relevance(p, groups, limit, cfg)[0]
    classic, recent = select(list(found.values()), cfg)
    log(f"  IEEE topic calls today: {store.calls_today('ieee_topic')}/{tc['ieee_topic_reserve']}; "
        f"selected {len(classic)} classics + {len(recent)} recent")

    # store everything relevant (new rows: status 'topic'), remember the selection
    for p in found.values():
        if p["rel"] > 0:
            row = {k: v for k, v in p.items() if k != "rel"}
            row["score"], row["hits"] = fetcher.score(p, cfg)
            store.upsert({**row, "first_seen": today.isoformat()}, "topic")
    slug = slugify(query)
    sel = [("classic", f"C{i}", p) for i, p in enumerate(classic, 1)] + [("recent", f"R{i}", p) for i, p in enumerate(recent, 1)]
    for _, _, p in sel:  # curation state + cached digest live in the store
        row = store.get(p["doi"]) or {}
        p["user_mark"], p["digest"] = row.get("user_mark") or "normal", row.get("digest") or p.get("digest")
    recalled = {p["doi"] for _, _, p in sel if p["user_mark"] == "archived"}
    if recalled:
        log(f"  ♻️ recalled from archive: {len(recalled)}")
    topics = store.meta("topics") or {}
    topics[slug] = {"query": query, "date": today.isoformat(), "dois": [p["doi"] for _, _, p in sel],
                    "n_classic": len(classic)}  # dois = classics, then recent (dashboard 🏛️/🚀 badges)
    store.meta("topics", topics)

    # Stage C — one claude call
    payload = [{"id": pid, "group": g, "title": p["title"], "venue": p["venue"],
                "year": (relations._ym(p["published"]) or 0) // 12, "authors": p.get("authors", [])[:8],
                "citations": p.get("cited_by") or 0, "doi": p["doi"],
                "verification_hint": fetcher.verification(p, cfg) if p.get("abstract") else "unclear",
                "power_numbers": sorted({f"{x:g} nW" for x in _powers_nw(p.get('abstract') or '')})[:6],
                **({"recalled": True, "cached_digest": p["digest"]} if p["doi"] in recalled and p.get("digest") else
                   {"abstract": p.get("abstract") or "(no abstract available — title only)"})} for g, pid, p in sel]
    body = "_(--no-claude: no synthesis)_"
    if use_claude and sel:
        log(f"Calling claude -p for the topic synthesis ({len(sel)} papers) ...")
        body = claude(PROMPT.format(query=query, papers=json.dumps(payload, ensure_ascii=False, indent=1)), cfg)
        body = body[body.find("## 1."):] if "## 1." in body else body
        # cache each per-paper digest (where none exists) so a later recall can reuse it at 0 tokens
        by_id = {pid: p for _, pid, p in sel}
        for pid, text in re.findall(r"^#{3,4} \[([CR]\d+)\][^\n]*\n(.*?)(?=^#{1,4} |\Z)", body, flags=re.M | re.S):
            p = by_id.get(pid)
            row = store.get(p["doi"]) if p else None
            if row and not row.get("digest") and text.strip():
                store.update(p["doi"], {"digest": text.strip(), "digest_ver": "topic-v1"})
    body = _decorate(body, {pid: p for _, pid, p in sel}, recalled)
    graph = mermaid(classic, recent)
    L = [f"# Topic Deep-Dive: {query}", "",
         f"*{today:%d %b %Y} · {len(classic)} foundational classics (before {tc['recent_from_year']}, ranked by relevance × "
         f"citations) + {len(recent)} recent papers · sources: local store, OpenAlex, IEEE Xplore API "
         f"({store.calls_today('ieee_topic')} topic calls today)*", "",
         f"**Query parsed as:** {' AND '.join('(' + ' | '.join(t.split('::')[0][3:] if t.startswith('re:') else t for t in g[:4]) + ')' for g in groups)}"
         + (f" · power ≤ {limit:g} nW boosts relevance" if limit else ""), "", body, "",
         "## 4. Lineage & Citation Map", ""]
    L += ([graph, "", "Arrows: the left paper's reference list cites the right one (OpenAlex)."] if graph else
          ["_No citation links among the selected papers in OpenAlex (reference lists missing or no direct citations)._"])
    L += ["", "## Paper list", ""]
    for _, pid, p in sel:
        L += [f"- **[{pid}]**{' ♻️ [Recalled from Archive]' if p['doi'] in recalled else ''} {p['title']} — "
              f"*{p['venue_name']}*, {p['published']} · cited {p.get('cited_by') or 0}× · "
              f"[{p['doi']}](https://doi.org/{p['doi']})",
              f"  {curation.line(p)}"]
    from pathlib import Path
    out_dir = Path(cfg["paths"]["topic_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{today.isoformat()}_{slug}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    log(f"Wrote {out}")
    return out
