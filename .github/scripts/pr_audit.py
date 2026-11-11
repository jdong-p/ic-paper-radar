"""PR audit for the IC Paper Radar starter template, run by .github/workflows/pr_audit.yml on every pull
request into main (a required status check in the main ruleset).

    python -I pr_audit.py <pull request checkout> <base sha>

It never imports or runs code from the pull request: files are only compiled (py_compile), parsed (json)
and read. Checks:
  1. every tracked *.py file compiles;
  2. config.example.json (the starter template) is valid JSON and every personal setting still ships blank
     (pillars, keywords, peer_id, data_repo_dir, ...), so nobody's own config lands in the template;
  3. no config.json / config.local.json (each user's own, git-ignored), database, secret, log, output or
     overlay file is added or changed, and no file is over 1 MB;
  4. no added line holds a personal path, a private IP address, an e-mail address or a key-like string;
  5. nothing under .github/ changes (the maintainer merges those with the admin bypass).
Prints ::error annotations and a summary; exits 1 when anything fails.
"""
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SELF = ".github/scripts/pr_audit.py"
TEMPLATE = "config.example.json"  # the tracked starter settings; config.json is each user's own (git-ignored)
MAX_BYTES = 1_000_000
WINDOW, OVERLAP = 1000, 200  # line scan in overlapping windows (longest pattern is far below OVERLAP)

# Starter settings that must stay exactly like this in config.example.json (key path -> required value).
BLANK = {
    ("pillars",): [],
    ("pillar_short",): [],
    ("positive_keywords",): {},
    ("negative_keywords",): [],
    ("negative_override",): "",
    ("anchors",): [],
    ("vip_authors",): [],
    ("contact_email",): "",
    ("host_lock",): "",
    ("portable_mode",): True,
    ("beyond_ieee", "key1_themes"): [],
    ("data_repo", "peer_id"): "",
    ("paths", "data_repo_dir"): "",
    ("vpn", "campus_networks"): [],
    ("vpn", "campus_route_host"): "",
    ("vpn", "campus_dns"): [],
    ("sync_server", "hosts"): [],
}
# Blank when present (not shipped today, but a natural place for a personal value).
BLANK_IF_PRESENT = {("data_repo", "data_repo_dir"): ""}

FORBIDDEN_FILE = re.compile(r"""(^|/)(
      config(\.local)?\.json$
    | [^/]*\.(sqlite[^/]*|db|db-journal|db-wal|db-shm|key|pem|p12|pfx|log)$
    | \.env(\.[^/]*)?$
    | \.radar_token$
    | id_(rsa|ecdsa|ed25519)[^/]*$
    | curation_marks[^/]*\.json$
    | pending_pdf_queue\.json$
    | output/
    | peers/
)""", re.X | re.I)

PLACEHOLDER = r"(?:you|your-?name|username|user|name|me|runner|public|default)\b"
LINE_RULES = [
    ("personal path", re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+(?!" + PLACEHOLDER + r")[A-Za-z0-9._-]+", re.I)),
    ("personal path", re.compile(r"(?<![\w.])/(?:home|Users)/(?!" + PLACEHOLDER + r")[A-Za-z0-9._-]+/")),
    ("private IP address", re.compile(
        r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))"
        r"\.\d{1,3}\.\d{1,3}\b")),
    ("API key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("API key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}")),
    ("AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("private key", re.compile("-----BEGIN [A-Z ]*" + "PRIVATE KEY-----")),
    ("secret value", re.compile(
        r"\b[A-Z0-9_]*(?:API_?KEY|TOKEN|SECRET|PASSWORD)\b[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}", re.I)),
]
EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
EMAIL_OK = re.compile(r"^(?:noreply|no-reply|git)@|@users\.noreply\.github\.com$|@example\.(?:com|org|net)$", re.I)

errors = []


def fail(check, msg, path=None, line=None):
    errors.append((check, msg, path, line))
    where = f" file={path}" + (f",line={line}" if line else "") if path else ""
    print(f"::error{where}::{check}: {msg}")


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def mask(s):
    return s if len(s) <= 8 else s[:4] + "…"


