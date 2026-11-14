"""Shared corpus repo (v2.18; peer overlays v2.19): keep every collaborator's corpus identical with one command,
and let each one see the others' radars.

  python briefing.py --sync-data-repo      (also runs after every Friday finalize when the clone exists)
  python briefing.py --pull-data-repo      read only: steps 1-2 below, nothing exported or pushed (pull())

The repo (a private Git repo named ic-paper-radar-data) holds paper_store_clean_share.sqlite (clean: no marks,
notes, pillars or scores) and peers/<peer_id>.json, one curation overlay per collaborator (their pillar names
and, per paper they curated, pillar, score, stage, ⭐, Si call, 🏷️ note and status). Git can't merge the binary
file, so nobody ever merges it in Git:
  1. git fetch origin + git reset --hard origin/main: take the remote exactly as it is; then every other
     peers/<id>.json replaces that peer's rows in peer_curation (store.import_peer_overlay)
  2. store.merge_store(): union the shared file into this radar's own store (new DOIs as 'external', marks and
     notes here untouched), then adopt the external papers that score ≥ min_score (data_repo.adopt_external)
  3. store.export_clean_share_db(): write this store, cleaned, back over the shared file (every row, 'external'
     ones included), and copy it to paths.share_db when that is set; then write this radar's own overlay to
     peers/<peer_id>.json (data_repo.share_curation, share_notes)
  4. git commit + git push only if something is new for the remote: the shared file gives it something it lacks
     (new DOIs, objective fields it has empty, higher citation counts) or this radar's overlay changed;
     otherwise the remote files are restored, so two radars whose exports differ only in bytes never trade
     commits. A rejected push (someone pushed meanwhile) waits a random 2–5 s and goes back to step 1, up to
     PUSH_RETRIES (3) times, so up to 5 radars syncing in the same minute serialize instead of failing
A reset can't lose anything: the remote's papers come in at step 2, this radar's own are in its store and
go out at step 3. After both collaborators have run it, both stores hold the same union of DOIs.
"""
import getpass
import json
import random
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

from env_guard import ensure_minisforum_env

ensure_minisforum_env()

import store as store_mod

HERE = Path(__file__).resolve().parent
DB_NAME = "paper_store_clean_share.sqlite"
PEERS_DIR = "peers"
REMOTE_MARK = "ic-paper-radar-data"  # origin must contain this before anything is reset
PUSH_RETRIES = 3          # fresh rounds after a rejected push (another radar pushed first)
PUSH_BACKOFF = (2.0, 5.0)  # random wait in seconds before each retry, so colliding radars spread out


def repo_dir(cfg):
    """paths.data_repo_dir (~ allowed), else the sibling folder ../ic-paper-radar-data."""
    d = (cfg.get("paths") or {}).get("data_repo_dir")
    return Path(d).expanduser() if d else HERE.parent / REMOTE_MARK


def _git(repo, *args, check=True):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    except FileNotFoundError:
        raise RuntimeError("git is not installed or not on PATH")
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r


def _slug(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(s or "")).strip("-.")[:39]


def peer_id(cfg, repo):
    """This radar's name for collaborators: data_repo.peer_id, else the clone's git user.name, else the
    login name (file-name safe)."""
    for cand in ((cfg.get("data_repo") or {}).get("peer_id"),
                 _git(repo, "config", "user.name", check=False).stdout.strip() if repo else "",
                 getpass.getuser()):
        s = _slug(cand)
        if s and store_mod.PEER_ID_RX.match(s):
            return s
    return "me"


def _count(db):
    if not db.exists():
        return 0
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        return c.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    finally:
        c.close()


def _snapshot(db):
    """{doi: (filled fields, cited_by, ieee_cites, first_seen)} of a share file, for _gain(). A field counts as
    filled unless it is NULL, '', '[]' or 'null' (store.EMPTY), so those four are the same thing here."""
    if not db.exists():
        return {}
    cols = [c for c in (*store_mod.OBJECTIVE, *store_mod.BOOKKEEPING, "digest")]
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        have = {r[1] for r in c.execute("PRAGMA table_info(papers)")}
        cols = [x for x in cols if x in have]
        out = {}
        for r in c.execute(f"SELECT doi, cited_by, ieee_cites, first_seen, {', '.join(cols)} FROM papers"):
            out[str(r[0]).lower()] = ({k for k, v in zip(cols, r[4:]) if v not in store_mod.EMPTY},
                                      r[1] or 0, r[2] or 0, r[3] or "")
        return out
    finally:
        c.close()


