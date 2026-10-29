# IC Paper Radar

**A free, local radar for new integrated-circuit papers, tuned to your own research.**
**一个免费、在本地运行、按你自己的研究方向定制的 IC 论文雷达。**

IC Paper Radar follows the IEEE solid-state-circuits venues (JSSC, ISSCC, VLSI, CICC, ESSERC, TCAS-I/II,
SSC-L, TBioCAS, Sensors Letters) and, optionally, Nature / Science. It scores every paper against
**your research pillars**, writes a weekly report, and builds an interactive dashboard.

IC Paper Radar 跟踪 IEEE 固态电路领域的主要会议和期刊（JSSC、ISSCC、VLSI、CICC、ESSERC、TCAS-I/II、SSC-L、
TBioCAS、Sensors Letters），并可选跟踪 Nature / Science。它按照**你的研究方向（pillars）**给每篇论文打分，
生成每周报告，并输出一个可交互的面板。

## Features / 功能

- **Zero dependencies / 零依赖:** Python **3.11+** standard library only. No `pip install`.
  只需 Python 3.11+ 标准库，无需 `pip install`。
- **Runs anywhere / 跨平台:** Windows, macOS and Linux. Everything is written to `./output`.
- **Interactive `output/DASHBOARD.html` / 交互式面板:** filter by pillar, search titles, authors and
  numbers (`nW`, `ENOB`, `fs`), read abstracts and digests, and click ✅ Select / ⭐ Cite / 🗄️ Archive.
  按 pillar 筛选，搜索标题、作者和数字，查看摘要，并标记 ✅ 选中 / ⭐ 引用 / 🗄️ 归档。
- **BibTeX export / 自动导出 BibTeX:** `output/cite.bib` (⭐ papers, for Overleaf) and
  `output/selected_pool.bib` (✅ + ⭐), rewritten on every run and downloadable from the dashboard.
- **Weekly reports / 每周报告:** `output/Weekly_Briefings/<YYYY-Www>.md` with a ranked table, a citation
  map and (optionally) an AI synthesis.
- **Lineage tracking / 会议→期刊演进:** links a journal paper to the ISSCC / VLSI / CICC / ESSERC paper it
  extends (📈), so you can see what the journal version adds.
- **Topic deep-dives / 专题综述:** `python briefing.py --topic "..."` collects the classics (by
  citations) and recent work on any topic.
- **Silicon vs. simulation / 流片验证标记:** measured-silicon papers get a ✅ badge and a small bonus;
  simulation-only papers are flagged ⚠️.
- **Free data sources / 免费数据源:** Crossref and OpenAlex (no key). A free IEEE API key and the
  Claude Code CLI are optional extras.
  使用 Crossref 和 OpenAlex（无需 key）；免费 IEEE API key 和 Claude Code CLI 为可选项。

> On macOS use `python3` wherever this README says `python`. On Windows, `python` or `py` both work.
> macOS 上请把本文中的 `python` 换成 `python3`；Windows 上 `python` 或 `py` 均可。

---

## Step 1 — Get the base paper database / 第一步：获取论文数据库

The radar keeps every paper it has seen in `paper_store.sqlite` (in the project folder). The repository
does **not** include this file.
雷达把见过的所有论文存放在项目目录下的 `paper_store.sqlite` 中。本仓库**不包含**该文件。

### Option A — Request the pre-built database (recommended, instant start) / 方式 A：索取预建数据库（推荐）

**[Open a GitHub Issue](../../issues/new?title=Database%20request)** in this repository titled
"Database request" (say briefly who you are, e.g. your university), and the author will send you the
pre-built `paper_store.sqlite` privately. Drop it into the project folder (next to `briefing.py`).
在本仓库 **[新建一个 GitHub Issue](../../issues/new?title=Database%20request)**，标题为 "Database request"
（简单说明你的身份，例如所在学校），作者会私下发送预建的 `paper_store.sqlite`。把它放到项目根目录（与
`briefing.py` 同一目录）即可。

> Please don't post your e-mail address in the issue (issues are public); the author will reply there
> with a way to send the file.
> 请不要在 Issue 中公开填写邮箱（Issue 是公开的）；作者会在 Issue 中回复传输方式。