def check_compile(repo):
    files = [f for f in git(repo, "ls-files", "-z", "--", "*.py").split("\0") if f]
    with tempfile.TemporaryDirectory() as tmp:
        for i, f in enumerate(files):
            try:
                py_compile.compile(str(repo / f), cfile=os.path.join(tmp, f"{i}.pyc"), doraise=True)
            except py_compile.PyCompileError as e:
                fail("py_compile", (e.msg.strip().splitlines() or ["does not compile"])[-1], f)
    return len(files)


def check_config(repo):
    name = TEMPLATE
    try:
        cfg = json.loads((repo / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fail(name, "missing: the starter template must stay in the repo")
    except ValueError as e:
        return fail(name, f"not valid JSON ({e})", name)

    def get(keys):
        node = cfg
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return KeyError
            node = node[k]
        return node

    for keys, want in {**BLANK, **BLANK_IF_PRESENT}.items():
        got = get(keys)
        if got is KeyError and keys in BLANK_IF_PRESENT:
            continue
        if got is KeyError or got != want or type(got) is not type(want):
            shown = "missing" if got is KeyError else mask(json.dumps(got, ensure_ascii=False))
            fail(name, f"{'.'.join(keys)} must be {json.dumps(want)} in the starter template, found {shown}. "
                       "Your own settings belong in config.json, which Git ignores", name)


def changed_files(repo, base):
    out = git(repo, "diff", "--name-only", "-z", "--no-renames", "--diff-filter=d", f"{base}...HEAD")
    return [f for f in out.split("\0") if f]


def check_files(repo, files):
    for f in files:
        if f.startswith(".github/"):
            fail(".github", "changes to workflows or this audit need the maintainer (admin bypass merge)", f)
        if FORBIDDEN_FILE.search(f):
            fail("forbidden file", "config.json, databases, secrets, logs, output/ and peers/ never go into this repo", f)
        p = repo / f
        if p.is_file() and p.stat().st_size > MAX_BYTES:
            fail("file size", f"{p.stat().st_size:,} bytes (limit {MAX_BYTES:,})", f)


def check_lines(repo, base):
    diff = git(repo, "diff", "-U0", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames",
               f"{base}...HEAD")
    path, n, scanned, header = None, 0, 0, False
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            path, header = None, True
            continue
        if header:
            if raw.startswith("+++ "):
                path = raw[6:] if raw.startswith("+++ b/") else None
            m = re.match(r"@@ -\S+ \+(\d+)", raw)
            if m:
                n, header = int(m.group(1)), False
            continue
        m = re.match(r"@@ -\S+ \+(\d+)", raw)
        if m:
            n = int(m.group(1))
            continue
        if not raw.startswith("+") or path is None:
            continue
        line, n = raw[1:], n + 1
        if path == SELF:
            continue
        scanned += 1
        seen = set()
        # Overlapping windows keep the regexes linear on huge one-line files (minified or generated content).
        for start in range(0, max(len(line), 1), WINDOW - OVERLAP):
            seg = line[start:start + WINDOW]
            for name, rx in LINE_RULES + [("e-mail address", EMAIL)]:
                for hit in rx.finditer(seg):
                    key = (name, start + hit.start())
                    if key in seen or (rx is EMAIL and EMAIL_OK.search(hit.group(0))):
                        continue
                    seen.add(key)
                    fail(name, f"'{mask(hit.group(0))}' in an added line", path, n - 1)
            if start + WINDOW >= len(line):
                break
    return scanned


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # -I ignores PYTHONIOENCODING
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    repo, base = Path(sys.argv[1]).resolve(), sys.argv[2]
    n_py = check_compile(repo)
    check_config(repo)
    files = changed_files(repo, base)
    check_files(repo, files)
    n_lines = check_lines(repo, base)

    summary = [f"## PR audit: {'❌ ' + str(len(errors)) + ' problem(s)' if errors else '✅ passed'}", "",
               f"{n_py} Python files compiled, {TEMPLATE} checked, {len(files)} changed files, "
               f"{n_lines} added lines scanned.", ""]
    if errors:
        summary += ["| Check | File | Problem |", "|---|---|---|"]
        summary += [f"| {c} | {p or ''}{':' + str(l) if l else ''} | {m.replace('|', '/')} |"
                    for c, m, p, l in errors]
    text = "\n".join(summary)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
