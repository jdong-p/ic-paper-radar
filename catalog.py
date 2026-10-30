"""MASTER_TABLE.md + .bib files in IC_Paper_Radar\\ (0 tokens), rewritten on every run.

MASTER_TABLE.md: ⭐ Cite papers first, then ✅ Selected, then 📋 Candidates (🏛️ anchors, 📌 pinned, reported/current
candidates by pillar, the Beyond-IEEE board, topic deep-dive selections), then 🗄️ archived papers in a collapsed
<details> block.
cite.bib = every ⭐ (cited=1) paper (for Overleaf; its pre-v2.8 duplicate selected.bib is gone since v2.13);
selected_pool.bib = ✅ Selected or ⭐; all_reported.bib = Candidate + Selected + ⭐ (archived only when ⭐).
@article / @inproceedings, key = FirstAuthorYearVenue.
"""
import re
import unicodedata
from pathlib import Path

from env_guard import ensure_minisforum_env

ensure_minisforum_env()
import curation
import fetcher
import relations

PILLARS = {0: "Other IEEE"}  # filled from config.json "pillars" by configure() (fetcher.load_config calls it)
# Only digests written with the reader's own pillars carry a trustworthy "Pillar:" line. The pre-loaded
# digests (en-v2/en-v3) were written for someone else's pillars, so their Pillar line is ignored.
PILLAR_DIGEST_VERS = {"starter-v1"}
CONF_RX = re.compile(r"Conference|Symposium|ISSCC|CICC|ESSERC|ESSCIRC|VLSI", re.I)


def configure(cfg):
    PILLARS.clear()
    for i, name in enumerate(cfg.get("pillars") or [], 1):
        PILLARS[i] = f"Pillar {i} — {name}"
    PILLARS[0] = "Other IEEE"


def _kw_pillars(cfg):
    out, cur = {}, 0
    for k in cfg["positive_keywords"]:
        m = re.match(r"_pillar(\d+)", k)
        if m:
            cur = int(m[1])
        elif cur:
            out[k[3:].split("::")[0] if k.startswith("re:") else k] = cur
    return out


def pillar_of(p, kwmap):
    if p.get("pillar"):  # chosen by the user (--add --pillar)
        return p["pillar"]
    m = re.search(r"\*\*Pillar:\*\*\s*\(?(?:Pillar\s*)?(\d+)", p.get("digest") or "")
    if m and p.get("digest_ver") in PILLAR_DIGEST_VERS and int(m[1]) in PILLARS and int(m[1]):
        return int(m[1])
    votes = {}
    for h in p.get("hits") or []:
        if kwmap.get(h) in PILLARS:
            votes[kwmap[h]] = votes.get(kwmap[h], 0) + 1
    return max(votes, key=votes.get) if votes else 0


OPEN_SQL = ("status IN ('candidate','reported') AND grp='ieee' AND COALESCE(user_mark,'normal')='normal' "
            "AND COALESCE(cited,0)=0")  # 📋 unreviewed core papers (pinned anchors don't count)


def pillar_counts(store, cfg, week):
    """{pillar: [unreviewed 📋 candidates, papers pulled by catch-up this week (whatever their mark now)]}."""
    kwmap = _kw_pillars(cfg)
    out = {k: [0, 0] for k in PILLARS if k}
    for i, (sql, args) in enumerate(((OPEN_SQL, ()), ("catchup=? AND grp='ieee'", (week,)))):
        for p in store.where(sql, args):
            k = pillar_of(p, kwmap)
            if k in out:
                out[k][i] += 1
    return out