It holds **2,500+ IC papers**, mostly published 2024 – 2026, about 90 % with abstracts:
TCAS-I (524), IEEE Sensors Letters (462), JSSC (447), ISSCC (359), TCAS-II (301), VLSI (262), CICC (179),
SSC-L (29), ESSERC and a few Nature / Science papers, with reference lists, citation counts and
conference ↔ journal links. About 50 papers carry a cached AI digest. All personal curation has been
reset, so your own pillars decide everything.
其中包含 2,500+ 篇 IC 论文（主要为 2024–2026 年，约 90 % 含摘要），附参考文献、被引次数和会议↔期刊关联；
约 50 篇带有缓存的 AI 摘要。所有个人标记均已清除，完全由你自己的 pillars 决定排序。

> The database is shared privately for personal study. Please don't republish it.
> 数据库仅供个人学习使用，请勿二次发布。

### Option B — Build your own from scratch / 方式 B：从零开始建库

Just run the radar (Step 3). It creates an empty `paper_store.sqlite` and fills it:
直接运行（第三步），程序会自动创建空的 `paper_store.sqlite` 并逐步填充：

- every weekly run adds the last 7 days of papers from all venues (Crossref + OpenAlex, free);
  每次运行会抓取所有期刊/会议最近 7 天的新论文；
- every `--topic` dive adds the relevant classics and recent papers on that topic (OpenAlex);
  每次 `--topic` 专题会加入该主题的经典与近期论文；
- with a free `IEEE_API_KEY`, each run also back-fills older months (≈ 50 calls/day), so the store
  reaches 2024 within a few weeks.
  设置免费 `IEEE_API_KEY` 后，每次运行还会回填历史论文（约 50 次调用/天），几周内即可覆盖 2024 年以来的论文。

Until the store has papers, the terminal and the dashboard show a `[TIP]` about these two options.
在数据库为空时，终端和面板会显示 `[TIP]` 提示上述两种方式。

---

## Step 2 — Configure your research pillars with AI (required) / 第二步：用 AI 配置研究方向（必需）

A **pillar** is one research direction, e.g. "Noise-shaping SAR ADCs". Each pillar owns a group of
weighted keywords; a paper's score is the sum of the weights it hits. The `pillars`,
`positive_keywords`, `negative_keywords`, `anchors` and `vip_authors` in `config.json` are
**intentionally empty**: until you fill them, `python briefing.py` stops with a `[SETUP REQUIRED]`
message (only `--topic` and `--recall` work without pillars).

**pillar** 指一个研究方向（如 "Noise-shaping SAR ADCs"）。每个 pillar 拥有一组带权重的关键词，论文得分 =
命中关键词的权重之和。`config.json` 中的 `pillars`、`positive_keywords`、`negative_keywords`、`anchors`、
`vip_authors` **特意留空**；填写之前运行 `python briefing.py` 会提示 `[SETUP REQUIRED]` 并停止（只有 `--topic`
和 `--recall` 不需要 pillars）。

### With Claude Code (in this folder) / 使用 Claude Code（在本目录中）

```bash
cd ic-paper-radar
claude
```

Then type (replace the brackets) / 然后输入（替换方括号内容）:

