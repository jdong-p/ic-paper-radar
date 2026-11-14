# 📡 Engineer Paper Radar (v3.0)

**A free, local radar for new engineering and science papers, tuned to your own research.**

**一个免费、在本地运行、按你自己的研究方向定制的工程与科研论文雷达。**

Engineer Paper Radar started as **IC Paper Radar**, one PhD student's radar for integrated circuits. Since
v3.0, pluggable **Domain Presets** run the same engine for **IC / ECE**, **Robotics, Control & General
Engineering**, **BioMed (PubMed / bioRxiv / medRxiv)** and **Chemistry & Materials**. It is pure Python
standard library: no `pip install`, no paid API, and no AI or terminal needed to set it up.

Engineer Paper Radar 起源于 **IC Paper Radar**（一名博士生为集成电路方向打造的论文雷达）。从 v3.0 起，可插拔的
**领域预设**（Domain Presets）让同一引擎服务于 **IC / 电子工程**、**机器人、控制与通用工程**、**生物医学（PubMed /
bioRxiv / medRxiv）** 以及 **化学与材料**。纯 Python 标准库：无需 `pip install`、无需付费 API，配置也不需要 AI 或命令行。

## ✨ What's new in v3.0.2
*v3.0.2 亮点*

1. **🖥️ Zero-AI, zero-code Visual Control Center (`STARTUP.html` + `Start_Radar_GUI.cmd` / `.command`):**
   double-click the launcher, configure your pillars, weighted keywords, VIP authors, anchors and the
   deployment mode (💻 Single PC or 🌐 Virtual Mesh LAN) in the browser, then run updates with one click.\
   零 AI、零代码的可视化控制中心：双击启动器，在浏览器中配置方向、加权关键词、重点作者、锚点论文和部署模式
   （单机 / 虚拟局域网），并一键运行更新。
2. **🧭 4 domain cartridges (`presets.py`)**, switched with one click.\
   四种领域预设，一键切换。

   | Preset | Field | Evidence badge |
   |---|---|---|
   | `ic_ece` (default) | 🔬 IC & Solid-State Circuits | ✅ Silicon-Verified vs ⚠️ Simulation-Only |
   | `general_eng` | 🛠️ Robotics, Control & General Engineering | 🛠️ Hardware Tested vs ⚠️ Simulation-Only |
   | `bio_med` | 🧬 Biology, Biomedical & Medicine (PubMed / bioRxiv) | 🧬 Wet-Lab / In-Vivo vs 💻 In-Silico Only |
   | `chem_mat` | 🧪 Chemistry, Materials & ChemE | 🧪 Exp. Synthesized vs 💻 DFT / Sim Only |

   Each preset also brings starter venues and, with the Claude CLI, digests written in the field's own words.\
   每个预设自带起步期刊/会议，配合 Claude CLI 时 AI 摘要也会使用该领域的术语。
3. **🎯 v3.0 hybrid scoring and FTS5 search engine:** SQLite `FTS5` + `bm25()` search in milliseconds,
   OpenAlex lookups batched 40 DOIs per request, bibliographic coupling (`coupling:+3`), and a
   Karpathy-style Naive Bayes **personal taste classifier** (`taste:-2…+4`) that learns from your
   ✅ / ⭐ / 🗄️ clicks automatically.\
   混合打分与全文检索：FTS5 + bm25 毫秒级搜索、OpenAlex 每次批量查询 40 个 DOI、文献耦合加分，以及从你的
   ✅ / ⭐ / 🗄️ 点击中自动学习的朴素贝叶斯**个人口味分类器**。
4. **🔗 Decentralized, federated private data repos:** one click on **✨ Create / Init My Private Repo**
   creates your own private GitHub corpus repo; subscribe to colleagues' corpora with `read_repos` and browse
   their radars read-only in `Peers/DASHBOARD_<peer>.html`.\
   去中心化的私有数据仓库：一键创建你自己的私有 GitHub 论文库；通过 `read_repos` 订阅同事的论文库，并在
   `Peers/DASHBOARD_<peer>.html` 中只读浏览他们的雷达。

> The repository was renamed from `jdong-p/ic-paper-radar`. GitHub redirects old links and clones, so
> existing checkouts keep working (`git remote set-url origin <new URL>` is optional).
>
> 本仓库由 `jdong-p/ic-paper-radar` 更名而来；GitHub 会自动重定向旧链接和旧的克隆地址。

---

## 🚀 Quick Start: 100% visual setup in `STARTUP.html` (recommended)
*快速开始：在 `STARTUP.html` 中完成全部可视化配置（推荐）*

You **don't** need to write `config.json`, use an AI agent, or type a single command. The browser page
`STARTUP.html` (the **Setup & Control Center**) sets up, runs and syncs the radar with buttons.

你**不需要**手写 `config.json`、不需要 AI 助手，也不需要输入任何命令。浏览器页面 `STARTUP.html`（**设置与控制中心**）
通过按钮完成配置、运行和同步。

**Before you start:** install **Python 3.11+** from <https://www.python.org/downloads/> (Windows: tick
"Add python.exe to PATH"), then get this folder: **Code → Download ZIP** on GitHub (unzip it), or
`git clone https://github.com/jdong-p/engineer-paper-radar.git`.

**准备工作：** 从 python.org 安装 **Python 3.11+**（Windows 上勾选 "Add python.exe to PATH"），然后在 GitHub 上点
**Code → Download ZIP** 下载并解压本项目（或使用 `git clone`）。

### Step 1: Launch the Visual Control Center
*第一步：启动可视化控制中心*

Double-click **`Start_Radar_GUI.cmd`** (Windows) or **`Start_Radar_GUI.command`** (macOS; the first time,
right-click → Open). It starts a small server on `http://127.0.0.1:18766` (this computer only) and opens
**`STARTUP.html`** in your browser. Keep its window open while you use the page. On Linux, run
`python3 briefing.py --gui` once instead.

双击 **`Start_Radar_GUI.cmd`**（Windows）或 **`Start_Radar_GUI.command`**（macOS，首次需右键 → 打开）。它会在本机
`127.0.0.1` 上启动一个小服务器，并在浏览器中自动打开 **`STARTUP.html`**。使用期间请保持该窗口打开。
Linux 上请运行一次 `python3 briefing.py --gui`。

### Step 2: Configure everything visually in `STARTUP.html`
*第二步：在 `STARTUP.html` 中可视化配置*

The **🧭 Setup Progress & Readiness** card at the top shows what is still missing.

页面顶部的 **🧭 Setup Progress & Readiness** 卡片会显示还缺少哪些设置。

1. **Pick your domain preset.** In **🧭 Domain preset**, click **Apply** on 🔬 IC & Solid-State Circuits,
   🧬 Biology, Biomedical & Medicine (PubMed / bioRxiv), 🧪 Chemistry, Materials & ChemE, or 🛠️ Robotics,
   Control & General Engineering.\
   **选择领域预设**：在 **🧭 Domain preset** 中，点击对应卡片上的 **Apply**。
2. **Let 🪄 Quick Keyword Setup build your keywords (no AI, 0 tokens).** In the **🪄** card:
   - name 1–9 pillars (a pillar is one research direction, e.g. "Pipelined & Ring-Amp ADCs"), add **2–5 anchor
     DOIs** (papers you love) and type a few **rough seed words** per pillar (e.g. `ring amplifier, pipelined
     ADC, low power`);
   - click **🪄 Auto-Plan Keywords, Weights & VIPs (from Anchors + Seeds)**;
   - review the preview (weighted keywords from +5 down to +1, unit regexes, a `negative_override`, VIP
     authors, each with its evidence, and how many papers would pass), then click **✅ Apply Selected to My
     Config**.\
   **让 🪄 快速关键词设置自动生成关键词（无需 AI，0 token）**：命名方向、添加 2–5 篇你喜欢的锚点论文 DOI、为每个方向写几个
   粗略的种子词，点击 **🪄 Auto-Plan**，在预览中勾选后点 **✅ Apply Selected to My Config**。
