"""IC Paper Radar — daily entry point; one progressive report per week, finalized on Friday.

  python briefing.py [--auto-degrade | --require-vpn] [--fetch-pdf] [--finalize] [--dry-run]
                     [--no-claude] [--no-backfill]
  python briefing.py --add "<DOI or title>" [--pillar N] [--cite]   pin a paper into the catalog (pins.py)
  python briefing.py --seed-pillars [N]   best N archive papers per pillar since catch_up.since + Beyond board, now
  python briefing.py --rescore            re-score every paper (after a keyword/pillar change)
  python briefing.py --lineage            conference ↔ journal lineage over every catalog paper, now
  python briefing.py --sync               apply marks, refill the Beyond board (digests only its new papers)
  python briefing.py --select / --unselect / --cite / --uncite / --archive / --unarchive <DOI or text>

Every day (scheduled 07:00): collect (0 tokens) → digest only the *new* candidates (cached per DOI,
never re-done) → rewrite this week's file Weekly_Briefings/<YYYY-Www>.md ("in progress").
Friday (or --finalize): key prior work + citation map + one synthesis call → "final"; the week's
papers become `reported` and never appear again.

  (default)       no VPN check: collection uses public APIs only, so no popup and no banner
  --require-vpn   check your campus VPN (config.json → vpn); down → popup + exit 2
  --fetch-pdf     check your campus VPN; down → popup + banner, today's top papers go to the PDF queue
  --auto-degrade  kept for old command lines; same as the default
  --dry-run       work on a copy of the store, write to IC_Paper_Radar\\_archive\\_dryrun\\
  --no-claude     0 tokens: no digests / synthesis
Reports are always in English (ground rule).
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from env_guard import ensure_minisforum_env

ensure_minisforum_env()

import catalog
import curation
import fetcher
import html_renderer
import pins
import relations
import topic
import vpn_checker
from store import Store

HERE = Path(__file__).resolve().parent
PROMPT_VER = "starter-v1"  # bump to re-digest everything with a new prompt
# en-v2 / en-v3 = the pre-loaded digests: kept, not redone (catalog.pillar_of ignores their Pillar line)
DIGEST_VERS_OK = {PROMPT_VER, "en-v2", "en-v3"}

# claude() replaces this with the pillars from config.json, e.g. "(1) SAR ADCs; (2) PLLs"
PILLARS = "@@PILLARS@@"


def pillars_text(cfg):
    return "; ".join(f"({i}) {name}" for i, name in enumerate(cfg.get("pillars") or [], 1)) or "(none configured)"

DIGEST_PROMPT = """You are a senior analog/mixed-signal IC designer writing a reading digest for a PhD
researcher whose research pillars are """ + PILLARS + """. Write in English.
For each paper below use ONLY its title and abstract. Never invent numbers: write "not stated" when a
metric is missing. Measured silicon results matter most to this reader; simulation-only work counts
only if its numbers or topology are exceptional.

Output exactly this for every paper, in the given order, and nothing else (no preamble):

=== <doi> ===
- **Verification:** `✅ Silicon-Verified (<process>, <area>)` if the abstract reports fabricated/measured
  silicon; `⚠️ Simulation-Only (<why it may still be worth reading, or "no exceptional metric">)` if only
  simulations are reported; `❔ Not stated` otherwise. The JSON field "verification_hint" is a keyword
  heuristic; trust the abstract over it.
- **Pillar:** which of the pillars it serves, starting with its number (e.g. "2 — …"), or "other", in a few words
- **Core innovation:** 1–2 sentences
- **Architecture & key metrics:** Process · Power · FoM · ENOB or SNR/SNDR · Area · other headline numbers
  (inaccuracy, resolution FoM, efficiency, etc.)
- **Suggested focus:** e.g. circuit implementation / measurement / calibration / system architecture, with a one-line reason
- **📈 Conference → Journal Lineage & Delta:** ONLY for papers that have a "conference_precursor" field:
  (1) which conference paper it extends ("<venue> <year>: <title>"); (2) what the journal version adds over
  that 4-page conference brief — deeper circuit implementation, calibration, analysis/derivations, extended
  measurements (more chips, corners, temperature range) — judged by comparing the two abstracts. Say
  plainly when the abstracts don't reveal the delta. Omit this bullet entirely for other papers.

Papers (JSON):
{papers}
"""

BEYOND_VER = "beyond-v1"
BEYOND_PROMPT = """You are a senior analog/mixed-signal IC designer scouting non-IEEE journals (Nature /
Science portfolio) for ideas, for a PhD researcher whose pillars are """ + PILLARS + """. Write in English.
Use ONLY each paper's title and abstract; never invent numbers ("not stated" when missing).

