"""Shared corpus repo (v2.18; peer overlays v2.19): keep every collaborator's corpus identical with one command,
and let each one see the others' radars.

  python briefing.py --sync-data-repo      (also runs after every Friday finalize when the clone exists)

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
    """{doi: (filled objective fields + digest, cited_by, ieee_cites)} of a share file, for _gain()."""
    if not db.exists():
        return {}
    cols = [c for c in (*store_mod.OBJECTIVE, "digest")]
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        have = {r[1] for r in c.execute("PRAGMA table_info(papers)")}
        cols = [x for x in cols if x in have]
        out = {}
        for r in c.execute(f"SELECT doi, cited_by, ieee_cites, {', '.join(cols)} FROM papers"):
            out[str(r[0]).lower()] = ({k for k, v in zip(cols, r[3:]) if v not in (None, "", "[]")}, r[1] or 0, r[2] or 0)
        return out
    finally:
        c.close()


def _gain(remote, new):
    """What the new export gives the remote: (new DOIs, rows with more filled fields or higher citations).
    Only a real gain is pushed, so two radars whose files differ only in bytes don't trade commits forever."""
    added = sum(1 for d in new if d not in remote)
    better = sum(1 for d, (f, c1, c2) in new.items() if d in remote
                 and (f - remote[d][0] or c1 > remote[d][1] or c2 > remote[d][2]))
    return added, better


def check_clone(repo):
    """None if `repo` is a clone of the data repo, else the reason it isn't."""
    if not (repo / ".git").exists():
        return f"no clone at {repo}"
    origin = _git(repo, "remote", "get-url", "origin", check=False).stdout.strip()
    if REMOTE_MARK not in origin:
        return f"{repo} is not a clone of {REMOTE_MARK} (origin: {origin or 'none'})"
    return None


def import_peers(store, repo, me, log=print):
    """Every peers/<id>.json except this radar's own → peer_curation. Returns {peer_id: rows}."""
    out = {}
    for f in sorted((repo / PEERS_DIR).glob("*.json")):
        if f.stem == me or not store_mod.PEER_ID_RX.match(f.stem):
            continue
        try:
            out[f.stem] = store_mod.import_peer_overlay(store, json.loads(f.read_text(encoding="utf-8")), f.stem)
        except Exception as e:
            log(f"  peer overlay {f.name} skipped: {e}")
    return out


def write_overlay(store, cfg, repo, me, secrets=()):
    """This radar's overlay → peers/<me>.json. Rewritten only when its content changed ('updated' is the time of
    that change), and refused if any text holds a local path or a secret. Returns (changed, rows)."""
    import arxiv_source, catalog  # here: catalog imports modules that import this one
    dr = cfg.get("data_repo") or {}
    kwmap = catalog._kw_pillars(cfg)
    ov = store_mod.peer_overlay(store, me, [catalog.PILLARS[k] for k in sorted(catalog.PILLARS) if k],
                                lambda p: catalog.pillar_of(p, kwmap), share_notes=dr.get("share_notes", True),
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
    peers = import_peers(store, repo, me, log)
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
    _git(repo, "add", "-A", "--", DB_NAME, *([PEERS_DIR] if (repo / PEERS_DIR).exists() else []))
    if not _git(repo, "status", "--porcelain").stdout.strip():
        log("  4. nothing new for the remote: no commit")
        return True, s["papers"], peers
    what = [f"{s['papers']} papers, +{added} new, {better} enriched"] if (added or better) else []
    what += [f"{me}'s radar ({ov_rows} rows)"] if ov_changed else []
    _git(repo, "commit", "-m", f"Sync shared corpus ({'; '.join(what)})")
    if not push:
        log("  4. committed locally (no push)")
        return True, s["papers"], peers
    r = _git(repo, "push", "origin", "HEAD:main", check=False)
    if r.returncode:
        log("  4. push rejected: the remote moved meanwhile")
        return False, s["papers"], peers
    log(f"  4. pushed: {'; '.join(what)}")
    return True, s["papers"], peers


def sync(store, store_path, cfg, adopt=None, secrets=(), push=True, log=print):
    """Steps 1–4 (see the module docstring); after a rejected push, a random PUSH_BACKOFF wait and a fresh
    round from step 1, up to PUSH_RETRIES times. The jitter keeps radars that collided from colliding again.
    Returns {'papers': n, 'peers': {peer_id: rows}}; raises RuntimeError on any failure."""
    repo = repo_dir(cfg)
    why = check_clone(repo)
    if why:
        raise RuntimeError(why)
    me = peer_id(cfg, repo)
    log(f"Shared corpus: {repo} (this radar: {me})")
    attempts = 1 + PUSH_RETRIES
    for attempt in range(1, attempts + 1):
        done, n, peers = _round(store, store_path, cfg, repo, me, adopt, secrets, push, log)
        if done:
            return {"papers": n, "peers": peers}
        if attempt < attempts:
            wait = random.uniform(*PUSH_BACKOFF)
            log(f"  retry {attempt}/{PUSH_RETRIES} from step 1 in {wait:.1f} s")
            time.sleep(wait)
    raise RuntimeError(f"push rejected {attempts} times; run --sync-data-repo again later")
