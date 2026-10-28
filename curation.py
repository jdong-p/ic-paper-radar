"""Paper curation: ✅ Select / ⭐ Cite / 🗄️ Archive checkboxes in the Markdown reports ↔ the store.

Two independent things (v2.9):
  stage  `user_mark`: normal = 📋 Candidate | selected = ✅ shortlisted | archived = 🗄️ rejected (one of them)
  cite   `cited` 0/1: ⭐ for the manuscript, independent of the stage (Selected + Cited, Archived + Cited …)
Ticking ⭐ on a 📋 Candidate also moves it to ✅ Selected (convenience). After that, ⭐ on/off never changes
the stage and Select/Archive never clear ⭐.
A third, also independent (v2.10): `user_silicon` = the user's Silicon-Verified call after reading the PDF
('silicon_verified' | 'simulation_only'; NULL = the automatic guess), overriding it everywhere.
Pages, the sync server and curation_marks.json carry all three as one "mark" string: the stage, "+cite" when
cited, "+si" / "+sim" for a silicon override ("selected+cite+si", "normal+sim"); the pre-v2.9 mark "cite"
reads as "selected+cite". The Markdown checkboxes show stage and ⭐ only; editing them keeps the override.

Every report line carries the paper's DOI:
  [ ] ✅ Select | [ ] ⭐ Cite | [ ] 🗄️ Archive <!-- doi:10.1109/... -->
(in tables the bar is escaped as "\\|"; pre-v2.8 lines without the Select box are still read). Since every run
writes the checkboxes *from* the store, a box that differs from the store is the user's edit. sync_markdown_marks():
  1. reads MASTER_TABLE.md, Weekly_Briefings/*.md and Topic_Dives/*.md, oldest file first, so the most
     recently saved file wins when two files disagree;
  2. applies the edits: stage = Archive if ticked, else Select if ticked, else Candidate; cite = the ⭐ box;
  3. rewrites the boxes in every file to the store's state, so an old report can never undo a newer
     decision.
curation_marks.json (exported by the HTML pages' "💾 Save Marks") joins step 1 in the same save-time order;
after it's applied it's renamed to curation_marks.applied.json so it's never applied twice.
Archived papers keep their abstract and digest; they're only hidden from MASTER_TABLE.md's active view
and from the .bib files, and stay searchable by --topic / --recall.
"""
import json
import re
import secrets
from pathlib import Path

from env_guard import ensure_minisforum_env

ensure_minisforum_env()

# groups: 1 Select box (absent in pre-v2.8 lines), 2 bar, 3 Cite box, 4 Archive box, 5 DOI
BOX_RX = re.compile(r"(?:\[([ xX])\] ✅ Select \\?\| )?\[([ xX])\] ⭐ Cite (\\?\|) \[([ xX])\] 🗄️ Archive <!-- doi:(\S+?) -->")
STAGES = ("normal", "selected", "archived")


SI_TOKENS = {"si": "silicon_verified", "sim": "simulation_only"}
KEEP = object()  # set_state: leave the silicon override as it is


def fmt_mark(stage, cited, si=None):
    tok = next((t for t, v in SI_TOKENS.items() if v == si), None)
    return stage + ("+cite" if cited else "") + (f"+{tok}" if tok else "")


def mark_of(p):
    """The paper's mark string: 'selected', 'normal+cite', 'selected+cite+si', …"""
    return fmt_mark(p.get("user_mark") or "normal", p.get("cited"), p.get("user_silicon"))


def parse_mark(mark):
    """'selected+cite+si' → ('selected', 1, 'silicon_verified'); legacy 'cite' → ('selected', 1, None);
    invalid → None."""
    mark = str(mark or "")
    if mark == "cite":
        return "selected", 1, None
    stage, *flags = mark.split("+")
    if stage not in STAGES or any(f not in ("cite", *SI_TOKENS) for f in flags):
        return None
    si = next((SI_TOKENS[f] for f in flags if f in SI_TOKENS), None)
    return stage, int("cite" in flags), si


def set_state(store, doi, stage, cited, si=KEEP):
    upd = {"user_mark": stage, "cited": int(bool(cited))}
    if si is not KEEP:
        upd["user_silicon"] = si
    store.update(doi, upd)


def cite_on(stage):
    """Stage after ⭐ is switched on: a 📋 Candidate becomes ✅ Selected; Selected/Archived stay."""
    return "selected" if stage == "normal" else stage


