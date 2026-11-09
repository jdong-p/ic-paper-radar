"""Shared corpus repo (v2.18): keep every collaborator's corpus identical with one command.

  python briefing.py --sync-data-repo      (also runs after every Friday finalize when the clone exists)

The repo (a private Git repo named ic-paper-radar-data) holds one file, paper_store_clean_share.sqlite.
Git can't merge a binary file, so nobody ever merges it in Git:
  1. git fetch origin + git reset --hard origin/main: take the remote file exactly as it is
  2. store.merge_store(): union it into this radar's own store (new DOIs as 'external', marks and notes
     here untouched), then adopt the external papers that score ≥ min_score (data_repo.adopt_external)
  3. store.export_clean_share_db(): write this store, cleaned, back over the repo file (every row,
     'external' ones included), and copy it to paths.share_db when that is set
  4. git commit + git push only if the export gives the remote something it lacks (new DOIs, objective
     fields it has empty, higher citation counts); otherwise the remote file is restored, so two radars
     whose exports differ only in bytes never trade commits. A rejected push (someone pushed meanwhile)
     goes back to step 1 once more
A reset can't lose anything: the remote's papers come in at step 2, this radar's own are in its store and
go out at step 3. After both collaborators have run it, both stores hold the same union of DOIs.
"""
import shutil
import sqlite3
import subprocess
from pathlib import Path

from env_guard import ensure_minisforum_env

ensure_minisforum_env()

import store as store_mod

HERE = Path(__file__).resolve().parent
DB_NAME = "paper_store_clean_share.sqlite"
REMOTE_MARK = "ic-paper-radar-data"  # origin must contain this before anything is reset


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


def _round(store, store_path, cfg, repo, adopt, secrets, push, log):
    db = repo / DB_NAME
    _git(repo, "fetch", "origin")
    _git(repo, "reset", "--hard", "origin/main")
    before, remote = _count(db), _snapshot(db)
    log(f"  1. remote: {before} papers")
    if db.exists():
        st = store_mod.merge_store(store, db, log=lambda m: None)
        msg = f"  2. merged: {st['new']} new, {st['enriched']} enriched"
        if adopt and (cfg.get("data_repo") or {}).get("adopt_external", True):
            msg += f", {adopt(store, cfg)} adopted into the archive (≥ min_score)"
        log(msg)
    s = store_mod.export_clean_share_db(store_path, db, secrets=secrets)
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
    if not (added or better) or not _git(repo, "status", "--porcelain").stdout.strip():
        _git(repo, "checkout", "--", DB_NAME, check=False)  # keep the remote's file as it is
        log("  4. nothing new for the remote: no commit")
        return True, s["papers"]
    _git(repo, "add", DB_NAME)
    _git(repo, "commit", "-m", f"Sync shared corpus ({s['papers']} papers, +{added} new, {better} enriched)")
    if not push:
        log("  4. committed locally (no push)")
        return True, s["papers"]
    r = _git(repo, "push", "origin", "HEAD:main", check=False)
    if r.returncode:
        log("  4. push rejected: the remote moved meanwhile")
        return False, s["papers"]
    log(f"  4. pushed: {s['papers']} papers (+{s['papers'] - before})")
    return True, s["papers"]


def sync(store, store_path, cfg, adopt=None, secrets=(), push=True, log=print):
    """Steps 1–4 (see the module docstring), with one retry from step 1 after a rejected push.
    Returns the paper count of the shared file; raises RuntimeError on any failure."""
    repo = repo_dir(cfg)
    why = check_clone(repo)
    if why:
        raise RuntimeError(why)
    log(f"Shared corpus: {repo}")
    for attempt in (1, 2):
        done, n = _round(store, store_path, cfg, repo, adopt, secrets, push, log)
        if done:
            return n
        if attempt == 1:
            log("  retrying once from step 1")
    raise RuntimeError("push rejected twice; run --sync-data-repo again later")
