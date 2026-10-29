# IC Paper Radar — Starter Edition

Instructions for an AI agent (Claude Code) opened in this folder:

- Read `README.md` first. To set up the user's research pillars, follow its "AI Setup Prompt" schema
  and rules, and edit **only** these keys of `config.json`: `pillars`, `positive_keywords`,
  `negative_keywords`, `negative_override`, `anchors`, `vip_authors`, `beyond_ieee.key1_themes`
  (and `contact_email` if the user gives one). Keep the file valid JSON.
- Then run `python briefing.py --rescore` and `python briefing.py --seed-pillars 5 --no-claude`
  (`python3` on macOS) and report how many papers each pillar got. If a pillar gets 0–1 papers,
  propose broader keywords; if one pillar dominates, lower its generic weights.
- If the user wants more papers in a pillar now, run `python briefing.py --seed-pillars N` with a larger N
  (README.md, "Catch-up"). Keep `catch_up.not_a_paper` in `config.json`: it skips tutorials and forums.
- Don't edit the `*.py` files unless the user asks. Never put API keys in `config.json`; the IEEE key
  goes in the `IEEE_API_KEY` environment variable.
- Reports and digests are written in English.
- If `paper_store.sqlite` is missing or empty, say so: the user can request the pre-built database from
  the author (README.md, Step 1) or build one with weekly runs and `--topic` dives.