def boxes(doi, mark, table=False):
    stage, cited, _ = parse_mark(mark) or ("normal", 0, None)
    s, a = ("x" if stage == "selected" else " "), ("x" if stage == "archived" else " ")
    c = "x" if cited else " "
    bar = "\\|" if table else "|"
    return f"[{s}] ✅ Select {bar} [{c}] ⭐ Cite {bar} [{a}] 🗄️ Archive <!-- doi:{doi} -->"


def box_mark(sel, cite, arch, current):
    """The mark a ticked line asks for, given the store's current mark. Archive wins over Select. A pre-v2.8
    line (no Select box) can't express 'selected', so it keeps a selected paper selected. Newly ticking ⭐ on a
    Candidate also selects it. The silicon override isn't in the boxes, so it's carried over."""
    cur_stage, cur_cited, cur_si = parse_mark(current) or ("normal", 0, None)
    cited = int(cite in "xX")
    if arch in "xX":
        stage = "archived"
    elif sel is None:
        stage = "selected" if cur_stage == "selected" else "normal"
    else:
        stage = "selected" if sel in "xX" else "normal"
    if cited and not cur_cited and stage == "normal" and cur_stage == "normal":
        stage = cite_on(stage)
    return fmt_mark(stage, cited, cur_si)


def line(p):
    return f"- **Curation**: {boxes(p['doi'], mark_of(p))}"


TOKEN_FILE = Path(__file__).resolve().parent / ".radar_token"


def sync_token():
    """Shared secret between radar_sync_server.py and the generated pages (random, gitignored)."""
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def page_sync_config(cfg):
    sc = cfg.get("sync_server", {})
    return {"hosts": sc.get("hosts", ["127.0.0.1"]), "port": sc.get("port", 18765),
            "timeout": sc.get("probe_timeout_ms", 1500), "token": sync_token()}


VIEW_RX = re.compile(r"^[a-z0-9]{1,20}$")


def system_dir(cfg):
    """IC_Paper_Radar/_system (v2.13): machine files the user doesn't open (store backup, prefs, sync logs)."""
    d = Path(cfg["paths"].get("system_dir") or Path(cfg["paths"]["onedrive_root"]) / "_system")
    d.mkdir(parents=True, exist_ok=True)
    return d


def prefs_file(cfg):
    """Dashboard settings shared by every device (v2.12): IC_Paper_Radar/_system/dashboard_prefs.json."""
    return system_dir(cfg) / "dashboard_prefs.json"


def clean_prefs(prefs):
    """Only what the pages may store: layout = {main: [view…], more: [view…], t: epoch ms}. None if malformed."""
    lay = (prefs or {}).get("layout") if isinstance(prefs, dict) else None
    if not isinstance(lay, dict):
        return None
    views = [lay.get("main"), lay.get("more")]
    if not all(isinstance(v, list) and len(v) <= 40 and all(isinstance(k, str) and VIEW_RX.match(k) for k in v)
               for v in views) or not isinstance(lay.get("t", 0), (int, float)):
        return None
    return {"layout": {"main": views[0], "more": views[1], "t": int(lay.get("t", 0))}}


def load_prefs(cfg):
    try:
        return clean_prefs(json.loads(prefs_file(cfg).read_text(encoding="utf-8"))) or {}
    except (OSError, ValueError):
        return {}


def save_prefs(cfg, prefs):
    """Newest layout wins: a save older than the stored one is ignored. Returns what is stored now."""
    new, cur = clean_prefs(prefs), load_prefs(cfg)
    if new and new["layout"]["t"] >= (cur.get("layout") or {}).get("t", 0):
        f = prefs_file(cfg)
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(new, indent=1), encoding="utf-8")
        tmp.replace(f)
        return new
    return cur


def marks_exports(cfg):
    """curation_marks*.json saved by the HTML pages, in IC_Paper_Radar and in your Downloads
    (browsers add ' (1)' etc.). Not the applied copy, and not the sync server's own log (*.live.json)."""
    dirs = [Path(cfg["paths"]["onedrive_root"])] + [Path(d) for d in cfg["paths"].get("marks_extra_dirs", [])]
    return [f for d in dirs if d.exists() for f in d.glob("curation_marks*.json")
            if "applied" not in f.name and "live" not in f.name]


def report_files(cfg):
    root = Path(cfg["paths"]["onedrive_root"])
    files = [root / "MASTER_TABLE.md"] + list(Path(cfg["paths"]["weekly_dir"]).glob("*.md")) \
        + list(Path(cfg["paths"]["topic_dir"]).glob("*.md"))
    return sorted((f for f in files if f.exists()), key=lambda f: f.stat().st_mtime)