def _gain(remote, new):
    """What the new export gives the remote: (new DOIs, rows with more filled fields, higher citations or an
    earlier first_seen). Only a real gain is pushed, so two radars whose files differ only in bytes (or in
    how they write an empty field) don't trade commits forever."""
    added = sum(1 for d in new if d not in remote)
    better = sum(1 for d, (f, c1, c2, fs) in new.items() if d in remote
                 and (f - remote[d][0] or c1 > remote[d][1] or c2 > remote[d][2]
                      or (fs and (not remote[d][3] or fs < remote[d][3]))))
    return added, better


def _identity(repo, me):
    """git -c options for the sync commit when this computer has no git identity (a fresh Git install): commit as
    the peer id with a placeholder address, set for that one commit only (nothing is written to any git config)."""
    have = [_git(repo, "config", k, check=False).stdout.strip() for k in ("user.name", "user.email")]
    if all(have):
        return []
    return ["-c", f"user.name={me}", "-c", f"user.email={me}@ic-paper-radar.local"]


def check_clone(repo, cfg=None):
    """None if `repo` is a clone of a data repo, else the reason it isn't. A data repo: origin names
    ic-paper-radar-data, or the clone holds the MARKER file (v3.0 protocol, any repo name), or its origin is
    data_repo.remote_url."""
    if not (repo / ".git").exists():
        return f"no clone at {repo}"
    origin = _git(repo, "remote", "get-url", "origin", check=False).stdout.strip()
    own = ((cfg or {}).get("data_repo") or {}).get("remote_url") or ""
    if REMOTE_MARK in origin or (repo / MARKER).exists() or (own and _norm_url(own) == _norm_url(origin)):
        return None
    return f"{repo} is not a data repo (origin: {origin or 'none'}; no {MARKER} file)"


# ---------- v3.0: user-owned private data repos (protocol v1) ----------
# Anyone can own one: `briefing.py --init-data-repo <owner/name | URL>` creates (gh) or clones it, writes the
# files below and pushes main. A repo is a data repo when its origin names ic-paper-radar-data (the original
# one), when it holds the MARKER file, or when its origin is this radar's data_repo.remote_url; nothing else is
# ever reset. data_repo.read_repos lists more data repos (URLs or local folders) that collaborators shared for
# reading: they are pulled (never pushed) into <data_repo_dir>_peers/<slug> and merged like the primary one.
MARKER = "IC_PAPER_RADAR_DATA"
PROTOCOL = 1
README = """# IC Paper Radar: shared corpus (private data repo)

This private repository is an **IC Paper Radar data repo** (protocol v{protocol}). The public code
(`data_repo.py` of IC Paper Radar) defines it; nobody edits these files by hand.

| File | What it is |
|---|---|
| `paper_store_clean_share.sqlite` | The clean shared corpus: papers, abstracts, digests (no marks, notes, pillars or scores). Binary: Git never merges it. Each radar fetches it, merges it into its own store and exports the union back. |
| `peers/<peer_id>.json` | One curation overlay per collaborator (pillar names; per curated paper its pillar, score, stage, ⭐, note). |
| `{marker}` | Marks this repository as a data repo, so `--sync-data-repo` may reset its clone. |

- **Sync (read and write):** `python briefing.py --sync-data-repo` or 🔄 Full Sync in STARTUP.html. The owner
  and collaborators with write access share one corpus.
- **Read only:** give a collaborator read access (Settings → Collaborators). They add this repo's URL to
  `"data_repo": {{"read_repos": [...]}}` in their config.json (or in STARTUP.html), and
  `python briefing.py --pull-data-repo` merges it into their radar and shows your radar under 👥 Peers.
"""
REPO_URL_RX = re.compile(r"^(https://[A-Za-z0-9.-]+(:\d+)?/|git@[A-Za-z0-9.-]+:)[\w.-]+/[\w.-]+?(\.git)?/?$")
SLUG_RX = re.compile(r"^[A-Za-z0-9][\w.-]*/[\w.-]+$")


def _norm_url(u):
    """https://github.com/a/b(.git)(/) and git@github.com:a/b(.git) → 'github.com/a/b' (lower case)."""
    u = str(u or "").strip().lower().removesuffix("/").removesuffix(".git")
    u = re.sub(r"^git@([^:]+):", r"\1/", u)
    return re.sub(r"^https?://", "", u)


