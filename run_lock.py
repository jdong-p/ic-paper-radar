"""One radar run at a time on this computer (v2.21.1): a lock file shared by briefing.py and the Control Center.

Every briefing.py run that writes (all but --gui and a --recall-only search) takes .run.lock next to the
scripts, so the scheduled tasks (07:00 daily run, Friday 12:30 sync), a run from a terminal and the Control
Center's buttons never work on the SQLite store or the data-repo clone at the same time. While it holds the
lock, the run also copies its output to .run.log, so STARTUP.html can show a run it didn't start.

  - A second run waits for the lock (a [BUSY] line, then a check every 5 s) up to WAIT_S (30 min), so a
    scheduled task that meets a GUI job runs after it instead of failing; then it gives up with exit 75.
  - The Control Center doesn't wait: POST /api/run answers "already_running" and the page streams .run.log.
  - The lock holds {pid, args, started, host}. A lock whose process is gone, or older than STALE_S (12 h),
    is stale and taken over, so a crashed or killed run never blocks the radar.
Both files are gitignored.
"""
import atexit
import json
import os
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = HERE / ".run.lock"
LOG = HERE / ".run.log"
WAIT_S = 30 * 60
POLL_S = 5
STALE_S = 12 * 3600
EXIT_BUSY = 75  # EX_TEMPFAIL: the wrappers log it as the run's exit code


def _alive(pid):
    if pid <= 0:
        return False
    if sys.platform == "win32":  # never os.kill(pid, 0) here: on Windows it terminates the process
        import ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # access denied: it exists (another user / elevated)
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read():
    try:
        text = LOCK.read_text(encoding="utf-8")
        age = time.time() - LOCK.stat().st_mtime
    except FileNotFoundError:
        return None, None, 0
    try:
        return json.loads(text), text, age
    except ValueError:
        return {}, text, age


def holder():
    """The live run holding the lock ({pid, args, started, host}), else None. A stale lock is removed."""
    info, text, age = _read()
    if info is None:
        return None
    pid = int(info.get("pid") or 0) if isinstance(info, dict) else 0
    if (pid and age < STALE_S and _alive(pid)) or (not info and age < 10):  # empty = being written right now
        return info or {"pid": 0, "args": [], "started": ""}
    if _read()[1] == text:  # still the same stale lock (not one a new run just wrote)
        try:
            LOCK.unlink()
        except FileNotFoundError:
            pass
    return None


def describe(h):
    if not h:
        return ""
    args = " ".join(h.get("args") or []) or "(daily run)"
    since = str(h.get("started") or "")[11:16]
    return f"briefing.py {args}" + (f" since {since}" if since else "") + (f" (pid {h['pid']})" if h.get("pid") else "")


def release():
    info, _, _ = _read()
    if isinstance(info, dict) and info.get("pid") == os.getpid():
        try:
            LOCK.unlink()
        except FileNotFoundError:
            pass


def acquire(args, wait=WAIT_S, log=None):
    """Take the lock (waiting up to `wait` s for another run). None when taken (released at exit), else the
    holder's info when it is still busy after `wait`."""
    log = log or (lambda m: print(m, file=sys.stderr, flush=True))
    deadline, said = time.time() + wait, False
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            h = holder()
            if h is None:
                continue  # stale lock removed: try again at once
            if time.time() >= deadline:
                return h
            if not said:
                log(f"[BUSY] another radar run is in progress: {describe(h)}. Waiting for it (up to {wait // 60} min) ...")
                said = True
            time.sleep(POLL_S)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "args": list(args), "host": socket.gethostname(),
                       "started": datetime.now().isoformat(timespec="seconds")}, fh)
        atexit.register(release)
        if said:
            log("[BUSY] the other run finished: starting now.")
        return None


class _Tee:
    """sys.stdout / sys.stderr that also go to .run.log (the stream may be None under pythonw)."""

    def __init__(self, stream, fh):
        self.stream, self.fh = stream, fh

    def write(self, s):
        if self.stream is not None:
            self.stream.write(s)
        try:
            self.fh.write(s)
            self.fh.flush()
        except (OSError, ValueError):
            pass
        return len(s)

    def flush(self):
        if self.stream is not None:
            self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def tee_output():
    """Copy this run's output to .run.log (rewritten at each run) for the Control Center's console."""
    try:
        fh = open(LOG, "w", encoding="utf-8", errors="replace")
    except OSError:
        return
    sys.stdout, sys.stderr = _Tee(sys.stdout, fh), _Tee(sys.stderr, fh)


def read_log(since=0, finished=False, limit=256_000):
    """(lines, next offset) of .run.log from byte `since`; only whole lines while the run is still writing."""
    try:
        size = LOG.stat().st_size
        if since > size:  # a new run rewrote the file
            since = 0
        with open(LOG, "rb") as f:
            f.seek(since)
            data = f.read(limit)
    except (FileNotFoundError, OSError):
        return [], since
    cut = len(data) if finished else data.rfind(b"\n") + 1
    return data[:cut].decode("utf-8", "replace").splitlines(), since + cut