def pillar_replenish(store, cfg, week, per_pillar=None, log=print, fresh=True):
    """Hybrid catch-up, per pillar: pull the best backfilled `archive` papers published since
    `catch_up.since` (score ≥ min_score; ranked by score + flagship_bonus, then newest) into this week
    (status candidate, `catchup` = week), as many as max(min_candidates_per_pillar − unreviewed,
    per_pillar − pulled this week). So a pillar always gets its weekly top `per_pillar` (3), and is topped
    back up to the water mark (10) whenever curation drops it below. per_pillar = --seed-pillars N.
    `not_a_paper` (regex on title + abstract) skips tutorials, plenaries and forums. fresh=True re-scores
    the archive and saves changed scores; False ranks by the stored scores. 0 calls, 0 tokens.
    Returns {pillar: added}."""
    cu = cfg.get("catch_up") or {}
    quota = cu.get("per_pillar", 0) if per_pillar is None else per_pillar
    floor = cu.get("min_candidates_per_pillar", 10)  # also for configs written before the key existed
    need = {k: max(floor - n_open, quota - n_week, 0) for k, (n_open, n_week) in pillar_counts(store, cfg, week).items()}
    if not any(need.values()):
        return {}
    kwmap, flagship = _kw_pillars(cfg), set(cu.get("flagship_venues", []))
    cutoff = relations._ym(cu.get("since", "2025-01-01"))
    # ISSCC tutorials, plenaries and forums are in the IEEE index like papers (one author, "I will present …")
    not_paper = re.compile(cu["not_a_paper"]) if cu.get("not_a_paper") else None
    picks = {k: [] for k in need}
    for p in store.where("status='archive' AND grp='ieee' AND COALESCE(user_mark,'normal') != 'archived'"):
        ym = relations._ym(p["published"])
        if ym is None or ym < cutoff or (not_paper and not_paper.search(f"{p['title']}\n{p.get('abstract') or ''}")):
            continue
        if fresh:
            s, hits = fetcher.score(p, cfg)
            if s != p["score"] or hits != (p.get("hits") or []):  # keeps the stored-score ranking current
                store.update(p["doi"], {"score": s, "hits": hits})
        else:
            s, hits = p["score"] or 0, p.get("hits") or []
        k = pillar_of({**p, "hits": hits}, kwmap)
        if s >= cfg["min_score"] and need.get(k):
            picks[k].append((s + (cu.get("flagship_bonus", 0) if p["venue"] in flagship else 0), s, hits, p))
    added = {}
    for k, lst in picks.items():
        lst.sort(key=lambda t: (-t[0], -(relations._ym(t[3]["published"]) or 0)))  # ties: newest first
        for _, s, hits, p in lst[:need[k]]:
            store.update(p["doi"], {"score": s, "hits": hits, "status": "candidate", "week": week, "catchup": week,
                                    "related": fetcher.find_related(p, store)})
            added[k] = added.get(k, 0) + 1
            log(f"  Pillar {k} +1: {p['venue']} {p['published']} ({s}) {p['title'][:70]}")
    short = {k: need[k] - added.get(k, 0) for k in need if need[k] > added.get(k, 0)}
    if short:
        log("  Pillar archive used up: " + ", ".join(f"Pillar {k} short by {v}" for k, v in sorted(short.items())))
    return added


def key_numbers(p):
    m = re.search(r"\*\*Architecture & key metrics:\*\*\s*(.+)", p.get("digest") or "")
    if m:
        txt = re.sub(r"[`*]", "", m[1])
        txt = re.sub(r"\b(not stated|Power: not stated|FoM: not stated)\b\s*·?\s*", "", txt)
        return txt[:140].rstrip(" ·;,") + ("…" if len(txt) > 140 else "")
    toks = sorted(relations._metric_tokens(f"{p['title']} {p.get('abstract') or ''}"))
    return ", ".join(toks[:6])


SI_BADGE = {"silicon_verified": "✅", "simulation_only": "⚠️ sim"}


def silicon(p, cfg, auto=False):
    """✅ / ⚠️ sim / ❔: the user's call (`user_silicon`, set after reading the PDF) unless auto=True, else the
    digest's Verification line, else the abstract's keyword cues."""
    if p.get("user_silicon") and not auto:
        return SI_BADGE[p["user_silicon"]]
    d = p.get("digest") or ""
    if "Silicon-Verified" in d:
        return "✅"
    if "Simulation-Only" in d:
        return "⚠️ sim"
    v = fetcher.verification(p, cfg) if p.get("abstract") else "unclear"
    return SI_BADGE.get(v, "❔")


def _year(p):
    return (relations._ym(p.get("published")) or 0) // 12 or ""


def _first_last(p):
    a = p.get("authors") or []
    if not a:
        return "n/a"
    return a[0] if len(a) == 1 else f"{a[0]} … {a[-1]}"