def repo_url(spec):
    """'owner/name' → https://github.com/owner/name.git; a clone URL (no user name or token in it) as it is;
    else ValueError. A local folder (an existing path) is returned as a resolved path string."""
    s = str(spec or "").strip()
    if SLUG_RX.match(s) and not Path(s).expanduser().exists():
        return f"https://github.com/{s}.git"
    if REPO_URL_RX.match(s):
        return s
    p = Path(s).expanduser()
    if s and p.exists():
        return str(p.resolve())
    raise ValueError(f"not a GitHub owner/name, a clone URL (https://… or git@…, without user name or token) or a "
                     f"folder: {s!r}")


def _origin(repo):
    return _git(repo, "remote", "get-url", "origin", check=False).stdout.strip()


def ensure_clone(cfg, log=print):
    """Clone data_repo.remote_url into paths.data_repo_dir when there is no clone yet (a new computer)."""
    repo, url = repo_dir(cfg), ((cfg.get("data_repo") or {}).get("remote_url") or "").strip()
    if (repo / ".git").exists() or not url:
        return repo
    if repo.exists() and any(repo.iterdir()):
        raise RuntimeError(f"{repo} exists and isn't a clone: move it away or set paths.data_repo_dir")
    log(f"Cloning data_repo.remote_url into {repo} ...")
    _git(HERE, "clone", "--", repo_url(url), str(repo))
    return repo


def _peers_cache(cfg):
    return Path(str(repo_dir(cfg)) + "_peers")


# ---------- v3.0.4: read repos are isolated by default; domain-similarity check; opt-in merge ----------
# data_repo.read_repos entries: "owner/name" (a URL or a folder) = isolated, or {"repo": "owner/name",
# "merge_corpus": true} to merge a similar-domain repo into this store (its papers then round-trip like the
# primary repo's); "force_merge": true also merges a different-domain repo (STARTUP.html asks first).
# Isolated: the repo is fetched into <data_repo_dir>_peers/<slug> (or read in place) and its peers get their own
# Peers/DASHBOARD_<peer>.html built from that repo's own file (html_renderer); this store gains 0 rows.
SIMILAR_VENUE_OVERLAP = 0.15  # ≥ this share of a repo's papers in venues this radar uses → similar


def read_repo_entries(cfg):
    """data_repo.read_repos as [{'spec', 'merge', 'force'}] (strings are isolated; bad entries are left out)."""
    out = []
    for e in (cfg.get("data_repo") or {}).get("read_repos") or []:
        if isinstance(e, str) and e.strip():
            out.append({"spec": e.strip(), "merge": False, "force": False})
        elif isinstance(e, dict) and isinstance(e.get("repo"), str) and e["repo"].strip():
            out.append({"spec": e["repo"].strip(), "merge": e.get("merge_corpus") is True,
                        "force": e.get("force_merge") is True})
    return out


def read_repo_dir(cfg, spec):
    """The folder a read repo is read from (no network): a local folder holding the shared file in place, else
    its clone in <data_repo_dir>_peers/<repo name>-<8 hex of its URL> (two repos never share a folder, even
    with the same name or a long common path)."""
    import hashlib
    src = repo_url(spec)
    if Path(src).exists() and (Path(src) / DB_NAME).exists() and not REPO_URL_RX.match(str(spec).strip()):
        return Path(src)
    tag = hashlib.sha1(_norm_url(src).encode("utf-8")).hexdigest()[:8]
    return _peers_cache(cfg) / f"{_slug(repo_label(spec))[:30] or 'repo'}-{tag}"


def repo_label(spec):
    """'bio-paper-radar-data' for owner/bio-paper-radar-data, a URL or a folder."""
    s = re.sub(r"\.git$", "", str(spec or "").strip().rstrip("/\\"))
    return re.split(r"[/\\:]", s)[-1] or s


def primary_label(cfg):
    """The primary data repo's name (its remote_url, else the clone folder's name)."""
    url = ((cfg.get("data_repo") or {}).get("remote_url") or "").strip()
    return repo_label(url) if url else repo_dir(cfg).name