> Read README.md and configure `config.json` for my research: [your IC topics, e.g. "noise-shaping SAR
> ADCs and ADPLLs for IoT radios"], then run `--rescore` and `--seed-pillars 5`.

### With Web Claude / ChatGPT / Gemini / 使用网页版 Claude / ChatGPT / Gemini

1. Copy the **AI Setup Prompt** below into the chat.
   复制下面的 **AI Setup Prompt** 到对话框。
2. Under it, describe your research, then paste the **whole current `config.json`**.
   在其后描述你的研究方向，并粘贴**完整的当前 `config.json`**。
3. Replace your `config.json` with the file the AI returns, and check it's valid JSON
   (e.g. <https://jsonlint.com>).
   用 AI 返回的文件替换 `config.json`，并确认它是合法 JSON。

#### AI Setup Prompt (copy the whole block / 复制整个代码块)

```text
You are configuring "IC Paper Radar", a local tool that scores new IEEE solid-state-circuits papers
(JSSC, ISSCC, VLSI, CICC, ESSERC, TCAS-I/II, SSC-L, TBioCAS, Sensors Letters) against a PhD student's
research pillars. Below my research description I paste my current config.json. Return the COMPLETE
config.json with ONLY the keys listed in SCHEMA filled in; keep every other key and value exactly as
it is. Output valid JSON only (no comments, no prose, no Markdown fences).

SCHEMA
"pillars": ["<Pillar 1 name>", "<Pillar 2 name>", ...]
    2-4 short names, most important first.
"positive_keywords": {
    "_pillar1_<slug>": 0,          group heading: weight 0, N = position in "pillars" (1..4)
    "<keyword>": <weight>, ...,    keywords of pillar 1
    "_pillar2_<slug>": 0,
    "<keyword>": <weight>, ...     keywords of pillar 2, and so on up to _pillar4_
}
"negative_keywords": ["<off-topic term>", ...]          10-25 terms
"negative_override": "<regex>" or ""                    title regex that protects on-topic papers
"anchors": ["10.1109/JSSC.YYYY.NNNNNNN", ...]           0-20 DOIs of landmark papers
"vip_authors": ["<First Last>", ...]                    5-25 leading researchers in these pillars
"beyond_ieee": {..., "key1_themes": [...]}              0-20 application themes; keep the other beyond_ieee keys
"contact_email": "<e-mail>" or ""                       only if I give one

RULES FOR positive_keywords
- Every keyword belongs to the _pillarN_ heading above it. 15-40 keywords per pillar.
- Weights: 5-6 = a defining term that alone makes a paper relevant ("noise-shaping SAR", "ADPLL",
  "compute-in-memory"); 3-4 = a strong architecture / technique term ("redundant DAC", "DTC",
  "time-interleaved"); 1-2 = a generic term that only helps in combination ("calibration", "low power").
  A paper is shown when its total reaches 5 (min_score).
- Matching is whole-word and case-insensitive; a space and a hyphen are interchangeable and plural
  -s/-es is automatic, so list each concept once ("SAR ADC" also matches "SAR-ADCs").
- ALL-CAPS keys are case-sensitive acronyms ("ADPLL", "LDO", "TDC", "CIM"). Avoid acronyms that are
  common words or ambiguous across fields (e.g. "SOC").
- Regex keys for units and patterns: "re:<label>::<python regex>", e.g.
  "re:fs-jitter::\\d+(\\.\\d+)?\\s?fs\\b": 3 or "re:sub-µW::(?i)\\bsub-?(µ|u)W\\b": 4.
  Escape backslashes for JSON.
- Never repeat a keyword in two pillars. Don't use words every circuits paper contains ("circuit",
  "CMOS", "design", "chip", "measured"). Silicon (+1) / simulation-only (-4) is scored automatically.

RULES FOR THE OTHER KEYS
- negative_keywords: neighbouring fields that are NOT wanted (for an ADC student e.g. "power amplifier",
  "phased array", "GaN", "LiDAR"). A negative keyword zeroes a paper with no positive hit and costs -5
  otherwise.
- negative_override: a case-insensitive Python regex such as "(?i)ADC|analog-to-digital", or "".
- anchors: only DOIs you are certain exist; fewer correct DOIs beat many guessed ones. A paper citing an
  anchor gets +5.
- vip_authors: "First Last" matches that exact given name + surname, "F. Last" matches authors listed by
  initial, a surname alone matches any author with that surname (use only for rare surnames). +3.
- beyond_ieee.key1_themes: application themes ("wearable", "implantable", "6G", "quantum computing") used
  to pick Nature / Science papers that also mention circuits; [] turns that board off.

MY RESEARCH:
<describe your 2-4 IC research directions, the circuits you design, the metrics you care about, and the
groups you follow>

MY CURRENT config.json:
<paste the whole file here>
```

**What the filled keys look like (an ADC + PLL student) / 填写后的示例:**

```json
{
  "pillars": ["Noise-Shaping & Hybrid SAR ADCs", "All-Digital PLLs & Clock Generation"],
  "positive_keywords": {
    "_pillar1_sar_adc": 0,
    "noise-shaping SAR": 6, "SAR ADC": 5, "successive approximation": 4, "pipelined-SAR": 5,
    "redundant DAC": 3, "dynamic comparator": 3, "kT/C": 2, "Schreier FoM": 3, "ENOB": 1,
    "_pillar2_adpll": 0,
    "ADPLL": 6, "all-digital PLL": 6, "fractional-N": 4, "DTC": 4, "digital-to-time": 4,
    "re:fs-jitter::\\d+(\\.\\d+)?\\s?fs\\b": 3, "phase noise": 2, "DCO": 3
  },
  "negative_keywords": ["power amplifier", "phased array", "GaN", "LiDAR", "optical receiver"],
  "negative_override": "(?i)ADC|PLL|analog-to-digital",
  "anchors": [],
  "vip_authors": ["Robert Bogdan Staszewski", "Nan Sun"]
}
```

With the pre-built database, this example puts ten noise-shaping / pipelined SAR ADC papers and ten
fractional-N PLL papers (JSSC, TCAS-I/II, CICC, ISSCC) on the radar.
使用预建数据库时，该示例会筛出 10 篇噪声整形/流水线 SAR ADC 论文和 10 篇小数分频 PLL 论文。

---

## Step 3 — Run & explore / 第三步：运行与探索

### Score and seed the dashboard / 打分并生成面板

With `paper_store.sqlite` and your `config.json` in place / 数据库和 `config.json` 就绪后运行:

```bash
python briefing.py --rescore
python briefing.py --seed-pillars 5 --no-claude
```

- `--rescore` scores every paper in the store against your pillars (0 API calls, seconds).
  按你的 pillars 给库中全部论文打分（0 次 API 调用，几秒完成）。
- `--seed-pillars 5` fills each pillar with its best papers (published since 2025, flagship venues
  first): at least 5, and up to 10 unreviewed 📋 Candidates (see "Catch-up" below). It writes
  `output/DASHBOARD.html` and `output/MASTER_TABLE.md`.
  为每个 pillar 选出最相关的论文（2025 年以来，旗舰会议/期刊优先；至少 5 篇，并补足到 10 篇待审），生成面板和总表。

Open `output/DASHBOARD.html` in your browser. Not happy with the picks? Edit the keywords and run both
commands again; it costs nothing.
在浏览器中打开 `output/DASHBOARD.html`。不满意？修改关键词后重新运行这两条命令即可，不产生任何费用。

### Weekly radar / 每周雷达

```bash
python briefing.py
```

Collects the last 7 days of papers (Crossref + OpenAlex), scores them, and updates this week's report in
`output/Weekly_Briefings/`. On Friday (`report_day`) the report is finalized. Put your e-mail in
`"contact_email"` so Crossref and OpenAlex serve you from their faster "polite pool".
抓取最近 7 天的新论文并打分，更新本周报告，周五定稿。建议在 `"contact_email"` 填写邮箱以获得更快的 API 响应。

Run it every morning / 每天自动运行:

- **Windows** (Task Scheduler):
  ```bat
  schtasks /Create /TN PaperRadar /TR "cmd /c cd /d C:\path\to\ic-paper-radar && python briefing.py >> radar.log 2>&1" /SC DAILY /ST 07:00
  ```
- **macOS / Linux** (`crontab -e`; the computer must be awake):
  ```text
  0 7 * * * cd "$HOME/ic-paper-radar" && /usr/bin/python3 briefing.py >> radar.log 2>&1
  ```

### Catch-up: older papers join your radar / 补录：旧论文进入雷达

```bash
python briefing.py --sync                       # after 💾 Save Marks: apply your clicks, refill each pillar
python briefing.py --archive "<DOI or title>"   # a mark from the terminal refills that pillar too
python briefing.py --seed-pillars 15            # want more now? 15 this week instead of 10
```

- **What it does:** papers already in the store (status `archive`) that were published since
  `catch_up.since` (2025-01-01) never appeared as "new", so no report showed them. Catch-up moves the
  best of them into the radar's 📋 Candidates and the report's Catch-up section. Flagship venues
  (`flagship_venues`: JSSC, ISSCC, VLSI, CICC, ESSERC, SSC-L) rank higher; ties go to the newest.
  库中 2025 年以来、从未作为"新论文"出现过的论文，会按 pillar 补进 📋 Candidates（旗舰会议/期刊优先）。
- **How many, per pillar:** the larger of two rules.
  - **Water mark:** keep `min_candidates_per_pillar` (10) unreviewed 📋 Candidates. Each ✅ Select,
    ⭐ Cite or 🗄️ Archive drops the pillar to 9, and the next command brings it back to 10.
  - **Weekly top:** at least `per_pillar` (3) new ones every week, even when the pillar is full.
  水位线：每个 pillar 保持 10 篇待审论文，每整理一篇（✅/⭐/🗄️），下次运行就补一篇；每周至少新增 3 篇。
- **When it refills:** the daily run, `--sync`, the mark flags (`--select`, `--cite`, `--archive`, …),
  `--rescore`, `--lineage`, `--add` and `--seed-pillars`. Dashboard clicks count once you 💾 Save Marks
  and run `--sync` (or the next daily run). If a pillar prints `Pillar archive used up`, every matching
  paper is already on the radar.
  每日运行、`--sync`、标记命令、`--rescore`、`--lineage`、`--add`、`--seed-pillars` 都会补充；面板上的点击需先 💾 保存再 `--sync`。
- **Not papers:** `catch_up.not_a_paper` (a regex on title + abstract) skips ISSCC/VLSI tutorials, short
  courses, forums and plenary talks, which IEEE lists like papers (about 24 in the shared database).
  Leave it in `config.json`; delete it only if you want those entries back.
  `not_a_paper` 正则会跳过 IEEE 当作论文收录的教程、短课程、论坛和全体报告（共享数据库中约 24 条），请保留。
- **Settings** in `config.json` → `catch_up`: `since`, `per_pillar`, `min_candidates_per_pillar` (10 when
  missing), `flagship_venues`, `flagship_bonus`, `not_a_paper`. 均可在 `config.json` 的 `catch_up` 中修改。

### Topic deep-dives / 专题综述

```bash
python briefing.py --topic "noise-shaping SAR ADC with passive integrator"
python briefing.py --recall "ring oscillator"      # local store only, 0 calls
```

`--topic` combines the local store, OpenAlex and (with a key) the IEEE API: the classics by citations
plus recent work, written to `output/Topic_Dives/`. It works even before you configure pillars.
`--topic` 结合本地库、OpenAlex 和 IEEE API（如有 key），输出经典论文与近期进展；无需先配置 pillars。

### Curation / 整理论文

On the dashboard, click ✅ Select / ⭐ Cite / 🗄️ Archive. Clicks are kept in your browser; **💾 Save
Marks** downloads `curation_marks.json` (to your Downloads folder), and the next `python briefing.py`
or `python briefing.py --sync` applies it. **📥 Download cite.bib** exports your ⭐ papers.
From the terminal: `python briefing.py --cite "<DOI or title words>"` (also `--select`, `--archive`,
`--uncite`, `--unselect`, `--unarchive`).
在面板上点击按钮标记论文；点 **💾 Save Marks** 下载 `curation_marks.json`，下次运行或 `--sync` 时写入数据库。

### Optional: free IEEE API key / 可选：免费 IEEE API key

Without a key the radar prints one `[INFO]` line and uses OpenAlex + Crossref. With a key, new papers get
their abstracts and IEEE index terms sooner and older months are back-filled.
没有 key 时打印一行 `[INFO]` 并使用 OpenAlex + Crossref；有 key 时新论文摘要更全，并会回填历史论文。

1. Register at <https://developer.ieee.org> (free plan, about 200 calls/day; activation can take a day).
2. Store the key as an environment variable, never in `config.json` / 保存为环境变量，不要写进 `config.json`:
   - Windows (then open a new terminal):
     ```bat
     setx IEEE_API_KEY "your-key"
     ```
   - macOS (zsh):
     ```bash
     echo 'export IEEE_API_KEY="your-key"' >> ~/.zshrc && source ~/.zshrc
     ```

### Optional: AI digests with the Claude Code CLI / 可选：用 Claude Code 生成 AI 摘要

If the `claude` command is installed and signed in (<https://claude.com/claude-code>), each run sends the
new papers' **titles and abstracts** to `claude -p` and adds a short English digest (verification,
pillar, innovation, key metrics), plus a weekly synthesis on Fridays. If `claude` isn't found, the radar
switches to `--no-claude` by itself and everything else still works. Add `--no-claude` to save tokens.
安装并登录 `claude` 后，每次运行会用标题和摘要生成英文摘要，周五生成周综述；找不到 `claude` 时自动切换为
`--no-claude`，其余功能照常。

---

## All commands / 全部命令

| Command | What it does |
|---|---|
| `python briefing.py` | Weekly radar: collect, score, update this week's report |
| `python briefing.py --rescore` | Re-score every paper after a keyword change (0 calls) |
| `python briefing.py --seed-pillars N` | Put the best papers of each pillar on the radar now: at least N this week, and up to 10 unreviewed |
| `python briefing.py --topic "..."` | Topic deep-dive (local + OpenAlex [+ IEEE]) |
| `python briefing.py --recall "..."` | Search the local store only |
| `python briefing.py --add "<DOI or title>" [--pillar N] [--cite]` | Pin a paper you care about |
| `python briefing.py --cite / --select / --archive "<DOI or title words>"` | Mark papers from the terminal |
| `python briefing.py --sync` | Apply 💾 Save Marks exports, refill each pillar to 10, rewrite the dashboard |
| `python briefing.py --lineage` | Conference ↔ journal links for every catalog paper |
| `python briefing.py --finalize` | Finalize this week's report now |
| `--no-claude` | Add to any command: no AI calls |
| `--dry-run` | Work on a copy of the store, write to `output/_archive/_dryrun/` |

## Project layout / 目录结构

| Path | What it is |
|---|---|
| `config.json` | Your settings: pillars, keywords, venues, anchors / 你的配置 |
| `briefing.py` | The command you run / 运行入口 |
| `fetcher.py`, `topic.py`, `relations.py`, `pins.py` | Collection, scoring, deep-dives, lineage, pinning |
| `catalog.py`, `html_renderer.py`, `curation.py` | Master table, BibTeX, dashboard, ✅/⭐/🗄️ marks |
| `store.py`, `paths.py`, `env_guard.py` | Paper store, output paths (`./output`), portable mode |
| `vpn_checker.py` | Optional campus-VPN check for your own institution (`--require-vpn`, `--fetch-pdf`; set up in `config.json` → `vpn`) |
| `paper_store.sqlite` | The paper database (not in Git) / 数据库（不在仓库中） |
| `output/` | Everything generated (not in Git) / 生成的所有文件 |

## Notes / 说明

- **No PDFs:** digests and scores use titles and abstracts only. Read the paper before citing its numbers.
  不读取 PDF，摘要与评分只基于标题和摘要；引用数据前请阅读原文。
- **Reports are in English** (academic convention). / 报告统一使用英文。
- **Reset:** delete `output/` and run `python briefing.py --rescore`; the store keeps every paper.
  重置：删除 `output/` 后重新运行 `--rescore`，数据库中的论文不会丢失。
- **Dedicated machine (optional):** set `"portable_mode": false` and `"host_lock": "<hostname>"` in
  `config.json` to stop the scripts from running on other computers that sync the same folder.

## Troubleshooting / 常见问题

| Symptom | Fix |
|---|---|
| `[SETUP REQUIRED] No research pillars configured in config.json!` | Do Step 2 |
| `[TIP] Local paper store is currently empty.` | Do Step 1 (request the database, or let weekly runs and `--topic` fill it) |
| `json.decoder.JSONDecodeError` | `config.json` isn't valid JSON (a missing comma or quote) |
| `[INFO] No IEEE_API_KEY set` | Not an error: the free OpenAlex + Crossref mode is in use |
| `HTTP Error 429` from OpenAlex | OpenAlex's daily free budget is used up; the run continues and retries next time. Setting `contact_email` helps |
| `python` not found / opens the Microsoft Store (Windows) | Install Python 3.11+ from python.org with "Add python.exe to PATH", or use `py` |
| `xcrun: error` (macOS) | Install Python from python.org, or run `xcode-select --install` once |
| Dashboard has no pillar buttons | Run `--rescore` and `--seed-pillars 5` after editing `config.json` |