def _cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def gather(store, cfg):
    """[(group title, [papers])] in display order, regardless of user_mark (callers split by mark)."""
    kwmap = _kw_pillars(cfg)
    main = store.where("(status IN ('reported','candidate') OR pin IS NOT NULL) AND grp='ieee'")
    groups = {}
    for p in main:
        groups.setdefault(pillar_of(p, kwmap), []).append(p)
    out = [(PILLARS[k], groups[k]) for k in sorted(k for k in PILLARS if k) + [0] if groups.get(k)]
    # the board (≤ board_size undocumented) plus every Beyond paper already selected / cited / archived;
    # 'pool' papers wait for a slot (fetcher.beyond_replenish)
    beyond = store.where("status IN ('reported','candidate') AND grp='beyond'")
    if beyond:
        out.append(("🌍 Beyond IEEE (Nature / Science)", beyond))
    for slug, t in sorted((store.meta("topics") or {}).items(), key=lambda kv: kv[1]["date"], reverse=True):
        papers = [store.get(d) for d in t["dois"]]
        out.append((f"🔎 Topic: {t['query']} ({t['date']})", [p for p in papers if p]))
    return out


def _mark(p):
    """The curation stage (normal | selected | archived); ⭐ is the separate `cited` flag."""
    return p.get("user_mark") or "normal"


def _by_date(papers):
    return sorted(papers, key=lambda p: str(p.get("published") or ""), reverse=True)


PIN_TAG = {"anchor": "🏛️ Classic / Anchor", "manual": "📌 Pinned"}


HEAD = ["| Date | Venue | Title | First … Last Author | Silicon | Status | Key Numbers | Curation |",
        "|---|---|---|---|---|---|---|---|"]


def _row(p, cfg):
    note = f"🏷️ **{p['user_note']}** · " if p.get("user_note") else ""  # the user's 🏷️ Tech note (v2.15)
    return (f"| {_cell(str(p.get('published') or '')[:10])} | {p['venue']} | "
            f"[{_cell(fetcher.tidy_tex(p['title']))}](https://doi.org/{p['doi']}) | {_cell(_first_last(p))} | {silicon(p, cfg)} | "
            f"{PIN_TAG.get(p.get('pin'), p['status'])}{' · W' + p['week'][-2:] if p.get('week') else ''}"
            f"{' · 📈 Ext.' if p.get('lineage') else ''} | {_cell(note + key_numbers(p))} | "
            f"{curation.boxes(p['doi'], curation.mark_of(p), table=True)} |")


def write_master_table(store, cfg, path):
    groups = gather(store, cfg)
    cite = {p["doi"]: p for p in store.where("cited=1")}
    selected = {p["doi"]: p for p in store.where("user_mark='selected'")}
    archived = {p["doi"]: p for p in store.where("user_mark='archived'")}
    L = ["# IC Paper Radar — Master Table", "",
         "_Rewritten on every run. Workflow: 📋 Candidate → tick **✅ Select** to shortlist, **🗄️ Archive** to "
         "reject (it stays in the database and can be recalled by `--topic` / `--recall`); untick to send a paper "
         "back to Candidate. **⭐ Cite** is separate: a paper can be Selected *and* Cited ([cite.bib](cite.bib)); "
         "ticking ⭐ on a Candidate also selects it. Edits are picked up on the next run or with "
         "`briefing.py --sync`. [selected_pool.bib](selected_pool.bib) = ✅ or ⭐; "
         "[all_reported.bib](all_reported.bib) = every non-archived paper below._", "",
         f"## ⭐ Cite ({len(cite)})", ""]
    L += (HEAD + [_row(p, cfg) for p in _by_date(cite.values())] if cite else ["_Nothing to cite yet._"]) + [""]
    L += [f"## ✅ Selected ({len(selected)})", ""]
    L += (HEAD + [_row(p, cfg) for p in _by_date(selected.values())] if selected else ["_Nothing selected yet._"]) + [""]
    L += ["## 📋 Candidates", ""]
    for title, papers in groups:
        active = [p for p in papers if _mark(p) == "normal"]
        if active:  # 🏛️ anchors and 📌 pinned papers first
            rows = sorted(_by_date(active), key=lambda p: (p.get("pin") != "anchor", p.get("pin") != "manual"))
            L += [f"### {title} ({len(active)})", ""] + HEAD + [_row(p, cfg) for p in rows] + [""]
    L += [f"## 🗄️ Archived / Redundant Papers ({len(archived)})", "",
          "<details><summary>Show archived papers (untick 🗄️ Archive to send one back to Candidate)</summary>", ""]
    L += ["| Date | Venue | Title | Curation |", "|---|---|---|---|"] + [
        f"| {_cell(str(p.get('published') or '')[:10])} | {p['venue']} | [{_cell(fetcher.tidy_tex(p['title']))}](https://doi.org/{p['doi']}) | "
        f"{curation.boxes(p['doi'], curation.mark_of(p), table=True)} |" for p in _by_date(archived.values())]
    L += ["", "</details>", ""]
    Path(path).write_text("\n".join(L), encoding="utf-8")