def repo_meta(d):
    """A data repo's own field: domain_preset and radar_title from its MARKER file (v3.0.4), else the most common
    domain_preset among its peers/*.json. Unknown values come back as ''."""
    import presets
    try:
        m = json.loads((d / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m = {}
    m = m if isinstance(m, dict) else {}
    seen = {}
    for f in sorted((d / PEERS_DIR).glob("*.json")) if (d / PEERS_DIR).exists() else []:
        try:
            dp = json.loads(f.read_text(encoding="utf-8")).get("domain_preset")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(dp, str):
            seen[dp] = seen.get(dp, 0) + 1
    dp = m.get("domain_preset") if isinstance(m.get("domain_preset"), str) else (max(seen, key=seen.get) if seen else "")
    title = m.get("radar_title")
    return {"domain_preset": dp if dp in presets.PRESETS else "",
            "radar_title": re.sub(r"[\x00-\x1f]", " ", title)[:80].strip() if isinstance(title, str) else ""}


def _ro_uri(p):
    import urllib.parse
    return f"file:{urllib.parse.quote(Path(p).resolve().as_posix(), safe='/:')}?mode=ro"


def similarity(cfg, d, store_path):
    """Domain Similarity Check of the read repo in folder `d` against this radar (both files read only):
    'similar' when both use the same domain_preset or ≥ SIMILAR_VENUE_OVERLAP of its papers are in venues this
    radar's own papers use (Beyond-IEEE / Nature and merged papers left out); otherwise 'different'.
    Returns {kind, mine, theirs, mine_label, theirs_label, venue_overlap, doi_overlap, papers, title}."""
    import presets
    mine, meta = presets.active_name(cfg), repo_meta(d)
    theirs = meta["domain_preset"]
    n, vo, do = 0, 0.0, 0.0
    db = d / DB_NAME
    if db.exists():
        c = sqlite3.connect(_ro_uri(db), uri=True)
        try:
            n = c.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            if n and store_path and Path(store_path).exists():
                c.execute("ATTACH DATABASE ? AS mine", (_ro_uri(store_path),))
                v = c.execute("SELECT COUNT(*) FROM papers WHERE LOWER(COALESCE(venue,'')) IN (SELECT DISTINCT "
                              "LOWER(venue) FROM mine.papers WHERE COALESCE(venue,'') != '' AND COALESCE(grp,'') != "
                              "'beyond' AND status NOT IN ('external','external_ro'))").fetchone()[0]
                dd = c.execute("SELECT COUNT(*) FROM papers WHERE doi IN (SELECT doi FROM mine.papers)").fetchone()[0]
                vo, do = v / n, dd / n
        except sqlite3.Error:
            pass
        finally:
            c.close()
    kind = "similar" if (theirs and theirs == mine) or vo >= SIMILAR_VENUE_OVERLAP else "different"
    return {"kind": kind, "mine": mine, "theirs": theirs, "mine_label": presets.short(mine),
            "theirs_label": presets.short(theirs), "venue_overlap": round(vo, 3), "doi_overlap": round(do, 3),
            "papers": n, "title": meta["radar_title"]}


def repo_mode(entry, sim):
    """'merged' only for merge_corpus on a similar repo (or with force_merge); everything else is 'isolated'."""
    return "merged" if entry["merge"] and (entry["force"] or (sim or {}).get("kind") == "similar") else "isolated"


def isolated_repos(cfg, store_path=None, log=print):
    """[(entry, folder, similarity)] for the read repos in isolated mode that are already on disk (no network):
    html_renderer builds their peers' pages from these folders."""
    out = []
    for e in read_repo_entries(cfg):
        try:
            d = read_repo_dir(cfg, e["spec"])
        except Exception:
            continue
        if (d / DB_NAME).exists():
            sim = similarity(cfg, d, store_path)
            if repo_mode(e, sim) == "isolated":
                out.append((e, d, sim))
    return out


def _stamp_marker(repo, cfg):
    """Put domain_preset and radar_title into the MARKER file when they are missing (v3.0.4), so a radar reading
    this repo can tell its field; the first radar to write them wins. Returns True if the file changed."""
    import presets
    f = repo / MARKER
    try:
        m = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        m = {}
    m = m if isinstance(m, dict) else {}
    new = {"protocol": PROTOCOL, "kind": "ic-paper-radar-data", **m}
    new.setdefault("domain_preset", presets.active_name(cfg))
    new.setdefault("radar_title", str((cfg.get("data_repo") or {}).get("radar_title") or "")
                   or repo_label(_origin(repo) or str(repo)))
    if f.exists() and new == m:
        return False
    f.write_text(json.dumps(new, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def read_repo_dirs(cfg, log=print):
    """[(entry, folder)] for data_repo.read_repos (read_repo_entries): a local folder that holds the shared file is
    read in place (never touched); a URL, or a local git repo (e.g. a bare one), is cloned into
    <data_repo_dir>_peers/<slug> the first time, then fetched + reset (that cache is this radar's own)."""
    out = []
    for e in read_repo_entries(cfg):
        spec = e["spec"]
        try:
            src = repo_url(spec)
            d = read_repo_dir(cfg, spec)
            if d == Path(src):
                out.append((e, d))
                continue
            if (d / ".git").exists():
                if _norm_url(_origin(d)) != _norm_url(src):
                    raise RuntimeError(f"{d} is a clone of another repo")
                _git(d, "fetch", "origin")
                _git(d, "reset", "--hard", "origin/HEAD" if _git(d, "rev-parse", "--verify", "-q", "origin/HEAD",
                                                                   check=False).returncode == 0 else "origin/main")
            else:
                d.parent.mkdir(parents=True, exist_ok=True)
                _git(HERE, "clone", "--", src, str(d))
                if not (d / DB_NAME).exists() and _git(d, "rev-parse", "--verify", "-q", "origin/main", check=False).returncode == 0:
                    _git(d, "checkout", "-q", "-B", "main", "origin/main")  # its HEAD names a branch it doesn't have
            out.append((e, d))
        except Exception as err:
            log(f"  read repo {spec}: skipped ({err})")
    return out


def pull_read_repos(store, cfg, me, adopt=None, log=print):
    """Every data_repo.read_repos entry: fetched (never pushed), then a Domain Similarity Check against this radar.
    - isolated (the default, and always for a different-domain repo without force_merge): nothing is written into
      this store; its peers' pages are built from the repo's own file (html_renderer.collect_peer_pages);
    - merged (merge_corpus on a similar repo): its peers/*.json → peer_curation and its shared file merged into
      this store as 'external' (then adopted ≥ min_score), so it round-trips into the primary repo like the
      primary corpus.
    Returns {spec: {'papers', 'new', 'enriched', 'peers', 'mode', 'similarity'}}."""
    out, merged = {}, False
    for e, d in read_repo_dirs(cfg, log):
        spec, db, label = e["spec"], d / DB_NAME, repo_label(e["spec"])
        sim = similarity(cfg, d, getattr(store, "path", None))
        mode = repo_mode(e, sim)
        if e["merge"] and mode == "isolated":
            log(f"  read repo {spec}: merge_corpus ignored: 🟠 different discipline ({sim['theirs_label'] or 'unknown'} "
                f"vs. {sim['mine_label']}); kept isolated (set \"force_merge\": true to merge anyway)")
        st, peers = {"new": 0, "enriched": 0}, {}
        if mode == "merged":
            merged = True
            peers = import_peers(store, d, me, log, source=label) if (d / PEERS_DIR).exists() else {}
            if db.exists():
                st = store_mod.merge_store(store, db, log=lambda m: None)
        else:
            for f in sorted((d / PEERS_DIR).glob("*.json")) if (d / PEERS_DIR).exists() else []:
                if f.stem != me and store_mod.PEER_ID_RX.match(f.stem):
                    peers[f.stem] = "isolated"
                    if store.meta(f"peer_source:{f.stem}") == label:  # was merged before: its page now comes from the repo
                        store_mod.drop_peer(store, f.stem)
        out[spec] = {"papers": _count(db), "new": st["new"], "enriched": st["enriched"], "peers": peers,
                     "mode": mode, "similarity": sim}
        badge = "🟢 similar" if sim["kind"] == "similar" else "🟠 different"
        log(f"  read repo {spec}: {out[spec]['papers']} papers, {badge} ({sim['theirs_label'] or '?'} vs. "
            f"{sim['mine_label']}, venue overlap {sim['venue_overlap']:.0%}), "
            + (f"merged ({st['new']} new, {st['enriched']} enriched)" if mode == "merged"
               else "🔒 isolated (0 rows written to your store)")
            + (", peers " + ", ".join(peers) if peers else ""))
    if merged and adopt and (cfg.get("data_repo") or {}).get("adopt_external", True):
        log(f"  read repos: {adopt(store, cfg)} adopted into the archive (≥ min_score)")
    return out


def _write_protocol_files(repo):
    (repo / MARKER).write_text(json.dumps({"protocol": PROTOCOL, "kind": "ic-paper-radar-data"}) + "\n", encoding="utf-8")
    (repo / ".gitattributes").write_text("*.sqlite binary\n*.json text eol=lf\n*.md text eol=lf\n", encoding="utf-8")
    (repo / "README.md").write_text(README.format(protocol=PROTOCOL, marker=MARKER), encoding="utf-8")


def init_repo(spec, store, store_path, cfg, secrets=(), log=print):
    """--init-data-repo <owner/name | URL | folder> (STARTUP.html ✨ Create / Init My Private Repo):
      1. with `gh` signed in and an owner/name: `gh repo create owner/name --private` if it doesn't exist yet;
      2. clone it into paths.data_repo_dir (default ../ic-paper-radar-data);
      3. an empty repo gets the protocol files (MARKER, .gitattributes, README.md), this radar's
         paper_store_clean_share.sqlite and peers/<peer_id>.json, one commit, and `git push -u origin main`;
         a repo that already holds a corpus is just connected;
      4. config.json: data_repo.remote_url = the URL (so another computer clones it automatically).
    Returns {'url', 'dir', 'created', 'initialized'}; raises RuntimeError / ValueError."""
    import shutil as sh
    url = repo_url(spec)
    repo = repo_dir(cfg)
    created = False
    if (repo / ".git").exists():
        if _norm_url(_origin(repo)) != _norm_url(url):
            raise RuntimeError(f"{repo} is already a clone of {_origin(repo) or 'another repo'}: set paths.data_repo_dir "
                               "to another folder for a second data repo, or use data_repo.read_repos to read it")
    else:
        slug = str(spec).strip()
        if SLUG_RX.match(slug) and not Path(slug).expanduser().exists() and sh.which("gh"):
            if subprocess.run(["gh", "repo", "view", slug], capture_output=True, text=True).returncode:
                log(f"Creating the private GitHub repo {slug} (gh) ...")
                r = subprocess.run(["gh", "repo", "create", slug, "--private", "--description",
                                    "IC Paper Radar shared corpus (private data repo)"], capture_output=True, text=True)
                if r.returncode:
                    raise RuntimeError(f"gh repo create failed: {(r.stderr or r.stdout).strip()[-300:]}")
                created = True
        if repo.exists() and any(repo.iterdir()):
            raise RuntimeError(f"{repo} exists and isn't empty: choose another paths.data_repo_dir")
        log(f"Cloning {url} into {repo} ...")
        r = _git(HERE, "clone", "--", url, str(repo), check=False)
        if r.returncode:
            raise RuntimeError(f"git clone failed: {(r.stderr or r.stdout).strip()[-300:]} (create the empty private repo "
                               "on github.com first, or install the GitHub CLI `gh` and sign in)")
    has_commit = _git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0
    initialized = False
    if not has_commit or not (repo / DB_NAME).exists():
        me = peer_id(cfg, repo)
        log(f"Initializing the data repo (protocol v{PROTOCOL}) as {me} ...")
        _write_protocol_files(repo)
        _stamp_marker(repo, cfg)
        kw = {}
        try:
            import arxiv_source
            kw["skip_arxiv"] = arxiv_source.share_skip(cfg)
        except ImportError:
            pass
        s = store_mod.export_clean_share_db(store_path, repo / DB_NAME, secrets=secrets, **kw)
        log(f"  exported {s['papers']} papers into {DB_NAME}")
        if (cfg.get("data_repo") or {}).get("share_curation", True):
            write_overlay(store, cfg, repo, me, secrets)
        _git(repo, "add", "-A")
        _git(repo, *_identity(repo, me), "commit", "-m", f"Initialize IC Paper Radar data repo (protocol v{PROTOCOL})")
        _git(repo, "branch", "-M", "main")
        r = _git(repo, "push", "-u", "origin", "main", check=False)
        if r.returncode:
            raise RuntimeError(f"push failed: {(r.stderr or r.stdout).strip()[-300:]}")
        initialized = True
        log("  pushed main")
    else:
        log("  the repo already holds a corpus: connected (run 📥 Read / --pull-data-repo next)")
    return {"url": url, "dir": str(repo), "created": created, "initialized": initialized}


def import_peers(store, repo, me, log=print, source=""):
    """Every peers/<id>.json except this radar's own → peer_curation (`source`: the repo it came from). Returns
    {peer_id: rows}."""
    out = {}
    for f in sorted((repo / PEERS_DIR).glob("*.json")):
        if f.stem == me or not store_mod.PEER_ID_RX.match(f.stem):
            continue
        try:
            out[f.stem] = store_mod.import_peer_overlay(store, json.loads(f.read_text(encoding="utf-8")), f.stem,
                                                        source=source)
        except Exception as e:
            log(f"  peer overlay {f.name} skipped: {e}")
    return out


def write_overlay(store, cfg, repo, me, secrets=()):
    """This radar's overlay → peers/<me>.json. Rewritten only when its content changed ('updated' is the time of
    that change), and refused if any text holds a local path or a secret. Returns (changed, rows)."""
    import arxiv_source, catalog  # here: catalog imports modules that import this one
    import presets
    dr = cfg.get("data_repo") or {}
    kwmap = catalog._kw_pillars(cfg)
    ov = store_mod.peer_overlay(store, me, [catalog.PILLARS[k] for k in sorted(catalog.PILLARS) if k],
                                lambda p: catalog.pillar_of(p, kwmap), share_notes=dr.get("share_notes", True), domain_preset=presets.active_name(cfg),
                                radar_title=str(cfg.get("radar_title") or "")[:80] or f"{me}'s Radar",
                                skip_arxiv=arxiv_source.share_skip(cfg))
    text = json.dumps(ov, ensure_ascii=False, sort_keys=True)
    hit = store_mod.FORBIDDEN.search(text) or next((x for x in secrets if x and x in text), None)
    if hit:
        raise RuntimeError("peer overlay not written: a local path or secret is in a note")
    f = repo / PEERS_DIR / f"{me}.json"
    try:
        old = json.loads(f.read_text(encoding="utf-8"))
        old.pop("updated", None)
    except (OSError, ValueError):
        old = None
    if old == json.loads(text):
        return False, len(ov["rows"])
    ov["updated"] = datetime.now().isoformat(timespec="seconds")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(ov, ensure_ascii=False, sort_keys=True, indent=0) + "\n", encoding="utf-8")
    return True, len(ov["rows"])


def _round(store, store_path, cfg, repo, me, adopt, secrets, push, log):
    db = repo / DB_NAME
    _git(repo, "fetch", "origin")
    _git(repo, "reset", "--hard", "origin/main")
    before, remote = _count(db), _snapshot(db)
    peers = import_peers(store, repo, me, log, source=primary_label(cfg))
    log(f"  1. remote: {before} papers" + (", peers " + ", ".join(f"{p} ({n} rows)" for p, n in peers.items())
                                            if peers else ", no other peers yet"))
    if db.exists():
        st = store_mod.merge_store(store, db, log=lambda m: None)
        msg = f"  2. merged: {st['new']} new, {st['enriched']} enriched"
        if adopt and (cfg.get("data_repo") or {}).get("adopt_external", True):
            msg += f", {adopt(store, cfg)} adopted into the archive (≥ min_score)"
        log(msg)
    import arxiv_source  # here, like catalog above
    s = store_mod.export_clean_share_db(store_path, db, secrets=secrets, skip_arxiv=arxiv_source.share_skip(cfg))
    if s["papers"] < before:
        _git(repo, "checkout", "--", DB_NAME, check=False)
        raise RuntimeError(f"export has {s['papers']} papers, fewer than the remote's {before}: nothing pushed")
    log(f"  3. exported: {s['papers']} papers, {s['abstracts']} abstracts, {s['digests']} digests, "
        f"{s['bytes'] / 1e6:.1f} MB")
    share = (cfg.get("paths") or {}).get("share_db")
    if push and share and Path(share).expanduser().resolve() != db.resolve():  # not from a --dry-run copy
        Path(share).expanduser().parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db, Path(share).expanduser())
    added, better = _gain(remote, _snapshot(db))
    if not (added or better):
        _git(repo, "checkout", "--", DB_NAME, check=False)  # keep the remote's file as it is
    ov_changed, ov_rows = False, 0
    if (cfg.get("data_repo") or {}).get("share_curation", True):
        ov_changed, ov_rows = write_overlay(store, cfg, repo, me, secrets)
        log(f"     overlay peers/{me}.json: {ov_rows} rows" + (" (changed)" if ov_changed else " (unchanged)"))
    marker_changed = _stamp_marker(repo, cfg)  # v3.0.4: the repo's domain_preset / radar_title for readers
    _git(repo, "add", "-A", "--", DB_NAME, MARKER, *([PEERS_DIR] if (repo / PEERS_DIR).exists() else []))
    if not _git(repo, "status", "--porcelain").stdout.strip():
        log("  4. nothing new for the remote: no commit")
        return True, s["papers"], peers
    what = [f"{s['papers']} papers, +{added} new, {better} enriched"] if (added or better) else []
    what += [f"{me}'s radar ({ov_rows} rows)"] if ov_changed else []
    what += ["repo domain metadata"] if marker_changed else []
    _git(repo, *_identity(repo, me), "commit", "-m", f"Sync shared corpus ({'; '.join(what)})")
    if not push:
        log("  4. committed locally (no push)")
        return True, s["papers"], peers
    r = _git(repo, "push", "origin", "HEAD:main", check=False)
    if r.returncode:
        log("  4. push rejected: the remote moved meanwhile")
        return False, s["papers"], peers
    log(f"  4. pushed: {'; '.join(what)}")
    return True, s["papers"], peers


def pull_only(store, cfg, adopt=None, log=print):
    """Read only (briefing.py --pull-data-repo, STARTUP.html's 📥 Read from Private Repo): steps 1 and 2 of a sync.
    Fetch + reset to origin/main, every other peer's overlay into peer_curation, the shared file merged into this
    store (+ adopt); then every data_repo.read_repos entry the same way (v3.0). Nothing is exported, written into
    a clone or pushed. Without a primary clone (and no remote_url) only the read repos are read. Returns
    {'papers', 'new', 'enriched', 'adopted', 'peers', 'read_repos'}; raises RuntimeError on any failure."""
    repo = ensure_clone(cfg, log)
    why = check_clone(repo, cfg)
    if why and (cfg.get("data_repo") or {}).get("read_repos"):
        me = peer_id(cfg, None)
        log(f"No primary data repo ({why}): reading data_repo.read_repos only")
        return {"papers": 0, "new": 0, "enriched": 0, "adopted": 0, "peers": {},
                "read_repos": pull_read_repos(store, cfg, me, adopt, log)}
    if why:
        raise RuntimeError(why)
    me = peer_id(cfg, repo)
    log(f"Shared corpus (read only): {repo} (this radar: {me})")
    _git(repo, "fetch", "origin")
    _git(repo, "reset", "--hard", "origin/main")
    db = repo / DB_NAME
    peers = import_peers(store, repo, me, log, source=primary_label(cfg))
    out = {"papers": _count(db), "new": 0, "enriched": 0, "adopted": 0, "peers": peers}
    log(f"  1. remote: {out['papers']} papers" + (", peers " + ", ".join(f"{p} ({n} rows)" for p, n in peers.items())
                                                  if peers else ", no other peers yet"))
    if db.exists():
        st = store_mod.merge_store(store, db, log=lambda m: None)
        out.update(new=st["new"], enriched=st["enriched"])
        msg = f"  2. merged: {st['new']} new, {st['enriched']} enriched"
        if adopt and (cfg.get("data_repo") or {}).get("adopt_external", True):
            out["adopted"] = adopt(store, cfg)
            msg += f", {out['adopted']} adopted into the archive (≥ min_score)"
        log(msg)
    out["read_repos"] = pull_read_repos(store, cfg, me, adopt, log)
    log("  read only: nothing exported or pushed (🔄 Full Sync / --sync-data-repo does that)")
    return out


pull = pull_only  # v2.21 name


def sync(store, store_path, cfg, adopt=None, secrets=(), push=True, log=print):
    """Steps 1–4 (see the module docstring); after a rejected push, a random PUSH_BACKOFF wait and a fresh
    round from step 1, up to PUSH_RETRIES times. The jitter keeps radars that collided from colliding again.
    Returns {'papers': n, 'peers': {peer_id: rows}}; raises RuntimeError on any failure."""
    repo = ensure_clone(cfg, log)
    why = check_clone(repo, cfg)
    if why:
        raise RuntimeError(why)
    me = peer_id(cfg, repo)
    log(f"Shared corpus: {repo} (this radar: {me})")
    attempts = 1 + PUSH_RETRIES
    for attempt in range(1, attempts + 1):
        done, n, peers = _round(store, store_path, cfg, repo, me, adopt, secrets, push, log)
        if done:  # then the repos shared with this radar for reading (v3.0), never pushed
            return {"papers": n, "peers": peers, "read_repos": pull_read_repos(store, cfg, me, adopt, log)}
        if attempt < attempts:
            wait = random.uniform(*PUSH_BACKOFF)
            log(f"  retry {attempt}/{PUSH_RETRIES} from step 1 in {wait:.1f} s")
            time.sleep(wait)
    raise RuntimeError(f"push rejected {attempts} times; run --sync-data-repo again later")
