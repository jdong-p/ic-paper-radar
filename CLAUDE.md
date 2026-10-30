# IC Paper Radar — Starter Edition

Instructions for an AI agent (Claude Code) opened in this folder:

- Read `README.md` first. To set up the user's research pillars, follow its "AI Setup Prompt" schema
  and rules, and edit **only** these keys of `config.json`: `pillars`, `positive_keywords`,
  `negative_keywords`, `negative_override`, `anchors`, `vip_authors`, `beyond_ieee.key1_themes`
  (and `contact_email` if the user gives one). Keep the file valid JSON.
- Then run `python briefing.py --rescore` and `python briefing.py --seed-pillars 5 --no-claude`
  (`python3` on macOS) and report how many papers each pillar got. If a pillar gets 0–1 papers,
  propose broader keywords; if one pillar dominates, lower its generic weights.
- Each pillar is kept at `catch_up.min_candidates_per_pillar` (10) unreviewed papers and refilled after
  every mark, `--sync` and daily run (README.md, "Catch-up"). If the user wants more now, run
  `python briefing.py --seed-pillars N` with N above 10. Keep `catch_up.not_a_paper` in `config.json`: it
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
- Reports and digests are written in English.
- If `paper_store.sqlite` is missing or empty, say so: the user can request the pre-built database from
  the author (README.md, Step 1) or build one with weekly runs and `--topic` dives.