def sync_markdown_marks(store, cfg, log=print, read_edits=True):
    """Apply checkbox edits from the reports to the store, then normalise all files. Returns #changes.
    read_edits=False only normalises: use it at the end of a run, when files may still show a state that a
    CLI flag (--cite/--uncite …) just changed and would otherwise be mistaken for a user edit."""
    files = report_files(cfg)
    current = all_marks(store)
    wanted = {}
    exports = marks_exports(cfg) if read_edits else []
    sources = sorted(files + exports, key=lambda f: f.stat().st_mtime) if read_edits else []
    for f in sources:  # oldest first: later files overwrite earlier ones
        if f.suffix == ".json":
            try:
                for doi, mark in json.loads(f.read_text(encoding="utf-8")).get("marks", {}).items():
                    st = parse_mark(mark)
                    mark = st and fmt_mark(*st)  # canonical (legacy 'cite' included)
                    if doi in current and st and mark != current[doi]:
                        wanted[doi] = (mark, f.name)
            except (ValueError, AttributeError) as e:
                log(f"  curation: {f.name} unreadable ({e}); left in place")
                exports.remove(f)
            continue
        for m in BOX_RX.finditer(f.read_text(encoding="utf-8")):
            doi = m[5]
            mark = box_mark(m[1], m[2], m[4], current.get(doi))
            if doi in current and mark != current[doi]:
                wanted[doi] = (mark, f.name)
    for doi, (mark, src) in wanted.items():
        set_state(store, doi, *parse_mark(mark))
        current[doi] = mark
        log(f"  curation: {doi} → {mark} (from {src})")
    # applied once: the newest export is kept as IC_Paper_Radar/_system/curation_marks.applied.json for reference,
    # older and numbered duplicates ("curation_marks (1).json", Downloads copies) are deleted
    applied_copy = system_dir(cfg) / "curation_marks.applied.json"
    for i, f in enumerate(sorted(exports, key=lambda f: f.stat().st_mtime, reverse=True)):
        if i == 0:
            f.replace(applied_copy)
        else:
            f.unlink(missing_ok=True)
    for f in files:
        text = f.read_text(encoding="utf-8")
        new = BOX_RX.sub(lambda m: boxes(m[5], current.get(m[5], "normal"), table=m[3].startswith("\\")), text)
        if new != text:
            f.write_text(new, encoding="utf-8")
    return len(wanted)


def all_marks(store, where="1=1"):
    return {r[0]: fmt_mark(r[1] or "normal", r[2], r[3])
            for r in store.db.execute(f"SELECT doi, user_mark, cited, user_silicon FROM papers WHERE {where}")}


# CLI flag → change: a stage, or the ⭐ flag on/off
ACTIONS = {"select": ("stage", "selected"), "unselect": ("stage", "normal"), "archive": ("stage", "archived"),
           "unarchive": ("stage", "normal"), "cite": ("cite", 1), "uncite": ("cite", 0)}


def apply_action(store, p, action):
    """One CLI action on paper p; stage and ⭐ stay independent (⭐ on a Candidate also selects it)."""
    kind, val = ACTIONS[action]
    stage, cited = p.get("user_mark") or "normal", int(bool(p.get("cited")))
    if kind == "stage":
        stage = val
    else:
        stage, cited = (cite_on(stage) if val else stage), val
    set_state(store, p["doi"], stage, cited)  # the silicon override stays
    return fmt_mark(stage, cited, p.get("user_silicon"))


def set_mark(store, needle, action, log=print):
    """--select / --cite / --archive / --unselect / --uncite / --unarchive: DOI or a substring of DOI/title
    (max 5 matches)."""
    n = needle.lower().strip()
    hits = [p for p in store.where("lower(doi)=?", (n,))] or \
        [p for p in store.where("lower(doi) LIKE ? OR lower(title) LIKE ?", (f"%{n}%", f"%{n}%"))]
    if not hits:
        log(f"No paper matches '{needle}'.")
        return 0
    if len(hits) > 5:
        log(f"'{needle}' matches {len(hits)} papers; be more specific (or use the DOI):")
        for p in hits[:10]:
            log(f"  {p['doi']}  {p['title'][:80]}")
        return 0
    for p in hits:
        mark = apply_action(store, p, action)
        log(f"  {mark:<14} {p['doi']}  {p['title'][:80]}")
    return len(hits)