Output exactly this for every paper, in the given order, and nothing else (no preamble):

=== <doi> ===
- **What it is:** 1–2 sentences on the transducer / system / bioelectronic concept and the headline result
- **Hardware & numbers:** sensing principle · electronics used (custom IC? discrete? off-the-shelf?) ·
  power / energy · size · key performance numbers
- **💡 System Concept & IC Takeaway:** why the concept is interesting, and concretely how a CMOS
  ultra-low-power / sensor-interface designer could leverage it or build a better IC readout for it
  (e.g. required noise, bandwidth, power budget, interface type)

Papers (JSON):
{papers}
"""

SYNTH_PROMPT = """You are a senior analog/mixed-signal IC designer. Below are this week's selected papers
(title, venue, digest, citation relations, keyword hits). The reader's research pillars are
""" + PILLARS + """. Write the week's synthesis in English, max ~550 words, Markdown, starting directly
with "### By pillar" and nothing before it:

### By pillar
One sub-bullet list per pillar (in the order above, plus "Other" only if needed): the
technical threads, citing papers as #number. Write
"nothing this week" for an empty pillar.
### Head-to-head (silicon-verified state of the art)
A Markdown table of the papers that address comparable problems, with columns Paper · Pillar · Process ·
Power · Key metric (FoM / inaccuracy / efficiency) · Area · Verification. Use only numbers from the
digests. Where a paper has "verification_confirmed_by_reader", that value (from the PDF) replaces the
digest's Verification line. Silicon-verified papers first; mark simulation-only rows with ⚠️ and never present their
numbers as state of the art.
### Reading order
The 3 papers to read first (#number + title) and why.
### Signals
1–3 bullets: VIP-author or anchor-citing work (see "hits"), conference → journal extensions (see
"lineage"), and anything that changes the state of the art for the reader's pillars.
### Beyond IEEE
1–2 bullets on the "beyond_ieee" papers (Nature/Science), only as inspiration for IC work; omit the
heading if that list is empty.

Context (facts, don't contradict them): {context}

Papers (JSON):
{papers}
"""


def claude_available(cfg):
    return shutil.which(cfg["claude"]["command"]) is not None


def claude(prompt, cfg):
    cc = cfg["claude"]
    prompt = prompt.replace(PILLARS, pillars_text(cfg))
    cmd = [cc["command"], "-p", "--output-format", "text", "--tools", "", "--strict-mcp-config"]
    if cc.get("model"):
        cmd += ["--model", cc["model"]]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=cc["timeout_s"], cwd=HERE, shell=(sys.platform == "win32"))
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"claude -p failed (exit {r.returncode}): {(r.stderr or r.stdout)[-400:]}")
    return r.stdout.strip()


def _precursor(p):
    link = next((l for l in p.get("lineage") or [] if l["type"] == "journal_extension_of"), None)
    return {"venue": link["venue"], "year": link["year"], "title": link["title"],
            "abstract": link.get("abstract") or "(not available)"} if link else None


def _run_digests(todo, prompt, ver, payload_fn, store, cfg, log, what):
    if not todo:
        return 0
    log(f"Calling claude -p to digest {len(todo)} {what} ...")
    out = claude(prompt.format(papers=json.dumps([payload_fn(p) for p in todo], ensure_ascii=False, indent=1)), cfg)
    parts = re.split(r"^=== *(\S+?) *===\s*$", out, flags=re.M)
    got = {parts[i].lower(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    for p in todo:
        if got.get(p["doi"]):
            store.update(p["doi"], {"digest": got[p["doi"]], "digest_ver": ver})
    missing = [p["doi"] for p in todo if not got.get(p["doi"])]
    if missing:
        log(f"  digest missing for {missing} (retried next run)")
    return len(todo) - len(missing)


def _digest_payload(p):
    d = {"doi": p["doi"], "title": p["title"], "venue": p["venue_name"], "verification_hint": _verif(p) or "unclear",
         "abstract": p.get("abstract") or "(no abstract available — title only)"}
    if _precursor(p):
        d["conference_precursor"] = _precursor(p)
    return d


def digest_new(store, cfg, week, today, log):
    """Digest candidates of this week that have no current digest. Cached: never repeated
    (a newly found conference precursor resets the cache so the lineage & delta bullet is added)."""
    todo = [p for p in store.where("status='candidate' AND week=? AND grp='ieee'", (week,))
            if p.get("digest_ver") not in DIGEST_VERS_OK
            and (p.get("abstract") or (today - date.fromisoformat(p["first_seen"])).days >= 2)]  # wait 2 days for an abstract
    # pinned papers (anchors, --add) last: the catalog shows them, the weekly report doesn't
    todo += [p for p in store.where("status='pinned' AND grp='ieee'") if p.get("digest_ver") not in DIGEST_VERS_OK
             and (p.get("abstract") or (today - date.fromisoformat(p["first_seen"])).days >= 2)]
    todo = sorted(todo, key=lambda p: (p["status"] == "pinned", bool(p.get("catchup")), -p["score"]))[
        :cfg["digests_per_day_max"]]  # new first
    n = _run_digests(todo, DIGEST_PROMPT, PROMPT_VER, _digest_payload, store, cfg, log, "IEEE papers")
    n += digest_beyond(store, cfg, log)
    return n


def digest_beyond(store, cfg, log):
    """Every paper on the Beyond-IEEE board without a digest (≤ board_size, so one call)."""
    todo = [p for p in store.where("grp='beyond' AND status IN ('candidate','reported') AND "
                                   "COALESCE(user_mark,'normal')='normal' AND COALESCE(cited,0)=0")
            if p.get("digest_ver") != BEYOND_VER]
    return _run_digests(todo, BEYOND_PROMPT, BEYOND_VER,
                        lambda p: {"doi": p["doi"], "title": p["title"], "venue": p["venue_name"],
                                   "abstract": p.get("abstract") or "(no abstract available — title only)"},
                        store, cfg, log, "Beyond-IEEE papers")


def catch_up(store, cfg, week, today, per_pillar=None):
    """Backfilled (archive) IEEE papers published since `catch_up.since` were filed before the radar saw
    them as new, so no weekly report showed them. Re-score them and pull the best of each pillar into this
    week (status candidate, `catchup` = week), up to `per_pillar` per pillar per week, so one pillar can't
    crowd out the others. Flagship venues (JSSC, ISSCC, VLSI…) rank higher. `catch_up.not_a_paper` (regex
    on title + abstract) skips tutorials, plenaries and forums. Returns {pillar: added}."""
    cu = cfg.get("catch_up") or {}
    quota = cu.get("per_pillar", 0) if per_pillar is None else per_pillar
    kwmap, flagship = catalog._kw_pillars(cfg), set(cu.get("flagship_venues", []))
    have = {}
    for p in store.where("catchup=?", (week,)):
        have[catalog.pillar_of(p, kwmap)] = have.get(catalog.pillar_of(p, kwmap), 0) + 1
    cutoff = relations._ym(cu.get("since", "2025-01-01"))
    # ISSCC tutorials, plenaries and forums are in the IEEE index like papers (one author, "I will present …")
    not_paper = re.compile(cu["not_a_paper"]) if cu.get("not_a_paper") else None
    picks = {k: [] for k in catalog.PILLARS if k}
    for p in store.where("status='archive' AND grp='ieee' AND COALESCE(user_mark,'normal') != 'archived'"):
        ym = relations._ym(p["published"])
        if ym is None or ym < cutoff or (not_paper and not_paper.search(f"{p['title']}\n{p.get('abstract') or ''}")):
            continue
        s, hits = fetcher.score(p, cfg)
        k = catalog.pillar_of({**p, "hits": hits}, kwmap)
        if s >= cfg["min_score"] and k in picks:
            picks[k].append((s + (cu.get("flagship_bonus", 0) if p["venue"] in flagship else 0), s, hits, p))
    added = {}
    for k, lst in picks.items():
        lst.sort(key=lambda t: (-t[0], -(relations._ym(t[3]["published"]) or 0)))  # ties: newest first
        for _, s, hits, p in lst[:max(0, quota - have.get(k, 0))]:
            store.update(p["doi"], {"score": s, "hits": hits, "status": "candidate", "week": week, "catchup": week,
                                    "related": fetcher.find_related(p, store)})
            added[k] = added.get(k, 0) + 1
    return added


def synthesis(store, cfg, week, papers, beyond, notes, force, log):
    cached = store.meta(f"synthesis:{week}")
    key = [PROMPT_VER, BEYOND_VER, [p["doi"] for p in papers + beyond]]
    if cached and cached["key"] == key and not force:
        return cached["text"]
    payload = {"ieee": [{"no": i, "title": p["title"], "venue": p["venue"], "digest": p.get("digest") or "",
                         "hits": p.get("hits") or [], "relations": notes.get(p["doi"], []),
                         "lineage": [_lineage_line(l) for l in p.get("lineage") or []],
                         # the reader's own call from the PDF beats the digest's Verification line
                         **({"verification_confirmed_by_reader": p["user_silicon"]} if p.get("user_silicon") else {})}
                        for i, p in enumerate(papers, 1)],
               "beyond_ieee": [{"title": p["title"], "venue": p["venue_name"], "digest": p.get("digest") or ""} for p in beyond]}
    log("Calling claude -p for the weekly synthesis ...")
    with_refs = sum(1 for p in papers if p.get("refs"))
    context = (f"{len(cfg.get('anchors', []))} anchor papers and {len(cfg.get('vip_authors', []))} VIP-author name "
               f"forms are configured. 'cites an anchor' can only appear when a paper's reference list is indexed; "
               f"this week {with_refs} of {len(papers)} papers have an indexed reference list (Early Access papers "
               f"often have none yet), so a missing anchor hit is not evidence of no citation.")
    out = claude(SYNTH_PROMPT.format(papers=json.dumps(payload, ensure_ascii=False, indent=1), context=context), cfg)
    out = out[out.find("### "):] if "### " in out else out
    store.meta(f"synthesis:{week}", {"key": key, "text": out})
    return out


def fetch_pdfs(items, cfg, log=print):
    """Best effort via the DOI's IEEE arnumber. With the split tunnel this usually gets HTML; failures stay queued."""
    out_dir = Path(cfg["paths"]["pdf_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    for it in items:
        try:
            req = urllib.request.Request(f"https://doi.org/{it['doi']}", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                m = re.search(r"/document/(\d+)", r.geturl())
            if not m:
                raise RuntimeError("no IEEE arnumber")
            req = urllib.request.Request(f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={m[1]}",
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if not data.startswith(b"%PDF"):
                raise RuntimeError("no institutional access (got HTML, not a PDF)")
            (out_dir / f"{it['doi'].replace('/', '_')}.pdf").write_bytes(data)
            log(f"  PDF ok: {it['doi']}")
        except Exception as e:
            log(f"  PDF failed: {it['doi']}: {e}")
            failed.append({**it, "last_error": str(e)})
    return failed


def _verif(p):
    if p.get("user_silicon"):  # the reader's call after reading the PDF (v2.10)
        return p["user_silicon"]
    hits = p.get("hits") or []
    return next((h for h in ("silicon_verified", "simulation_only") if h in hits), "")


BADGE = {"silicon_verified": "✅", "simulation_only": "⚠️ sim-only", "": "❔"}


def _authors(p):
    a = p.get("authors") or []
    return ", ".join(a[:4]) + (" et al." if len(a) > 4 else "") or "n/a"


def _lineage_line(l):
    if l["type"] == "journal_extension_of":
        return f"📈 Extended from {l['venue']} {l['year'] or ''}: *{l['title']}* ({l['doi']}) — signal {l['signal']}"
    return f"📈 Has a journal extension in {l['venue']} {l['year'] or ''}: *{l['title']}* ({l['doi']}) — signal {l['signal']}"


def _paper_block(head, p, today, notes):
    L = [f"### {head}. {p['title']}" + (" 🆕" if p["first_seen"] == today.isoformat() else ""),
         f"*{p['venue_name']}* · {p['published']} · {_authors(p)} · DOI [{p['doi']}](https://doi.org/{p['doi']})"
         + ("" if p.get("abstract") else " · ⚠️ no abstract yet"), ""]
    L += [p.get("digest") or "_Digest pending (next run)._", curation.line(p), ""]
    lin = p.get("lineage") or []
    if lin:
        L += ["**" + " · ".join(_lineage_line(l) for l in lin) + "**", ""]
    rel = list(notes.get(p["doi"], []))
    rel += [f"possible other version: *{r['title']}* ({r['venue']}, {r['published']}, {r['doi']})"
            for r in p.get("related") or [] if r["doi"] not in {l["doi"] for l in lin}]
    if p.get("keyrefs"):
        rel.append("key prior work: " + "; ".join(
            f"{k['first_author']} — *{k['title']}* ({k['venue'] or 'n/a'}, {k['year']}, cited {k['cited_by']}×)" for k in p["keyrefs"]))
    if rel:
        L += ["**Relations:** " + " · ".join(rel), ""]
    return L


def render(week, friday, today, vpn, papers, also, catch, beyond, notes, edges, synth, final, store, cfg, run):
    L = [f"# IC Paper Radar — Week {week} (ends Fri {friday:%d %b %Y})", ""]
    L.append(f"> ✅ **Final** — {today:%a %d %b %Y}" if final else
             f"> 🟡 **In progress** — updated {datetime.now():%a %d %b %Y %H:%M}; final report on Friday {friday:%d %b}.")
    if vpn["connected"] is False:  # None = not checked (default daily run)
        L += ["", "> ⚠️ **[VPN Disconnected - Abstract-Only Mode]** Reconnect your campus VPN on this computer. "
              "Today's top papers were queued in `pending_pdf_queue.json`."]
    c = store.counts()
    L += ["", f"**Network:** {vpn['message']}  ",
          f"**This week:** {len(papers) + len(also)} matched papers + {len(catch)} catch-up · today +{run['new']} new records, "
          f"+{len(run['new_candidates'])} matches · IEEE API {run['ieee_calls']}/{cfg['ieee_daily_budget']} calls today  ",
          f"**Corpus:** {sum(c.values())} papers ({c.get('archive', 0)} backfilled, {c.get('reported', 0)} reported, "
          f"{c.get('pending', 0)} waiting for an abstract)", ""]
    if run["errors"]:
        L += ["**Fetch errors:** " + "; ".join(run["errors"]), ""]
    if synth:
        L += ["## Week synthesis", "", synth, ""]
    if not papers and not catch:
        return "\n".join(L + ["_No matching papers yet this week._", ""])

    def table(rows, numbered, added_col):
        out = [f"| {numbered} | Score | Silicon | Venue | Title | Cited by | {added_col} | Hits |",
               "|---|---|---|---|---|---|---|---|"]
        for i, p in enumerate(rows, 1):
            new = " 🆕" if p["first_seen"] == today.isoformat() else ""
            cites = max(p.get("cited_by") or 0, p.get("ieee_cites") or 0)
            hits = ", ".join(f"**{h}**" if h.startswith(("vip_author", "cites an anchor")) else h
                             for h in p["hits"] if h not in ("silicon_verified", "simulation_only"))
            when = p["first_seen"][5:] if added_col == "Added" else p["published"]
            out.append(f"| {numbered.replace('#', '') + str(i)} | {p['score']} | {BADGE[_verif(p)]} | {p['venue']} "
                       f"| [{p['title']}](https://doi.org/{p['doi']}){new} | {cites} | {when} | {hits} |")
        return out

    if papers:
        L += ["## Ranked papers", ""] + table(papers, "#", "Added")
        graph = relations.mermaid(papers, edges)
        if graph:
            L += ["", "## Citation map", "", "Solid arrow = cites; dotted line = shared references.", "", graph]
        L += ["", "## Papers", ""]
        for i, p in enumerate(papers, 1):
            L += _paper_block(i, p, today, notes)
    else:
        L += ["_No new matching papers yet this week._", ""]
    if also:
        L += ["## Also matched (not in the top list)", "", "| Score | Venue | Title |", "|---|---|---|"]
        L += [f"| {p['score']} | {p['venue']} | [{p['title']}](https://doi.org/{p['doi']}) |" for p in also]
    if catch:
        L += ["", "## ⏪ Catch-up: recent papers the radar filed before it saw them as new", "",
              f"_Published since {cfg['catch_up']['since']} but backfilled into the corpus, so no earlier report "
              f"showed them. The best {cfg['catch_up']['per_pillar']} of each pillar per week (flagship venues "
              f"rank higher); `--seed-pillars N` pulls more._", ""]
        L += table(catch, "C", "Published") + [""]
        for i, p in enumerate(catch, 1):
            L += _paper_block(f"C{i}", p, today, notes)
    L += render_beyond(beyond, today)
    return "\n".join(L + [""])


def render_beyond(beyond, today):
    if not beyond:
        return []
    L = ["", "## 🌍 Beyond IEEE: Cross-Disciplinary & Bioelectronics Highlights (Nature / Science)", "",
         "_Inspiration, not circuits papers: passed the dual-key gate (application theme + hardware/IC term)._", ""]
    for i, p in enumerate(beyond, 1):
        gate = ", ".join(h for h in p["hits"] if h.startswith(("theme:", "hw:")))
        L += [f"### 🌍 {i}. {p['title']}" + (" 🆕" if p["first_seen"] == today.isoformat() else ""),
              f"*{p['venue_name']}* · {p['published']} · {_authors(p)} · DOI [{p['doi']}](https://doi.org/{p['doi']})"
              + ("" if p.get("abstract") else " · ⚠️ no abstract (title-only gate)") + f" · gate: {gate}", "",
              p.get("digest") or "_Digest pending (next run)._", curation.line(p), ""]
    return L


def update_index(weekly_dir, topic_dir=None):
    rows = ["# IC Paper Radar — Index", "", "**[DASHBOARD.html](DASHBOARD.html)** — open in a browser to filter, search and click ⭐/🗄️ · "
            "[MASTER_TABLE.md](MASTER_TABLE.md) — ⭐ cite, ✅ selected, 📋 candidate and 🗄️ archived papers · "
            "[cite.bib](cite.bib) — ⭐ Cite only ·[selected_pool.bib](selected_pool.bib) — ✅ + ⭐ · "
            "[all_reported.bib](all_reported.bib) — everything not archived",
            "", "## Weekly reports", ""]
    for f in sorted(weekly_dir.glob("????-W??.md"), reverse=True):
        t = f.read_text(encoding="utf-8")
        n = len(re.findall(r"^### C?\d+\. ", t, flags=re.M))  # C1, C2… = catch-up papers
        state = "final" if "✅ **Final**" in t else "in progress"
        rows.append(f"- [{f.stem}]({weekly_dir.name}/{f.name}) — {n} papers, {state}")
    if topic_dir and topic_dir.exists():
        rows += ["", "## Topic deep-dives", ""]
        for f in sorted(topic_dir.glob("*.md"), reverse=True):
            first = f.read_text(encoding="utf-8").splitlines()[0].removeprefix("# Topic Deep-Dive: ")
            rows.append(f"- [{f.stem[:10]} — {first}]({topic_dir.name}/{f.name})")
    (weekly_dir.parent / "INDEX.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def backup_store(store, cfg, log=print):
    """Disaster recovery: lock-safe online copy of the store (sqlite3 backup API) to
    IC_Paper_Radar\\_system\\paper_store_backup.sqlite. Written to a .tmp file, checked, then swapped in, so
    OneDrive never syncs a half-written copy. A failure is logged and never fails the run."""
    dest = curation.system_dir(cfg) / "paper_store_backup.sqlite"
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        dst = sqlite3.connect(tmp)
        try:
            store.db.backup(dst)
            ok = dst.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            dst.close()
        if ok != "ok":
            raise RuntimeError(f"quick_check: {ok}")
        os.replace(tmp, dest)
        log(f"Store backup: {dest}")
    except Exception as e:
        tmp.unlink(missing_ok=True)
        log(f"Store backup failed (previous backup kept): {e}")


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--require-vpn", action="store_true")
    g.add_argument("--auto-degrade", action="store_true")
    ap.add_argument("--fetch-pdf", action="store_true")
    ap.add_argument("--finalize", action="store_true", help="finalize this week now (default: on Fridays)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-claude", action="store_true")
    ap.add_argument("--no-backfill", action="store_true")
    ap.add_argument("--topic", help='on-demand deep-dive, e.g. --topic "sub-100nW sensor design and low-leakage techniques"')
    ap.add_argument("--max-ieee", type=int, help="IEEE calls this --topic run may use (from topic.ieee_topic_reserve)")
    ap.add_argument("--recall", help="search the whole store (incl. archived + corpus) locally: 0 API calls, 0 tokens")
    ap.add_argument("--sync", action="store_true", help="apply ✅/⭐/🗄️ checkbox edits, refill the Beyond-IEEE board, "
                                                         "rewrite the catalog (a claude -p call only for new board papers)")
    ap.add_argument("--rescore", action="store_true", help="re-score every paper after a keyword/pillar change (0 calls)")
    ap.add_argument("--lineage", action="store_true", help="conference ↔ journal lineage over every catalog paper now "
                                                            "(OpenAlex, 0 IEEE calls, 0 tokens)")
    ap.add_argument("--add", metavar="DOI_OR_TITLE", help="pin a paper into the active catalog (fetched if missing), "
                                                          "bypassing min_score and date windows; with --pillar / --cite")
    ap.add_argument("--pillar", type=int, metavar="N", help="pillar number for --add (from config.json \"pillars\")")
    ap.add_argument("--seed-pillars", type=int, nargs="?", const=-1, metavar="N",
                    help="pull the best N archive papers per pillar (since catch_up.since) into this week now "
                         "(default catch_up.per_pillar), pin the anchors, and fill the Beyond-IEEE board")
    # --cite takes a DOI/text; with --add it may stand alone ("--add <doi> --cite")
    ap.add_argument("--cite", metavar="DOI_OR_TEXT", nargs="?", const=True,
                    help="mark papers matching a DOI or title substring (cite); bare with --add")
    for flag in ("select", "unselect", "archive", "unarchive", "uncite"):
        ap.add_argument(f"--{flag}", metavar="DOI_OR_TEXT", help=f"mark papers matching a DOI or title substring ({flag})")
    a = ap.parse_args()
    if a.cite is True and not a.add:
        ap.error("--cite needs a DOI or title substring (or use it with --add)")
    if a.pillar and not a.add:
        ap.error("--pillar only works with --add")
    add_cite = a.cite is True
    if add_cite:
        a.cite = None

    cfg = fetcher.load_config()
    if a.pillar and a.pillar not in catalog.PILLARS:
        ap.error(f"--pillar must be one of {sorted(k for k in catalog.PILLARS if k)} (config.json \"pillars\")")
    if not a.no_claude and not claude_available(cfg):
        print(f"[INFO] '{cfg['claude']['command']}' CLI not found on PATH: running in --no-claude mode (scoring, "
              "dashboard, master table, --topic and --seed-pillars still work; digests and the synthesis are skipped).")
        a.no_claude = True
    today = date.today()
    week, friday = fetcher.week_of(today)
    final = a.finalize or today.strftime("%A") == cfg["report_day"]

    store_path = HERE / cfg["paths"]["store_file"]
    out_dir = Path(cfg["paths"]["weekly_dir"])
    if a.dry_run:
        dry = HERE / "_dryrun.sqlite"
        if store_path.exists():
            shutil.copy(store_path, dry)
        archive = Path(cfg["paths"].get("archive_dir") or Path(cfg["paths"]["onedrive_root"]) / "_archive")
        store_path, out_dir = dry, archive / "_dryrun" / out_dir.name
    if fetcher.store_paper_count(store_path) == 0:  # checked before Store() creates an empty file
        print("\n" + fetcher.STORE_TIP + "\n")
    store = Store(store_path)
    topic_dir = Path(cfg["paths"]["topic_dir"])

    def refresh_catalog():
        catalog.write_all(store, cfg)
        update_index(Path(cfg["paths"]["weekly_dir"]), topic_dir)
        curation.sync_markdown_marks(store, cfg, read_edits=False)  # bring every report's boxes in line
        html_renderer.write_all(store, cfg)  # after the .md boxes are final

    if not a.dry_run:
        n = curation.sync_markdown_marks(store, cfg)
        print(f"Curation sync: {n} checkbox change(s) applied")
    marks = [(getattr(a, f), f) for f in curation.ACTIONS if getattr(a, f)]
    for needle, action in marks:
        curation.set_mark(store, needle, action)
    if not fetcher.pillars_ready(cfg) and not (a.topic or a.recall):
        # Starter Edition: nothing to score against yet (--topic / --recall don't need pillars);
        # still (re)write the welcome dashboard
        print("\n" + fetcher.SETUP_MSG + "\n")
        if not a.dry_run:
            refresh_catalog()
            print(f"Dashboard: {Path(cfg['paths']['onedrive_root']) / 'DASHBOARD.html'}")
        return 0
    if a.rescore:
        fetcher.rescore_all(cfg, store)
    if a.lineage:
        print(f"Lineage: {relations.catalog_lineage(cfg, store, today)} new conference ↔ journal links")
    if a.recall:
        topic.recall(a.recall, cfg, store)
    if a.topic:
        topic.run(a.topic, cfg, store, a.max_ieee, claude, print, use_claude=not a.no_claude)
    if a.add or a.seed_pillars is not None:
        print(f"Anchors: {pins.sync_anchors(store, cfg)} pinned as 🏛️ Classic / Anchor")
        added = a.add and pins.add(a.add, cfg, store, a.pillar, add_cite)
        if a.add and not added:
            return 1
        if a.seed_pillars is not None:
            n = catch_up(store, cfg, week, today, None if a.seed_pillars < 0 else a.seed_pillars)
            print("Seed: " + (", ".join(f"Pillar {k} +{v}" for k, v in sorted(n.items())) or "nothing new"))
            print(f"Beyond pool: {fetcher.pool_search(cfg, store, today)} gate-passing papers searched")
        if not a.no_claude:
            try:
                p = added and store.get(added)
                # this paper right away if it has an abstract (else the daily queue waits for one, ≤ 2 days)
                if p and p.get("digest_ver") not in DIGEST_VERS_OK and p.get("abstract"):
                    _run_digests([p], DIGEST_PROMPT, PROMPT_VER, _digest_payload, store, cfg, print, "pinned paper")
            except Exception as e:
                print(f"Digest failed (retried next run): {e}", file=sys.stderr)
    if a.sync or marks or a.rescore or a.lineage or a.recall or a.topic or a.add or a.seed_pillars is not None:
        if a.dry_run:
            return 0
        board = a.sync or marks or a.rescore or a.lineage or a.add or a.seed_pillars is not None  # not --recall/--topic
        if board:
            print(f"Beyond board: +{fetcher.beyond_replenish(cfg, store, week)} from the pool")
        if board and not a.no_claude:
            try:  # the board's new papers (and, with --seed-pillars, the seeded ones)
                digest_new(store, cfg, week, today, print) if a.seed_pillars is not None else digest_beyond(store, cfg, print)
            except Exception as e:
                print(f"Digest failed (retried next run): {e}", file=sys.stderr)
        refresh_catalog()
        return 0

    # The daily pipeline only uses public APIs (IEEE Metadata API, Crossref, OpenAlex), and IEEE
    # Xplore may bypass a split-tunnel VPN anyway, so the VPN matters only for --require-vpn / --fetch-pdf.
    if a.require_vpn or a.fetch_pdf:
        vpn = vpn_checker.check_vpn_status()
        print(vpn["message"])
        if not vpn["connected"]:
            if cfg["vpn"].get("notify", True) and not a.dry_run:
                vpn_checker.notify_disconnected()
            if a.require_vpn:
                print("--require-vpn set: stopping.", file=sys.stderr)
                return 2
    else:
        vpn = {"connected": None, "message": "public APIs only (VPN not checked; use --require-vpn / --fetch-pdf)"}

    print("Collecting (IEEE API / Crossref / OpenAlex, 0 tokens) ...")
    run = fetcher.collect(cfg, store, today, backfill=not a.no_backfill)
    print(f"{run['new']} new records, {len(run['new_candidates'])} new matches, IEEE calls today {run['ieee_calls']}")
    n = catch_up(store, cfg, week, today)
    print("Catch-up: " + (", ".join(f"Pillar {k} +{v}" for k, v in sorted(n.items())) or "nothing new"))
    print(f"Anchors: {pins.sync_anchors(store, cfg)} pinned as 🏛️ Classic / Anchor")
    print(f"Beyond board: +{fetcher.beyond_replenish(cfg, store, week)} from the pool")

    ieee_q =("status='candidate' AND week=? AND grp='ieee'", (week,))
    relations.fill_keyrefs(store.where(*ieee_q), cfg, store)  # references first: lineage signal A uses them
    n = relations.update_lineage(store.where(*ieee_q), cfg, store, today)
    n += relations.catalog_lineage(cfg, store, today)  # anchors, pinned, selected, cited, reported (every 30 days)
    print(f"Lineage: {n} new conference ↔ journal links")

    if not a.no_claude:
        try:
            digest_new(store, cfg, week, today, print)
        except Exception as e:
            print(f"Digest failed (retried next run): {e}", file=sys.stderr)

    allc = sorted(store.where(*ieee_q), key=lambda p: (-p["score"], p["first_seen"]))
    fresh = [p for p in allc if not p.get("catchup")]
    catch = [p for p in allc if p.get("catchup")]
    papers, also = fresh[:cfg["weekly_top"]], fresh[cfg["weekly_top"]:]
    all_beyond = sorted(store.where("status='candidate' AND week=? AND grp='beyond'", (week,)), key=lambda p: -p["score"])
    beyond = [p for p in all_beyond if (p.get("user_mark") or "normal") != "archived"]  # this week's board arrivals
    edges, notes = relations.week_relations(papers, store)
    notes.update(relations.week_relations(catch, store)[1])

    synth = ""
    if final and (papers or catch) and not a.no_claude:
        try:
            synth = synthesis(store, cfg, week, papers + catch, beyond, notes, a.finalize, print)
        except Exception as e:
            synth = f"> ❌ Synthesis failed: {e}"

    queue_path = HERE / cfg["paths"]["pdf_queue_file"]
    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
    todays = [p for p in papers if p["doi"] in run["new_candidates"]]
    if vpn["connected"] and a.fetch_pdf:
        queue = fetch_pdfs(queue + [{"doi": p["doi"], "title": p["title"]} for p in todays], cfg)
    elif vpn["connected"] is False:
        known = {q["doi"] for q in queue}
        queue += [{"doi": p["doi"], "title": p["title"], "queued": today.isoformat()} for p in todays if p["doi"] not in known]

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{week}.md"
    out.write_text(render(week, friday, today, vpn, papers, also, catch, beyond, notes, edges, synth, final, store, cfg, run),
                   encoding="utf-8")
    print(f"Wrote {out}")

    if final and not a.dry_run:
        for p in allc + all_beyond:
            store.update(p["doi"], {"status": "reported"})
    if not a.dry_run:
        refresh_catalog()
    else:
        update_index(out_dir)
    if not a.dry_run:
        queue_path.write_text(json.dumps(queue, indent=1, ensure_ascii=False), encoding="utf-8")
        backup_store(store, cfg, print)
    print(store.counts())
    return 0


if __name__ == "__main__":
    sys.exit(main())