3. **Fine-tune.** Every keyword stays editable in **🎯 My Research Themes & Keywords** (click a weight to change
   it), and VIP authors and anchors in **👤 Key Authors & 🏛️ Classic Anchors**.\
   **微调**：所有关键词都可以在 **🎯 My Research Themes & Keywords** 中修改，重点作者与锚点论文在
   **👤 Key Authors & 🏛️ Classic Anchors** 中修改。

**🎯 How keyword weights work (min_score = 5).** A paper becomes a candidate when the weights of the keywords
in its title, abstract and index terms add up to `min_score`:

**🎯 关键词权重说明（min_score = 5）**：论文标题、摘要和索引词中命中的关键词权重之和达到 `min_score` 时，论文成为候选。

| Weight | Meaning | Examples |
|---|---|---|
| **+5** | Core target phrase: one hit alone passes `min_score`<br>核心目标短语：命中一次即可达到 `min_score` | `ring amplifier`, `noise-shaping SAR` |
| **+4** | Specific topology or acronym (rare in the store, frequent in your field)<br>特定结构或缩写 | `MDAC`, `NTF`, `residue amplifier` |
| **+3** | Key mechanism, or a metric regex (`re:…`)<br>关键机制或指标正则 | `comparator`, `re:fJ-energy` |
| **+2** | Supporting circuit or method term<br>辅助电路或方法术语 | `gain error`, `calibration scheme` |
| **+1** | Broad context word: never passes `min_score` alone<br>宽泛的上下文词，单独永远达不到 `min_score` | `low power`, `sensor`, `CMOS` |

The planner reads only your own paper store (and OpenAlex for anchors it lacks). It weights each term by how
much more often it appears in your seed papers than in the whole store, caps terms that are common anyway, and
checks that the full set doesn't flood your radar: words found in more than 5 % of the store stay at +1.

规划器只读取你自己的论文库（以及 OpenAlex 上你的库中没有的锚点论文）。它按一个词在种子论文中比在整个库中常见多少来定权重，
对本来就常见的词设上限，并检查整套关键词不会让雷达被大量论文淹没：出现在 5 % 以上论文中的词最多 +1。
4. ***(Optional)* Connect a private data repo.** In **🤝 Private Shared Repo & Peer Sync**, either click
   **✨ Create / Init My Private Repo** to start your own, or, if a collaborator gave you access to theirs
   (for example a lab corpus of 10,000+ papers), paste its URL and click **📥 Clone & Connect Private Data
   Repo**, then **📥 Read / Pull Shared Repos** to load every paper with one click.\
   **（可选）连接私有数据仓库**：在 **🤝 Private Shared Repo & Peer Sync** 中点击 **✨ Create / Init My Private
   Repo** 创建你自己的仓库；或者在协作者给你权限后，粘贴其仓库地址并点击 **📥 Clone & Connect Private Data Repo**，
   再点 **📥 Read / Pull Shared Repos**，一键载入共享论文库。

Every change is kept on the page until you click **💾 Save Config** (only the settings you changed are
written; the previous file is backed up in `output/_system/config.backup.json`). The Run button below saves
for you too.

页面上的修改在点击 **💾 Save Config** 后写入 `config.json`（只写入改动的设置，旧文件备份在
`output/_system/config.backup.json`）。下面的运行按钮也会自动保存。

### Step 3: Click `▶ Run & Update My Dashboard`
*第三步：点击 `▶ Run & Update My Dashboard`*

Click **▶ Run & Update My Dashboard** in the bar at the bottom of `STARTUP.html`. It saves your settings,
scores every paper in your store against your pillars, fills each pillar with its best papers, and rebuilds
**`DASHBOARD.html`**. The output streams into the page; then click **📊 Open Dashboard ↗** in the header.

点击 `STARTUP.html` 底部栏中的 **▶ Run & Update My Dashboard**：它会保存设置、按你的方向给全部论文打分、为每个方向
挑选最佳论文，并重建 **`DASHBOARD.html`**。运行输出会实时显示在页面上；完成后点击页面顶部的 **📊 Open Dashboard ↗**。

The **🚀 Run** card has the other buttons, for any time:

**🚀 Run** 卡片中还有以下按钮，随时可用：

- **🌐 Fetch New Papers Now:** collects the latest papers from every venue and updates this week's report.\
  抓取所有期刊/会议的最新论文，并更新本周报告。
- **📥 Read / Pull Shared Repos:** reads your data repo and every repo you subscribe to (never pushes).\
  拉取你的数据仓库和你订阅的所有仓库（从不推送）。
- **🔄 Full Sync with My Private Repo:** applies your dashboard marks, then syncs and pushes your corpus.\
  应用面板上的标记，然后同步并推送你的论文库。

Only one run happens at a time: a button pressed while another run is going (a scheduled task, a second
window, a double click) starts nothing and shows that run's output instead.

同一时间只运行一个任务：其他任务运行时按下按钮不会重复启动，而是显示正在运行的任务输出。

`STARTUP.html` is rewritten with the dashboard on every run, and **⚙️ Setup & Manage** in the dashboard's
header opens it. Opened as a plain file (without the launcher) it still shows everything and lets you edit:
**💾 Save** then downloads a new `config.json` to put in this folder, and each button shows its command.

每次运行都会与面板一起重写 `STARTUP.html`，面板顶部的 **⚙️ Setup & Manage** 可以打开它。直接以文件方式打开
（不经启动器）时也能查看和编辑：保存会下载新的 `config.json`，按钮会显示对应的命令。

### Where the papers come from
*论文从哪里来*

The radar keeps every paper it has seen in `paper_store.sqlite` (in this folder; not in the repository).
An empty store shows a `[TIP]` on the dashboard. Pick one:

雷达把见过的所有论文存放在本目录的 `paper_store.sqlite` 中（不在仓库里）。数据库为空时面板会显示 `[TIP]`。
任选一种方式：

- **A. Request the pre-built IC database (instant start):** **[open a GitHub Issue](../../issues/new?title=Database%20request)**
  titled "Database request" (say briefly who you are, e.g. your university), and the author sends you
  `paper_store.sqlite` privately. Drop it next to `briefing.py`. Don't post your e-mail address in the issue
  (issues are public); the author replies there with a way to send the file.\
  **A. 索取预建的 IC 数据库（立即可用）**：在本仓库新建标题为 "Database request" 的 Issue（简单说明身份，例如所在
  学校），作者会私下发送 `paper_store.sqlite`，放到 `briefing.py` 同一目录即可。请不要在 Issue 中公开填写邮箱。
- **B. Build your own:** click **🌐 Fetch New Papers Now** (and come back to it, or schedule it). Each run
  adds the latest papers from all venues (Crossref + OpenAlex, free); with a free IEEE API key it also
  back-fills older months, so the store reaches 2024 within a few weeks.\
  **B. 自己建库**：点击 **🌐 Fetch New Papers Now**（可定期再点或设为定时任务）。每次运行都会抓取所有期刊/会议的
  新论文；设置免费 IEEE API key 后还会回填历史论文，几周内即可覆盖 2024 年以来的论文。
- **C. Read a collaborator's data repo:** see Step 2, item 4.\
  **C. 读取协作者的数据仓库**：见第二步第 4 项。

The pre-built database holds **2,500+ IC papers**, mostly published 2024 – 2026, about 90 % with abstracts:
TCAS-I (524), IEEE Sensors Letters (462), JSSC (447), ISSCC (359), TCAS-II (301), VLSI (262), CICC (179),
SSC-L (29), ESSERC and a few Nature / Science papers, with reference lists, citation counts and
conference ↔ journal links. About 50 papers carry a cached AI digest. All personal curation has been
reset, so your own pillars decide everything. It is shared privately for personal study: please don't
republish it.

预建数据库包含 2,500+ 篇 IC 论文（主要为 2024–2026 年，约 90 % 含摘要），附参考文献、被引次数和会议↔期刊关联；
约 50 篇带有缓存的 AI 摘要。所有个人标记均已清除，完全由你自己的方向决定排序。数据库仅供个人学习使用，请勿二次发布。

