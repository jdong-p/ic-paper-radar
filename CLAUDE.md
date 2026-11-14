# Engineer Paper Radar (formerly IC Paper Radar) — Starter Edition

Instructions for an AI agent (Claude Code) opened in this folder:

- Read `README.md` first. To set up the user's research pillars, follow its "AI Setup Prompt" schema
  and rules, and edit **only** these keys of `config.json`: `pillars`, `pillar_short` (optional 1–2 word labels, same order), `positive_keywords`,
  `negative_keywords`, `negative_override`, `anchors`, `vip_authors`, `beyond_ieee.key1_themes`
  (and `contact_email` if the user gives one). Keep the file valid JSON.
- `config.json` is the user's own file and Git ignores it. Any command creates it from the tracked template
  `config.example.json` when missing (or `cp config.example.json config.json`). The scripts lay it over the
  template, so keys it lacks take the template's defaults. Put the user's settings only in `config.json`;
  never write them into `config.example.json`, which must stay the blank starter template.
- If `git pull` stops with "Your local changes to the following files would be overwritten: config.json",
  or reports a conflict on `config.json`, the clone predates the template (README.md, "Updating"). Follow
  that one-time recipe: back the file up to `config.local.json` **first**. Never run `git checkout`,
  `git restore`, `git reset --hard` or `git stash drop` on `config.json` before that backup exists: it
  holds the user's pillars and keywords. A `modify/delete` conflict on `config.json` (after a merge or a
  `git stash pop`) leaves the user's file in the folder: `git rm --cached config.json` keeps it and resolves
  the conflict (then `git commit --no-edit` for a merge).
- After configuring, run `python briefing.py --rescore` and `python briefing.py --seed-pillars 5 --no-claude`
  (`python3` on macOS) and report how many papers each pillar got. If a pillar gets 0–1 papers,
  propose broader keywords; if one pillar dominates, lower its generic weights.
- Each pillar is kept at `catch_up.min_candidates_per_pillar` (10) unreviewed papers and refilled after
  every mark, `--sync` and daily run (README.md, "Catch-up"). If the user wants more now, run
  `python briefing.py --seed-pillars N` with N above 10. Keep `catch_up.not_a_paper` in the config: it
  skips tutorials and forums.
- Marks and 🏷️ Tech notes typed in `output/DASHBOARD.html` reach the database only after the user clicks
  💾 Save Marks and runs `python briefing.py --sync` (README.md, "Curation"). To set a note yourself, put it
  in `curation_marks.json` under `"notes": {"<doi>": "<text>"}` and run `--sync`; don't write to the
  database directly.
- To give the database to someone, run `python briefing.py --export-share` (README.md, "Sharing your
  corpus"); never send `paper_store.sqlite` itself, which holds the user's marks and notes. Use
  `--include-curation` only when the user says the other person should see them. To bring in someone
  else's store, use `--merge-store OTHER.sqlite` (never copy it over `paper_store.sqlite`).
- Don't edit the `*.py` files unless the user asks. Never put API keys in `config.json`; the IEEE key
  goes in the `IEEE_API_KEY` environment variable.
- Code changes to this repo go through a pull request: `main` on GitHub is protected and rejects direct
  pushes (README.md, "Contributing"). Work on a new branch, push it, and open a PR with
  `gh pr create --base main`; never push to `main` or force-push. Commit and push only when the user asks.
  The shared corpus repo used by `--sync-data-repo` is separate and unaffected.
- The required **PR audit** check fails a PR that fills a personal setting in `config.example.json`
  (pillars, keywords, `peer_id`, `data_repo_dir`, ...), adds `config.json`, `config.local.json`, a
  `.sqlite`/`.db`/`.env`/log file, `output/` or `peers/`, a personal path, IP, e-mail or key, or touches
  `.github/`. Never `git add -f` an ignored file; commit only the files the change needs. A change that
  needs a new setting adds it to `config.example.json` with a blank or neutral default. Don't edit
  `.github/` to make the audit pass.
- A user without an AI agent or a terminal can use the Setup & Control Center instead: `Start_Radar_GUI.cmd` /
  `.command` or `python briefing.py --gui` (control_center.py, `output/STARTUP.html`). It edits the same
  `config.json` keys listed above (plus `data_repo` sharing and `arxiv`), writing only the changed ones.
  It reports secrets as yes/no flags only. Keep the `--gui` server on 127.0.0.1, behind its per-launch key.
- Data repos (v3.0): a user owns their own private data repo. Create it with
  `python briefing.py --init-data-repo <owner/name>` (needs `gh` signed in, or an empty private repo made on
  github.com). Repos shared with them for reading go in `data_repo.read_repos`; `--pull-data-repo` reads them
  and never pushes. Keep `data_repo.remote_url` and `read_repos` blank in `config.example.json` (the PR audit
  checks); they belong in the user's `config.json`. Never put a token in a repo URL.
- `domain_preset` (`ic_ece`, `bio_med`, `chem_mat`, `general_eng`; `presets.py`) sets the evidence badge and
  can load starter venues; PubMed / bioRxiv venues use `"source": "pubmed" | "biorxiv" | "medrxiv"`.
- `CITATION.cff` is the citation metadata (keep `version` in step with releases). New domains go in
  `presets.py`; new sources in `fetcher.SOURCES` (README, "Call for Co-Maintainers").
- Reports and digests are written in English.
- If `paper_store.sqlite` is missing or empty, say so: the user can request the pre-built database from
  the author (README.md, Step 1) or build one with weekly runs and `--topic` dives.