# ---------- BibTeX ----------

def _ascii(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def _tex(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_")):
        s = s.replace(a, b)
    return s


def _bib_author(name):
    parts = (name or "").split()
    return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) > 1 else name


def bib_entry(p, key):
    conf = bool(CONF_RX.search(p.get("venue_name") or "")) or p["venue"] in ("ISSCC", "CICC", "VLSI", "ESSERC")
    fields = [("title", "{" + _tex(fetcher.tidy_tex(p["title"])) + "}"),  # double braces keep capitals (CMOS, ADC)
              ("author", " and ".join(_tex(_bib_author(a)) for a in p.get("authors") or [] if a)),
              ("booktitle" if conf else "journal", _tex(p.get("venue_name") or p["venue"])),
              ("year", str(_year(p))), ("doi", p["doi"]), ("url", f"https://doi.org/{p['doi']}")]
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields if v)
    return f"@{'inproceedings' if conf else 'article'}{{{key},\n{body}\n}}"


def bib_key(p, keys):
    """<FirstAuthorSurname><Year><Venue>, a/b/…/z/aa/ab/… suffix on clashes; adds the key to `keys`."""
    fam = re.sub(r"[^A-Za-z]", "", _ascii(((p.get("authors") or ["Anon"])[0] or "Anon").split()[-1])) or "Anon"
    base = f"{fam}{_year(p)}{re.sub(r'[^A-Za-z]', '', p['venue'])}"
    key, n = base, 0
    while key in keys:  # the whole pre-loaded corpus is keyed at once, so a common surname can clash > 26 times
        n += 1
        m, suffix = n, ""
        while m:
            m, r = divmod(m - 1, 26)
            suffix = "abcdefghijklmnopqrstuvwxyz"[r] + suffix
        key = base + suffix
    keys.add(key)
    return key


def write_bib(papers, path):
    seen, keys, out = set(), set(), []
    for p in sorted(papers, key=lambda p: p["doi"]):
        if p["doi"] in seen:
            continue
        seen.add(p["doi"])
        out.append(bib_entry(p, bib_key(p, keys)))
    Path(path).write_text("% IC Paper Radar — generated automatically, do not edit by hand\n\n" + "\n\n".join(out) + "\n",
                          encoding="utf-8")
    return len(out)


def write_all(store, cfg, log=print):
    root = Path(cfg["paths"]["onedrive_root"])
    write_master_table(store, cfg, root / "MASTER_TABLE.md")
    cite = store.where("cited=1")
    selected = store.where("user_mark='selected'")
    active = {p["doi"]: p for _, ps in gather(store, cfg) for p in ps if _mark(p) == "normal"}
    n_cite = write_bib(cite, root / "cite.bib")  # every ⭐, whatever its stage
    n_pool = write_bib(cite + selected, root / "selected_pool.bib")  # write_bib drops duplicate DOIs
    n_all = write_bib(cite + selected + list(active.values()), root / "all_reported.bib")
    for old in ("papers.bib", "selected.bib"):  # v2.3 / pre-v2.8 names, replaced by the files above (v2.13)
        (root / old).unlink(missing_ok=True)
    log(f"Catalog: MASTER_TABLE.md + cite.bib ({n_cite}) + selected_pool.bib ({n_pool}) "
        f"+ all_reported.bib ({n_all})")