> Prefer a terminal, an AI assistant, or unattended daily runs? Everything above also works from the command
> line: see [⚙️ Optional: Command-Line (CLI) & Unattended Scheduling](#cli) below.
>
> 喜欢命令行、AI 助手或无人值守的定时运行？以上所有操作也都可以用命令行完成，见下方的"可选：命令行与定时运行"。

---

## Features
*功能*

- **Zero dependencies:** Python **3.11+** standard library only. No `pip install`.\
  **零依赖**：只需 Python 3.11+ 标准库，无需 `pip install`。
- **Runs anywhere:** Windows, macOS and Linux. Everything is written to `./output`.\
  **跨平台**：支持 Windows、macOS 和 Linux，所有输出写入 `./output`。
- **Visual Control Center (`output/STARTUP.html`):** setup, runs and syncing with buttons (see Quick Start).\
  **可视化控制中心**：用按钮完成配置、运行和同步（见快速开始）。
- **Interactive `output/DASHBOARD.html`:** three bars (view → pillar or topic → curation stage), search
  titles, authors, numbers (`nW`, `ENOB`, `fs`) and your own notes, read abstracts and digests, click
  ✅ Select / ⭐ Cite / 🗄️ Archive, and type a 🏷️ Tech note per paper.\
  **交互式面板**：三层导航（视图 → 方向或专题 → 整理状态），搜索标题、作者、数字和你的笔记，查看摘要，标记
  ✅ 选中 / ⭐ 引用 / 🗄️ 归档，并为每篇论文写一条 🏷️ 技术笔记。
- **BibTeX export:** `output/cite.bib` (⭐ papers, for Overleaf) and `output/selected_pool.bib` (✅ + ⭐),
  rewritten on every run and downloadable from the dashboard.\
  **自动导出 BibTeX**：每次运行都会重写，也可在面板中下载。
- **Weekly reports:** `output/Weekly_Briefings/<YYYY-Www>.md` with a ranked table, a citation map and
  (optionally) an AI synthesis.\
  **每周报告**：包含排序表、引用关系图和（可选的）AI 综述。
- **Lineage tracking:** links a journal paper to the ISSCC / VLSI / CICC / ESSERC paper it extends (📈), so
  you can see what the journal version adds.\
  **会议→期刊演进**：把期刊论文与其扩展自的会议论文关联起来（📈）。
- **Topic deep-dives:** the classics (by citations) and recent work on any topic (a CLI command, see below).\
  **专题综述**：收集任意主题的经典论文与近期进展（命令行功能，见下文）。
- **Evidence badges:** measured-silicon (or wet-lab, synthesized, hardware-tested) papers get a badge and a
  small bonus; simulation-only papers are flagged.\
  **验证标记**：有实测（流片、湿实验、合成、硬件测试）的论文获得标记和少量加分；仅仿真的论文会被标出。
- **Free data sources:** Crossref and OpenAlex (no key). A free IEEE API key and the Claude Code CLI are
  optional extras.\
  **免费数据源**：使用 Crossref 和 OpenAlex（无需 key）；免费 IEEE API key 和 Claude Code CLI 为可选项。

### The default IC / ECE preset
*默认 IC / ECE 预设*

With the default `ic_ece` preset, the radar follows the IEEE solid-state-circuits venues (JSSC, ISSCC, VLSI,
CICC, ESSERC, TCAS-I/II, SSC-L, TBioCAS, Sensors Letters) and, optionally, Nature / Science. It scores every
paper against **your research pillars**, writes a weekly report, and builds an interactive dashboard.

默认的 `ic_ece` 预设跟踪 IEEE 固态电路领域的主要会议和期刊（JSSC、ISSCC、VLSI、CICC、ESSERC、TCAS-I/II、SSC-L、
TBioCAS、Sensors Letters），并可选跟踪 Nature / Science。它按照**你的研究方向**（pillars）给每篇论文打分，
生成每周报告，并输出一个可交互的面板。

### v3.0 at a glance
*v3.0 概览*

- **🔎 Instant full-text search:** an SQLite FTS5 index (bm25: title ×5, your 🏷️ notes ×3, index terms,
  authors, abstract) powers the Control Center's **🔎 Search the store** box and the CLI's `--recall` /
  `--topic`. It is built once, in a second, and kept in sync automatically. Shared database files stay
  exactly as before.
- **⚡ Fewer API calls:** OpenAlex lookups go 40 DOIs per request. Feeds are fetched with `ETag` /
  `Last-Modified`, so an unchanged feed answers `304 Not Modified`.
- **🎯 Smarter scores** (each shown in a paper's hits; `config.json` → `scoring`):
  - `title_boost` (keywords in the title count 1.5×);
  - `coupling:+3` (the paper builds on the same references as your 🏛️ / 📌 / ✅ / ⭐ papers);
  - `taste:-2…+4`, a small classifier that learns from your own ✅ / ⭐ and 🗄️ marks. You need 8 ✅ / ⭐ / 📌;
    if you archive few papers, papers you left unmarked in finalized weeks count as half a 🗄️ each. The idea
    comes from Karpathy's arxiv-sanity-lite, done in plain Python.
- **🧭 Other fields:** the domain preset (`"domain_preset"`: `ic_ece`, `bio_med`, `chem_mat`, `general_eng`)
  sets the evidence badge and can load starter venues. With the Claude CLI, the AI digests and the weekly
  synthesis switch to the field's wording too (e.g. 💡 Biological / Translational Takeaway); IC digests stay
  exactly as before. A venue with `"source": "pubmed"` (`"query"`: a PubMed search term) or
  `"source": "biorxiv"` / `"medrxiv"` (`"categories"`) is fetched from those free APIs.
- **🖥️ Deployment** (the **🖥️ Deployment** card):
  - 💻 Single PC (127.0.0.1 only, the default);
  - 🌐 Virtual Mesh LAN: a mini-PC hub on your LAN / Tailscale (`"deployment": "mesh_lan"`). The Control
    Center server also listens on the private IPs in `sync_server.hosts`, behind its per-launch key; the
    links are in `output/_system/gui_link.txt`, and the card shows copyable Task Scheduler commands.

  (There is also a third card. Click it at your own risk. ☕)

v3.0 新增：FTS5 全文检索、更少的 API 调用、更智能的打分（标题加权、文献耦合、个人口味）、多领域预设，以及单机 /
虚拟局域网两种部署方式。

---

## Using the dashboard
*使用面板*

### Three bars
*三层导航*

1. **Views (top bar):** All · 📋 Candidate · ✅ Selected · ⭐ To Cite · **📅 Weekly Brief** ·
   **🔎 Topic Dives** · 📁 More Views (🔬 Silicon-Verified Only · 🏛️ Anchors & Pinned · 📈 Journal
   Extensions · 🗄️ Archived · ⚙️ Customize views).
2. **Inside 📅 Weekly Brief:** All Weekly · one pill per pillar · 🌍 Beyond IEEE, plus **📄 Open Weekly
   Report** (the latest week, with a week selector once there are several).
   **Inside 🔎 Topic Dives:** All dives · one pill per topic dive · 📄 Open Topic Report.
3. **Curation stage, under either:** All (everything but 🗄️ Archived) · 📋 Candidate · ✅ Selected ·
   ⭐ Cite · 📁 More (🏛️ Anchors & Pinned · 🗄️ Archived). The counts follow the pill above, and the stage
   stays set while you switch pillars (e.g. 📋 Candidate across Pillar 1 → 2 → 3).

第一层选视图；在 📅 Weekly Brief 里第二层按方向或 🌍 Beyond IEEE 筛选，在 🔎 Topic Dives 里按专题筛选；
第三层按整理状态筛选，切换方向时保持不变。拖动按钮或用 ⚙️ Customize views 调整顺序。

### Short pillar labels and the phone layout
*短标签与手机布局*

- **Short labels:** each pillar gets a short label such as `P1 · SAR ADC`. It is used on the 📅 Weekly Brief
  pillar buttons (full name on hover), as a pill in the Pillar column (`🌍 Beyond` for Beyond IEEE), and, on a
  touchscreen with a pillar selected, as a `📌 Pillar 1: …` line above the list. Set your own in `config.json`
  (`"pillar_short": ["SAR ADC", "PLL"]`, same order as `pillars`); a pillar without one gets the first 1–2 key
  words of its name (`All-Digital PLLs & Clock Generation` → `P2 · All-Digital PLLs`).
- **Phone (≤ 768 px; wider screens are unchanged):** each paper is a card (date · venue · score · Si · pillar,
  then the full-width title, note and key numbers, and 38 px ✅ Select / ⭐ Cite / 🗄️ Archive buttons); a
  `Sort: Date | Score | Venue` row replaces the table header; the header and the three bars swipe sideways;
  the `.bib` downloads, 🏷️ Tags and ◐ fold behind `⋯`; inputs use 16 px so iOS Safari doesn't zoom. Open
  `output/DASHBOARD.html` on the phone, or use Add to Home Screen.

每个方向有短标签（如 `P1 · SAR ADC`），可在 `config.json` 的 `pillar_short` 中设置，未设置时取名称的前 1–2 个关键词。

手机上（≤ 768 px）论文显示为卡片，按钮 38 px，顶部栏和三层导航可左右滑动，次要按钮收进 `⋯`；电脑上布局不变。

### Curation
*整理论文*

On the dashboard, click ✅ Select / ⭐ Cite / 🗄️ Archive. Clicks are kept in your browser; **💾 Save Marks**
downloads `curation_marks.json` (to your Downloads folder), and the next run (any button in `STARTUP.html`)
applies it. **📥 Download cite.bib** exports your ⭐ papers.

在面板上点击按钮标记论文；点 **💾 Save Marks** 下载 `curation_marks.json`，下次运行（`STARTUP.html` 中任一按钮）时写入数据库。

**🏷️ Tech note:** expand a paper and type one short phrase in the **🏷️ Tech note** field below the
🔬 Silicon line (the key technique or takeaway, e.g. "split CDAC + kT/C cancellation"). Enter or leaving
the field saves it; Esc restores the old text. It's kept in your browser like a click, shows as a 🏷️ badge
under the title, and the search box finds it. 💾 Save Marks writes it into `curation_marks.json` next to the
marks, and the next run stores it in the database and in `MASTER_TABLE.md` (Key Numbers:
`🏷️ **note** · …`). One line, at most 200 characters; an empty note clears it.

**🏷️ 技术笔记**：展开论文，在 🔬 Silicon 下方的 **🏷️ Tech note** 输入一句话（回车或离开输入框即保存，Esc 撤销）；
💾 Save Marks 后，下次运行时写入数据库和 `MASTER_TABLE.md`。最多 200 字符，留空即清除。

```json
{"marks": {"10.1109/jssc.2026.1234567": "selected+cite"},
 "notes": {"10.1109/jssc.2026.1234567": "split CDAC + kT/C cancellation"}}
```

### Catch-up: older papers join your radar
*补录：旧论文进入雷达*

- **What it does:** papers already in the store (status `archive`) that were published since
  `catch_up.since` (2025-01-01) never appeared as "new", so no report showed them. Catch-up moves the
  best of them into the radar's 📋 Candidates and the report's Catch-up section. Flagship venues
  (`flagship_venues`: JSSC, ISSCC, VLSI, CICC, ESSERC, SSC-L) rank higher; ties go to the newest.\
  库中 2025 年以来、从未作为"新论文"出现过的论文，会按方向补进 📋 Candidates（旗舰会议/期刊优先）。
- **How many, per pillar:** the larger of two rules.
  - **Water mark:** keep `min_candidates_per_pillar` (10) unreviewed 📋 Candidates. Each ✅ Select,
    ⭐ Cite or 🗄️ Archive drops the pillar to 9, and the next run brings it back to 10.
  - **Weekly top:** at least `per_pillar` (3) new ones every week, even when the pillar is full.

  水位线：每个方向保持 10 篇待审论文，每整理一篇（✅/⭐/🗄️），下次运行就补一篇；每周至少新增 3 篇。
- **When it refills:** every run (all the `STARTUP.html` buttons, and the CLI commands that change marks or
  scores). Dashboard clicks count once you 💾 Save Marks and run. If a pillar prints
  `Pillar archive used up`, every matching paper is already on the radar.\
  每次运行都会补充；面板上的点击需先 💾 保存，下次运行时生效。
- **Not papers:** `catch_up.not_a_paper` (a regex on title + abstract) skips ISSCC/VLSI tutorials, short
  courses, forums and plenary talks, which IEEE lists like papers (about 24 in the shared database).
  Leave it in `config.json`; delete it only if you want those entries back.\
  `not_a_paper` 正则会跳过 IEEE 当作论文收录的教程、短课程、论坛和全体报告（共享数据库中约 24 条），请保留。
- **Settings** in `config.json` → `catch_up`: `since`, `per_pillar`, `min_candidates_per_pillar` (10 when
  missing), `flagship_venues`, `flagship_bonus`, `not_a_paper`.\
  均可在 `config.json` 的 `catch_up` 中修改。

---

## Sharing and private data repos
*共享与私有数据仓库*

### Your own private data repo
*你自己的私有数据仓库*

The data-repo protocol is defined by this public code, so anyone can **own** a private data repo and share
it with whoever they choose. Nobody has to host one for you.

数据仓库的协议由本公开代码定义，任何人都可以拥有并分享自己的私有数据仓库，无需他人托管。

Click **✨ Create / Init My Private Repo** in `STARTUP.html` (type `your-name/my-paper-radar-data` first):

在 `STARTUP.html` 中输入 `your-name/my-paper-radar-data` 后点击 **✨ Create / Init My Private Repo**：

1. With the [GitHub CLI](https://cli.github.com) signed in (`gh auth login`), it creates the private repo for
   you; without `gh`, create an **empty private** repo on github.com first.\
   已登录 GitHub CLI 时会自动创建私有仓库；否则请先在 github.com 上创建一个**空的私有**仓库。
2. It clones it into `paths.data_repo_dir` (default `../ic-paper-radar-data`) and writes the protocol files:
   `IC_PAPER_RADAR_DATA` (marks a data repo: only such clones are ever reset), `.gitattributes`, `README.md`,
   your clean `paper_store_clean_share.sqlite` and `peers/<peer_id>.json`.\
   克隆到 `data_repo_dir`（默认 `../ic-paper-radar-data`），并写入协议文件和你的干净论文库。
3. It pushes `main` and sets `"data_repo": {"remote_url": "…"}`. On a second computer, the first
   **🔄 Full Sync** clones it automatically.\
   推送 `main` 并设置 `remote_url`；在第二台电脑上，第一次 **🔄 Full Sync** 会自动克隆。

**Sharing:** add a collaborator in the repo's GitHub settings. With **write** access they sync the same
corpus (**🔄 Full Sync**). With **read** access they add your repo to their `"read_repos"` list
(in `STARTUP.html`, or in `config.json`):

**共享**：在 GitHub 仓库设置中添加协作者。有**写**权限的协作者用 **🔄 Full Sync** 同步同一个论文库；只有**读**权限的
协作者把你的仓库加入自己的 `read_repos` 列表：

```json
"data_repo": {"read_repos": ["your-name/my-paper-radar-data",
                             {"repo": "otherlab/rf-radar-data", "merge_corpus": true}]}
```

**📥 Read / Pull Shared Repos** then fetches your repo and every read repo. It never pushes to them; the same
happens at the end of every Full Sync.

**📥 Read / Pull Shared Repos** 拉取你的仓库和所有订阅的仓库，从不向它们推送。

### Subscribed repos: isolated by default, with a domain check
*订阅的仓库：默认隔离，并自动检查领域*

**Every subscribed repo is an isolated dashboard by default.** Its papers and its peers' radars stay in that
repo's own folder (`<data_repo_dir>_peers/…`): **0 rows** enter your `paper_store.sqlite`, and nothing of it is
ever exported into your own private data repo. Each of its peers still gets a full read-only page,
`output/Peers/DASHBOARD_<peer>.html`, built straight from that repo, with that radar's title and its own
evidence badges (e.g. 🧬 Wet-Lab / In-Vivo vs 💻 In-Silico Only).

**每个订阅的仓库默认都是一个隔离的面板**。它的论文和同事雷达只留在该仓库自己的文件夹中：**0 条**记录进入你的
`paper_store.sqlite`，也不会被导出到你自己的私有数据仓库。它的每位同事仍有一个完整的只读页面，直接由该仓库生成，
使用该雷达自己的标题和验证标记。

**Domain Similarity Check.** On every 📥 Read, and in `STARTUP.html` under **🤝 Private Shared Repo & Peer
Sync**, each subscribed repo is compared with your radar: its `domain_preset` (from the repo's marker file or
its peers) and the share of its papers in venues you use.

**领域相似度检查**：每次 📥 Read 时（以及在 `STARTUP.html` 中），每个订阅的仓库都会与你的雷达比较：领域预设，以及
其论文中属于你所用期刊/会议的比例。

- **🟢 Similar / same domain** (the same preset, or ≥ 15 % venue overlap, e.g. another lab's IC repo): stays
  isolated unless you tick **Merge & Sync Corpus**. Then its papers are merged into your store and go into your
  own data repo like your primary corpus (`{"repo": …, "merge_corpus": true}`).\
  **🟢 相似领域**（预设相同或期刊重合 ≥ 15 %）：默认隔离；勾选 **Merge & Sync Corpus** 后才会并入你的论文库并同步。
- **🟠 Different discipline** (another preset and < 15 % venue overlap, e.g. BioMed vs. IC): locked to isolated
  mode. Ticking Merge asks you to confirm first (`"force_merge": true`).\
  **🟠 不同学科**（预设不同且重合 < 15 %）：锁定为隔离模式；如仍要合并，页面会先请你确认。

**📚 Switch Radar / Repo ▾** in the dashboard's header lists every dashboard by the private repo it comes
from: your primary repo (📡 My Radar and its peers), repos merged into your corpus, and each isolated external
repo, each with its field's icon. Every peer page has a **← Back to My Radar** button.

面板顶部的 **📚 Switch Radar / Repo ▾** 按来源私有仓库列出所有面板（你的主仓库、已合并的仓库、各个隔离的外部仓库），
每个同事页面都有 **← Back to My Radar** 按钮。

### Co-maintaining one corpus
*共同维护一个论文库*

If you and a colleague keep one paper corpus in a shared (private) Git repo whose single file is
`paper_store_clean_share.sqlite`, connect it in `STARTUP.html` (**📥 Clone & Connect Private Data Repo**
clones it next to this folder), and **🔄 Full Sync with My Private Repo** keeps both of you in sync:

如果你和同事用一个共享（私有）Git 仓库维护同一个论文库，在 `STARTUP.html` 中连接它，然后用
**🔄 Full Sync with My Private Repo** 保持双方同步：

1. `git fetch` + `git reset --hard origin/main` in the clone: the shared file is taken exactly as it is,
   so Git never has to merge a binary file.
2. It is merged into your store (below): new papers arrive as `external`, your marks are never touched,
   and those that fit your pillars are adopted (`"data_repo": {"adopt_external": true}`). Empty fields are
   filled, including the date of the last lineage search, and a paper's first-seen date only ever moves
   earlier, to the first radar that saw it.
3. Your store is exported, cleaned, back over the shared file: every paper, the merged ones included.
   An empty field is always written as NULL (never `[]` or `''`), so every radar writes the same file.
4. It commits and pushes **only if** the remote gains something (new papers, missing abstracts or
   references, a lineage-search date, an earlier first-seen date, higher citation counts), so two radars
   never trade empty commits. If someone pushed in the meantime, it waits a random 2–5 s and starts again
   from step 1 (up to 3 times), so several radars syncing in the same minute take turns instead of failing.

It also runs after every Friday finalize when the clone exists (`"friday_sync": false` turns that off).
After both of you have run it, both stores hold the same union of papers.

运行后双方的论文库包含相同的论文并集；每周五定稿后也会自动同步。

### See each other's radar
*查看对方的雷达*

The shared `.sqlite` stays clean, but each sync also writes **your radar** next to it as
`peers/<your id>.json`: your pillar names and, for every paper you curated, its pillar, score, ✅ / ⭐ / 🗄️,
Si call, 🏷️ note and status. It reads your colleague's file and builds a read-only copy of their dashboard,
**`output/Peers/DASHBOARD_<id>.html`**, listed in your dashboard's header under **📚 Switch Radar / Repo ▾**.
It's the same page (search, filters, row details, BibTeX download) with their pillars,
choices and domain preset (its evidence badges); nothing you click there changes your own radar.

每次同步还会把你的雷达（方向名称、标记、⭐、评分、笔记）写成 `peers/<id>.json`，并为对方生成只读面板
`output/Peers/DASHBOARD_<id>.html`，在面板顶部的 📚 菜单中即可打开。

In `config.json` → `"data_repo"`: `"peer_id"` is your name in `peers/` (empty = your Git `user.name`),
`"share_curation": false` publishes nothing, `"share_notes": false` keeps your 🏷️ notes private. Everyone
with access to the shared repo can read what you publish.

### What a shared copy contains
*共享副本包含什么*

- **Every paper** with its abstract, references and AI digest, but none of your own state: all rows become
  unmarked `archive` papers (no ✅/⭐/🗄️, 🏷️ notes, pillars, scores or weekly state), the digests lose their
  "Pillar:" line, and the run log tables are emptied.\
  分享的副本包含全部论文、摘要、参考文献和 AI 摘要，但清除你的标记、笔记、方向、分数和运行记录。
- **Merging is safe:** one row per DOI, no duplicates. For a paper you already have, only empty objective
  fields (abstract, authors, references, a missing digest, higher citation counts) are filled in; your marks,
  notes, pillars, scores and weekly state are never touched. New papers arrive as `external` (searchable,
  used for conference ↔ journal links, never pulled into your pillars) until they fit your pillars and are
  adopted. Isolated subscribed repos never enter your store at all, so they can't end up in a copy you
  share.\
  合并他人的库：同一 DOI 只保留一条，只补空字段，从不改动你的标记；新论文标为 `external`，符合你的方向后才会收入。
- **Safety check:** before a share copy replaces the old one, it is checked for leftover marks or "Pillar:"
  lines and for local user paths (`C:\Users\…`, `/home/…`, `/Users/…`) or your sync token in any text. If
  anything is found, nothing is written and the previous copy stays.\
  写入前会检查残留标记、个人路径和令牌；发现问题时不会写入。

---

## Optional extras
*可选功能*

### Free IEEE API key
*免费 IEEE API key*

Without a key the radar prints one `[INFO]` line and uses OpenAlex + Crossref. With a key, new papers get
their abstracts and IEEE index terms sooner and older months are back-filled. The Setup Progress card shows
whether a key is set (yes/no only: keys are never displayed).

没有 key 时打印一行 `[INFO]` 并使用 OpenAlex + Crossref；有 key 时新论文摘要更全，并会回填历史论文。
控制中心只显示是否已设置 key，从不显示 key 本身。

1. Register at <https://developer.ieee.org> (free plan, about 200 calls/day; activation can take a day).\
   在 developer.ieee.org 免费注册（约 200 次调用/天，激活可能需要一天）。
2. Store the key as an environment variable, never in `config.json`:\
   把 key 保存为环境变量，不要写进 `config.json`：
   - Windows (then open a new terminal):
     ```bat
     setx IEEE_API_KEY "your-key"
     ```
   - macOS (zsh):
     ```bash
     echo 'export IEEE_API_KEY="your-key"' >> ~/.zshrc && source ~/.zshrc
     ```

### A narrow arXiv feed
*arXiv 定向订阅*

Off by default. For a topic that lives on arXiv before (or instead of) IEEE, set `"arxiv": {"enabled": true}`
in `config.json` with one or more raw arXiv search queries in `queries` (syntax:
<https://info.arxiv.org/help/api/user-manual.html>), e.g.
`(abs:LLM OR abs:"reinforcement learning") AND (abs:"analog circuit" OR abs:RFIC)`. The weekly run runs each
query through arXiv's official API, newest first, page by page back to the lookback window (at most
`max_pages`), and keeps only papers whose title or abstract contains a term of **every** group in `must_all`
(e.g. `[["LLM", "reinforcement learning"], ["analog circuit", "RFIC"]]`) and none of `exclude_any`; everything
else is dropped, not stored. Keep `must_all` non-empty: an empty one lets every query result through. Kept
papers are scored like any other paper with venue `arXiv`, filed under `pillar` if set, and cited as `@misc`
with their arXiv id. A topic deep-dive adds an arXiv stage only when the topic itself matches every
`must_all` group. A preprint whose journal version is already in the store is skipped. They stay out of shared
copies unless `"share": true`, you selected / cited them, or the existing share file (e.g. the shared repo's)
already has them, so an export never drops a paper the remote has. arXiv allows one request every 3 s, so the
radar waits `min_interval_s` (at least 3); no key is needed.

默认关闭。适合主要先发在 arXiv 上的方向：在 `config.json` 里设 `"arxiv": {"enabled": true}`，在 `queries` 中写
arXiv 检索式。每周运行按时间倒序分页查询，只保留标题或摘要同时命中 `must_all` 每一组、且不含 `exclude_any`
的论文，其余直接丢弃、不入库。保留的论文与其他论文一样打分（venue 为 `arXiv`），可用 `pillar` 归到某个方向。
`must_all` 不要留空：留空时检索结果会全部保留。专题综述只有在主题本身满足 `must_all` 时才查 arXiv。除非
`"share": true`、你选中/引用过，或已有的共享文件里本来就有，否则不会进入共享数据库。

### AI digests with the Claude Code CLI
*用 Claude Code 生成 AI 摘要*

If the `claude` command is installed and signed in (<https://claude.com/claude-code>), each run sends the
new papers' **titles and abstracts** to `claude -p` and adds a short English digest (verification,
pillar, innovation, key metrics), plus a weekly synthesis on Fridays. If `claude` isn't found, the radar
switches to `--no-claude` by itself and everything else still works.

安装并登录 `claude` 后，每次运行会用标题和摘要生成英文摘要，周五生成周综述；找不到 `claude` 时自动切换为
`--no-claude`，其余功能照常。

---

<a name="cli"></a>
## ⚙️ Optional: Command-Line (CLI) & Unattended Scheduling
*可选：命令行与无人值守定时运行*

**Everything in this section is optional.** `STARTUP.html` handles initialization, syncing and daily runs
with buttons. Use the terminal only if you prefer it, want an AI assistant to write your settings, or want
unattended scheduled runs (a server, a mini-PC, a cron job).

**本节内容全部可选。** `STARTUP.html` 已经用按钮完成配置、同步和日常运行。只有在你偏好命令行、希望让 AI 助手生成
设置，或需要无人值守的定时运行（服务器、迷你主机、cron）时才需要本节。

> On macOS use `python3` wherever this section says `python`. On Windows, `python` or `py` both work.
>
> macOS 上请把本节中的 `python` 换成 `python3`；Windows 上 `python` 或 `py` 均可。

### `config.json` by hand
*手动编辑 `config.json`*

**Your `config.json`** is created from the template `config.example.json` the first time you run any
command (e.g. `python briefing.py --help`, or the launcher), or copy it yourself:
`cp config.example.json config.json` (Windows: `copy config.example.json config.json`). Edit only
`config.json`: Git ignores it, so `git pull` never overwrites or conflicts with your settings, and new
settings in later versions reach you automatically (see "Updating"). Until `pillars` and keywords are
filled, `python briefing.py` stops with `[SETUP REQUIRED]` (only `--topic` and `--recall` work without
pillars).

**你的 `config.json`** 在首次运行任意命令（或启动器）时由模板 `config.example.json` 自动生成（也可手动复制）。只编辑
`config.json`：Git 会忽略它，`git pull` 不会覆盖或冲突，新版本新增的设置会自动生效。填写方向和关键词之前，
`python briefing.py` 会提示 `[SETUP REQUIRED]` 并停止。

### Keyword plan from the terminal (= 🪄 Auto-Plan)
*在终端中生成关键词方案（等同于 🪄 Auto-Plan）*

```bash
python briefing.py --plan-keywords "ring amplifier, pipelined ADC, low power; noise-shaping SAR"
```

Seed words of pillar 1, then `;` and those of pillar 2, and so on; the anchors and pillar names come from your
`config.json`. It prints the weighted keywords with their evidence, the calibration, a `negative_override`, VIP
authors and a `positive_keywords` fragment to paste, and saves the full plan in
`output/_system/keyword_plan.json`. It changes nothing by itself.

依次写出方向 1 的种子词、`;`、方向 2 的种子词……锚点论文和方向名称取自 `config.json`。它会输出加权关键词及依据、校准结果、
`negative_override`、重点作者，以及可直接粘贴的 `positive_keywords` 片段，本身不修改任何文件。

### Setup with an AI assistant
*使用 AI 助手配置*

**With Claude Code (in this folder):**

**使用 Claude Code（在本目录中）：**

```bash
cd engineer-paper-radar
claude
```

Then type (replace the brackets):

然后输入（替换方括号内容）：

> Read README.md and configure `config.json` for my research: [your IC topics, e.g. "noise-shaping SAR
> ADCs and ADPLLs for IoT radios"], then run `--rescore` and `--seed-pillars 5`.

**With Web Claude / ChatGPT / Gemini:**

**使用网页版 Claude / ChatGPT / Gemini：**

1. Copy the **AI Setup Prompt** below into the chat.\
   复制下面的 **AI Setup Prompt** 到对话框。
2. Under it, describe your research, then paste the **whole current `config.json`**.\
   在其后描述你的研究方向，并粘贴**完整的当前 `config.json`**。
3. Replace your `config.json` with the file the AI returns, and check it's valid JSON
   (e.g. <https://jsonlint.com>).\
   用 AI 返回的文件替换 `config.json`，并确认它是合法 JSON。

#### AI Setup Prompt (copy the whole block)
*AI Setup Prompt（复制整个代码块）*

```text
You are configuring "Engineer Paper Radar" (IC preset), a local tool that scores new IEEE solid-state-circuits papers
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

**What the filled keys look like (an ADC + PLL student):**

**填写后的示例（ADC + PLL 方向）：**

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

### Score and seed the dashboard (= ▶ Run & Update My Dashboard)
*打分并生成面板（等同于 ▶ Run & Update My Dashboard）*

```bash
python briefing.py --rescore
python briefing.py --seed-pillars 5 --no-claude
```

- `--rescore` scores every paper in the store against your pillars (0 API calls, seconds).\
  按你的方向给库中全部论文打分（0 次 API 调用，几秒完成）。
- `--seed-pillars 5` fills each pillar with its best papers (published since 2025, flagship venues
  first): at least 5, and up to 10 unreviewed 📋 Candidates. It writes `output/DASHBOARD.html` and
  `output/MASTER_TABLE.md`.\
  为每个方向选出最相关的论文（2025 年以来，旗舰会议/期刊优先；至少 5 篇，并补足到 10 篇待审），生成面板和总表。

Not happy with the picks? Edit the keywords and run both commands again; it costs nothing.

不满意？修改关键词后重新运行这两条命令即可，不产生任何费用。

### Weekly radar and scheduled runs (= 🌐 Fetch New Papers Now)
*每周雷达与定时运行（等同于 🌐 Fetch New Papers Now）*

```bash
python briefing.py
```

Collects the last 7 days of papers (Crossref + OpenAlex), scores them, and updates this week's report in
`output/Weekly_Briefings/`. On Friday (`report_day`) the report is finalized. Put your e-mail in
`"contact_email"` so Crossref and OpenAlex serve you from their faster "polite pool".

抓取最近 7 天的新论文并打分，更新本周报告，周五定稿。建议在 `"contact_email"` 填写邮箱以获得更快的 API 响应。

Run it every morning, unattended:

每天自动运行（无人值守）：

- **Windows** (Task Scheduler; in 🌐 Virtual Mesh LAN mode the **🖥️ Deployment** card shows ready-made
  commands):
  ```bat
  schtasks /Create /TN PaperRadar /TR "cmd /c cd /d C:\path\to\engineer-paper-radar && python briefing.py >> radar.log 2>&1" /SC DAILY /ST 07:00
  ```
- **macOS / Linux** (`crontab -e`; the computer must be awake):
  ```text
  0 7 * * * cd "$HOME/engineer-paper-radar" && /usr/bin/python3 briefing.py >> radar.log 2>&1
  ```

Every run takes the lock file `.run.lock` (`run_lock.py`): a run started from a terminal while another is
going waits for it (up to 30 min), and `STARTUP.html` shows the running one's output.

每次运行都会占用锁文件 `.run.lock`：从终端启动时如有其他任务在运行，会等待其结束（最多 30 分钟）。

### Catch-up, marks and topic dives from the terminal
*在终端中补录、标记和专题综述*

```bash
python briefing.py --sync                       # after 💾 Save Marks: apply your clicks, refill each pillar
python briefing.py --archive "<DOI or title>"   # a mark from the terminal refills that pillar too
python briefing.py --cite "<DOI or title words>"   # also --select, --uncite, --unselect, --unarchive
python briefing.py --seed-pillars 15            # want more now? 15 this week instead of 10
python briefing.py --topic "noise-shaping SAR ADC with passive integrator"
python briefing.py --recall "ring oscillator"   # local store only, 0 calls
```

`--topic` combines the local store, OpenAlex and (with a key) the IEEE API: the classics by citations plus
recent work, written to `output/Topic_Dives/`. It works even before you configure pillars.

`--topic` 结合本地库、OpenAlex 和 IEEE API（如有 key），输出经典论文与近期进展；无需先配置方向。

### Sharing and data repos from the terminal
*在终端中共享与同步数据仓库*

```bash
python briefing.py --export-share                       # output/paper_store_clean_share.sqlite
python briefing.py --export-share D:/share/radar.sqlite    # or any path (also: "share_db" under "paths")
python briefing.py --init-data-repo your-name/my-paper-radar-data   # = ✨ Create / Init My Private Repo
python briefing.py --pull-data-repo                     # = 📥 Read / Pull Shared Repos
python briefing.py --sync-data-repo                     # the sync half of 🔄 Full Sync
python briefing.py --merge-store classmate.sqlite --peer alice   # bring in someone else's store file
python briefing.py --adopt-external                     # later: take the ones that fit your pillars
```

- `--export-share` writes a clean copy (also every Friday, when the weekly report is finalized);
  `--include-curation` keeps your marks, notes, pillars and scores, for a co-maintainer who should see them
  (the text check still runs). A classmate puts the file in their folder as `paper_store.sqlite`.\
  `--export-share` 写出干净的共享副本（每周五也会自动更新）。
- `--merge-store` opens the other file read-only; with `--peer NAME` it also builds that person's read-only
  dashboard page, and their marks are kept in a separate `peer_curation` table.\
  `--merge-store` 以只读方式打开对方的文件；加 `--peer NAME` 时会生成对方的只读面板。

### All commands
*全部命令*

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
| `python briefing.py --export-share [DST] [--include-curation]` | Write the clean share copy of your store now (also every Friday) |
| `python briefing.py --merge-store OTHER.sqlite [--peer NAME]` | Merge someone else's store: fill gaps, new papers as `external` |
| `python briefing.py --adopt-external` | Move external papers that fit your pillars into your archive |
| `python briefing.py --sync-data-repo` | Sync with a shared corpus repo: fetch, merge, export, push if the remote gains (also on Fridays) |
| `python briefing.py --init-data-repo OWNER/NAME` | Create (with `gh`) or clone your own private data repo, push the protocol files, set `remote_url` |
| `python briefing.py --pull-data-repo` | Read only: fetch your data repo and every `read_repos` entry, run the domain check, merge only your data repo and repos with `merge_corpus` (no push) |
| `python briefing.py --plan-keywords "SEEDS; SEEDS"` | 0-token keyword & weight plan from your anchors and seed words (prints it; 🪄 in `STARTUP.html` applies it) |
| `python briefing.py --gui [PORT]` | Setup & Control Center in your browser (`Start_Radar_GUI.cmd` / `.command` do the same) |
| `python briefing.py --lineage` | Conference ↔ journal links for every catalog paper |
| `python briefing.py --finalize` | Finalize this week's report now |
| `--no-claude` | Add to any command: no AI calls |
| `--dry-run` | Work on a copy of the store, write to `output/_archive/_dryrun/` |

---

## Project layout
*目录结构*

| Path | What it is |
|---|---|
| `config.json` | Your settings: pillars, keywords, venues, anchors (not in Git, created from the template)<br>你的配置（不在仓库中） |
| `config.example.json` | The starter template and the defaults for any key your `config.json` lacks<br>模板与默认值 |
| `config_file.py` | Creates `config.json` from the template, merges it over the defaults |
| `briefing.py` | The command behind every button<br>运行入口 |
| `CITATION.cff` | Citation metadata (GitHub's "Cite this repository") |
| `scorer.py`, `presets.py` | v3.0 score boosters (coupling, taste) and domain presets |
| `keyword_planner.py` | 🪄 0-token keyword & weight planner (`--plan-keywords`, STARTUP.html Auto-Plan) |
| `run_lock.py` | One run at a time: `.run.lock` and `.run.log` (not in Git)<br>运行锁 |
| `Start_Radar_GUI.cmd`, `Start_Radar_GUI.command`, `control_center.py` | The Setup & Control Center (`output/STARTUP.html`, `--gui`)<br>控制中心 |
| `fetcher.py`, `topic.py`, `relations.py`, `pins.py` | Collection, scoring, deep-dives, lineage, pinning |
| `catalog.py`, `html_renderer.py`, `curation.py` | Master table, BibTeX, dashboard, ✅/⭐/🗄️ marks |
| `store.py`, `paths.py`, `env_guard.py` | Paper store, output paths (`./output`), portable mode |
| `vpn_checker.py` | Optional campus-VPN check for your own institution (`--require-vpn`, `--fetch-pdf`; set up in `config.json` → `vpn`) |
| `paper_store.sqlite` | The paper database (not in Git)<br>数据库（不在仓库中） |
| `output/` | Everything generated (not in Git)<br>生成的所有文件 |

## Updating
*更新*

```bash
git pull
```

(Downloaded the ZIP instead? Download it again and copy your `config.json` and `paper_store.sqlite` over.)

Your `config.json`, store and `output/` are not in Git, so a pull never touches them. When a new version
adds a setting to `config.example.json`, the scripts use its default until you set it in your own
`config.json`. Nested sections merge key by key (your values win); lists, and your keyword, synonym and
conference maps, are always taken whole from your file.

（如果你下载的是 ZIP，重新下载后把 `config.json` 和 `paper_store.sqlite` 复制过去即可。）
`config.json`、数据库和 `output/` 都不在 Git 中，`git pull` 不会改动它们；新版本在 `config.example.json` 中新增的
设置会以默认值自动生效，你的设置始终优先。

**One-time step for clones from before 2026-11-11** (when `config.json` was still in Git). The pull that
removes it from Git would otherwise stop with "Your local changes … would be overwritten", or delete your
file. Save your settings first, then put them back:

**2026-11-11 之前克隆的仓库需要一次性操作**（当时 `config.json` 还在 Git 中）：先备份，拉取后再恢复。

```bash
cp config.json config.local.json      # Windows: copy config.json config.local.json
git checkout -- config.json
git pull
cp config.local.json config.json      # Windows: copy config.local.json config.json
```

`config.local.json` is ignored too; keep it as a backup or delete it. If you had **committed** your
`config.json`, the pull reports a conflict on it instead; your file is still in the folder, so finish with
`git rm --cached config.json` and `git commit --no-edit`.

如果你曾提交过自己的 `config.json`，拉取时会提示冲突；文件仍在目录中，运行 `git rm --cached config.json` 和
`git commit --no-edit` 即可。

<a name="call-for-co-maintainers"></a>
## 🤝 Call for Co-Maintainers & Domain Leads
*招募共同维护者与领域负责人*

Engineer Paper Radar began as IC Paper Radar, one PhD student's radar for sensor interfaces and
ultra-low-power circuits. Since v3.0 it can follow any field. **We are looking for researchers who want to
own a domain**:

| Domain | What a lead would add |
|---|---|
| RF / mmWave / wireless | venues (IMS, RFIC, JSSC RF), keywords, an `rf_mmw` preset |
| Power management / PLLs & clocking | DC-DC / LDO / PLL keywords, flagship venues |
| Digital / AI accelerators / architecture | ISSCC digital, VLSI, ISCA / MICRO via OpenAlex, an architecture preset |
| BioMed / PubMed | better `bio_med` cues and PubMed terms, clinical-trial registries |
| Chemistry / materials | `chem_mat` venues, characterization cues, ChemRxiv as a source |
| Robotics / control | `general_eng` venues (ICRA, IROS, CDC), hardware-test cues |

**How to contribute:**
- **A domain preset** is one entry in `presets.py`: its badge words, evidence cues and starter venues, plus
  optional prompt passages.
- **A source connector** is one function in `fetcher.py` registered in `SOURCES` (see `pubmed_venue`,
  `biorxiv_venue`).
- **The workflow:** open a PR against `main` (see "Contributing" below). The required **PR audit** check
  compiles everything and keeps personal settings, paths, IPs and keys out of the repo, so a first PR is
  safe to send.

我们正在招募各领域的共同维护者（射频/毫米波、电源/PLL、数字/AI 加速器、生物医学、化学/材料、机器人）。新增一个领域
预设只需在 `presets.py` 中添加一项；新增一个数据源只需在 `fetcher.py` 的 `SOURCES` 中注册一个函数。欢迎提交 PR，
自动化的 PR audit 会帮你检查。

### 🏆 Contributors Hall of Fame
*贡献者名人堂*

| Contributor | Contribution |
|---|---|
| **[@Daidingxx](https://github.com/Daidingxx)** | PR #2: the optional arXiv feed (`arxiv_source.py`, merged as `2b1d73f`), and the first peer radar on the shared corpus |
| **[@jdong-p](https://github.com/jdong-p)** | Author and maintainer |

<a name="citation"></a>
## 📖 Citation
*引用*

If Engineer Paper Radar helps your research, please cite it. GitHub's **"Cite this repository"** button (from
`CITATION.cff`) gives APA and BibTeX, or copy this:

如果本工具对你的研究有帮助，欢迎引用：

```bibtex
@software{jdong_engineer_paper_radar_2026,
  author    = {jdong-p},
  title     = {{Engineer Paper Radar: Automated Literature Intelligence, Verification Filtering, and Federated Curation}},
  year      = {2026},
  version   = {3.0.2},
  url       = {https://github.com/jdong-p/engineer-paper-radar},
  license   = {MIT},
  note      = {Contributors: Daidingxx}
}
```

## Contributing
*参与开发*

`main` is protected: nobody pushes to it directly, and it can't be force-pushed or deleted. Every change
goes in through a **pull request with one approving review** from the maintainer.

`main` 分支受保护：不能直接推送、强制推送或删除；所有修改都通过 Pull Request，经维护者批准一次后合并。

- **Collaborators** (write access): push a branch and open a PR, no fork needed.
- **Everyone else:** fork the repo, push to your fork, and open a PR from there.
- **Your `config.json` can't end up in a PR:** Git ignores it. A new setting goes into
  `config.example.json` with a blank or neutral default, and the code should read it with that default.\
  你的 `config.json` 被 Git 忽略，不会进入 PR；新增设置写入 `config.example.json` 并给出空值或中性默认值。
- **PR audit** (required check, `.github/workflows/pr_audit.yml`): every `.py` file must compile;
  `config.example.json` must keep its personal settings blank (`pillars`, keywords, anchors,
  `data_repo.peer_id`, `paths.data_repo_dir`, VPN and sync hosts…); no `config.json` /
  `config.local.json` / `.sqlite` / `.db` / `.env` / key / log file, `output/` or `peers/`, no file over
  1 MB; no added line with a personal path (`C:\Users\<name>`), private IP, e-mail address or key-like
  string. Changes under `.github/` are merged by the maintainer only.\
  PR 审计（必需检查）：代码须能编译；`config.example.json` 的个人设置须保持为空；不得包含 `config.json`、
  数据库、密钥、日志、个人路径或邮箱。

```bash
git switch -c fix/short-description
git commit -am "Describe the change"
git push -u origin fix/short-description
gh pr create --base main --fill        # or open the PR on github.com
```

Using Claude Code? Ask it to work on a new branch and open a PR; it won't be able to push to `main`.
After the merge, `git switch main && git pull` before starting the next branch.

使用 Claude Code 时，让它在新分支上修改并创建 PR；合并后先 `git pull` 再开始下一个分支。

The shared corpus (`--sync-data-repo`) lives in a separate repo and isn't affected by this rule.

共享论文库（`--sync-data-repo`）在另一个仓库中，不受此规则影响。

## Notes
*说明*

- **No PDFs:** digests and scores use titles and abstracts only. Read the paper before citing its numbers.\
  不读取 PDF，摘要与评分只基于标题和摘要；引用数据前请阅读原文。
- **Reports are in English** (academic convention).\
  报告统一使用英文。
- **Reset:** delete `output/` and click **▶ Run & Update My Dashboard** (or run `python briefing.py --rescore`);
  the store keeps every paper.\
  重置：删除 `output/` 后点击 **▶ Run & Update My Dashboard**（或运行 `--rescore`），数据库中的论文不会丢失。
- **Dedicated machine (optional):** set `"portable_mode": false` and `"host_lock": "<hostname>"` in
  `config.json` to stop the scripts from running on other computers that sync the same folder.

## Troubleshooting
*常见问题*

| Symptom | Fix |
|---|---|
| `[SETUP REQUIRED] No research pillars configured in config.json!` | Add pillars and keywords in `STARTUP.html` (Quick Start, Step 2) |
| `[TIP] Local paper store is currently empty.` | See "Where the papers come from" (request the database, 🌐 Fetch New Papers Now, or a collaborator's repo) |
| `json.decoder.JSONDecodeError` | `config.json` isn't valid JSON (a missing comma or quote); 💾 Save Config in `STARTUP.html` always writes valid JSON |
| `[INFO] No IEEE_API_KEY set` | Not an error: the free OpenAlex + Crossref mode is in use |
| `HTTP Error 429` from OpenAlex | OpenAlex's daily free budget is used up; the run continues and retries next time. Setting `contact_email` helps |
| `python` not found / opens the Microsoft Store (Windows) | Install Python 3.11+ from python.org with "Add python.exe to PATH" (the launcher also tries `py`) |
| `xcrun: error` (macOS) | Install Python from python.org, or run `xcode-select --install` once |
| No pillar pills under 📅 Weekly Brief | Click **▶ Run & Update My Dashboard** after changing pillars |
| A 🏷️ note or click didn't reach `MASTER_TABLE.md` | 💾 Save Marks on the dashboard, then any run (or `python briefing.py --sync`) |
| `STARTUP.html` shows **⚪ Static** and the buttons only show commands | It was opened as a file: start `Start_Radar_GUI.cmd` / `.command` (or `python briefing.py --gui`) |
| macOS: "Start_Radar_GUI.command can't be opened" | Right-click → Open once; if it isn't executable, run `chmod +x Start_Radar_GUI.command` |
| Full Sync: `Please tell me who you are` (older versions) | Update; the sync now commits as your `peer_id` when Git has no name/e-mail set |
