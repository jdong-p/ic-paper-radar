"""Single-file interactive HTML next to the Markdown (stdlib only, 0 tokens):

  IC_Paper_Radar/DASHBOARD.html                 every catalog paper: filters, search, sort, expandable digests,
                                                ⭐ Cite / 🗄️ Archive buttons, BibTeX download
  Weekly_Briefings/<week>.html, Topic_Dives/<x>.html   the Markdown reports with real buttons

Clicks are kept in the browser's localStorage. Each stored click remembers the mark it was made *from*;
when a regenerated page embeds a different mark for that DOI (changed via Markdown, CLI or an applied
curation_marks.json), the stale click is dropped. "💾 Save Marks" exports the clicks as
curation_marks.json; curation.py applies it on the next run / --sync. Mermaid maps use the jsDelivr CDN
(pinned); offline they show as text.
"""
import html
import json
import re
from datetime import datetime
from pathlib import Path

from env_guard import ensure_minisforum_env

ensure_minisforum_env()
import catalog
import curation
import fetcher
import relations

MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"


# ---------- tiny Markdown → HTML (the subset our reports use) ----------

def _inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<!\w)_(?!\s)([^_]+?)(?<!\s)_(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+|[\w./-]+)\)", r'<a href="\2">\1</a>', s)
    s = s.replace("&lt;sub&gt;", "<sub>").replace("&lt;/sub&gt;", "</sub>")
    return s


def md_to_html(md):
    out, i = [], 0
    lines = md.splitlines()
    stack = []  # open list tags with their indent

    def close_lists(indent=-1):
        while stack and stack[-1][1] > indent:
            out.append(f"</li></{stack.pop()[0]}>")

    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            close_lists()
            lang, body = ln[3:].strip(), []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            code = html.escape("\n".join(body), quote=False)
            out.append(f'<pre class="mermaid">{code}</pre>' if lang == "mermaid" else f"<pre><code>{code}</code></pre>")
            i += 1
            continue
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            close_lists()
            cells = lambda r: [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", r.strip())[1:-1]]
            rows = [cells(ln)]
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            out.append('<div class="tablewrap"><table><thead><tr>' + "".join(f"<th>{_inline(c)}</th>" for c in rows[0])
                       + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                                                         for r in rows[1:]) + "</tbody></table></div>")
            continue
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", ln)
        if m:
            indent, tag = len(m[1]), ("ol" if m[2][0].isdigit() else "ul")
            if stack and stack[-1][1] == indent:
                out.append("</li><li>")
            elif not stack or indent > stack[-1][1]:
                out.append(f"<{tag}><li>")
                stack.append((tag, indent))
            else:
                close_lists(indent)
                out.append("</li><li>" if stack else f"<{tag}><li>")
                if not stack:
                    stack.append((tag, indent))
            out.append(_inline(m[3]))
            i += 1
            continue
        if stack and ln.startswith("  ") and ln.strip():
            out.append("<br>" + _inline(ln.strip()))  # continuation line inside a list item
            i += 1
            continue
        close_lists()
        h = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if h:
            out.append(f"<h{len(h[1])}>{_inline(h[2])}</h{len(h[1])}>")
        elif ln.startswith(">"):
            out.append(f"<blockquote>{_inline(ln.lstrip('> '))}</blockquote>")
        elif re.match(r"^\s*</?(details|summary)", ln):
            out.append(ln)
        elif ln.strip():
            out.append(f"<p>{_inline(ln)}</p>")
        i += 1
    close_lists()
    return "\n".join(out)


# ---------- shared page shell ----------

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1f23;--muted:#666b73;--card:#ffffff;--line:#e3e1dc;--accent:#2a5bd7;--cite:#b7791f;
--citebg:#fff6e0;--arch:#7a7f87;--ok:#1f7a4d;--warn:#b54708;--chip:#efede8}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15171b;--fg:#e7e5e0;--muted:#9aa0a8;--card:#1d2026;
--line:#2c3038;--accent:#7aa2ff;--cite:#f0b54d;--citebg:#3a2f17;--arch:#8a8f98;--ok:#5cc28e;--warn:#f0a35e;--chip:#262a31}}
:root[data-theme=dark]{--bg:#15171b;--fg:#e7e5e0;--muted:#9aa0a8;--card:#1d2026;--line:#2c3038;--accent:#7aa2ff;--cite:#f0b54d;
--citebg:#3a2f17;--arch:#8a8f98;--ok:#5cc28e;--warn:#f0a35e;--chip:#262a31}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,
"Segoe UI",Inter,Roboto,sans-serif}a{color:var(--accent)}code{background:var(--chip);padding:0 .3em;border-radius:4px;font-size:.92em}
header.bar{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;
display:flex;flex-wrap:wrap;gap:8px;align-items:center}header.bar h1{font-size:17px;margin:0 12px 0 0;max-width:min(60vw,560px);
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:5px 10px;cursor:pointer;
font:inherit;font-size:13.5px;white-space:nowrap}.btn:hover{border-color:var(--accent)}.btn.primary{background:var(--accent);
color:#fff;border-color:var(--accent)}.btn.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.btn.cite.on{background:var(--cite);border-color:var(--cite)}.btn.sel.on{background:var(--ok);border-color:var(--ok)}.btn.arch.on{background:var(--arch);border-color:var(--arch)}
.filters{display:flex;flex-wrap:wrap;gap:6px;padding:10px 16px;border-bottom:1px solid var(--line)}
input.search{flex:1;min-width:200px;padding:6px 10px;border-radius:8px;border:1px solid var(--line);background:var(--card);
color:var(--fg);font:inherit}main{padding:12px 16px 60px;max-width:1500px;margin:0 auto}
.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;background:var(--card)}
th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top;font-size:14px}
thead th{position:sticky;top:0;background:var(--card);z-index:5;cursor:default}th.sort{cursor:pointer;user-select:none}
th.sort:after{content:" ↕";color:var(--muted)}tr.paper{cursor:pointer}tr.paper:hover{background:var(--chip)}
tr.paper.cite{background:var(--citebg)}tr.paper.fade{opacity:0;transition:opacity .3s}tr.detail td{background:var(--bg);padding:12px 18px}
.muted{color:var(--muted);font-size:12.5px}.tag{display:inline-block;background:var(--chip);border-radius:6px;padding:0 6px;
margin:1px 2px 1px 0;font-size:12px}.ok{color:var(--ok)}.warn{color:var(--warn)}.count{font-variant-numeric:tabular-nums}
pre{background:var(--chip);padding:10px;border-radius:8px;overflow:auto;font-size:12.5px}pre.mermaid{background:var(--card)}
.report{max-width:1100px;margin:0 auto;background:var(--card);padding:10px 28px 40px;border:1px solid var(--line);border-radius:12px}
.more{position:relative;display:inline-block}.menu{position:absolute;top:calc(100% + 4px);left:0;z-index:40;
background:var(--card);border:1px solid var(--line);border-radius:10px;padding:6px;display:flex;flex-direction:column;
gap:4px;min-width:230px;max-height:75vh;overflow-y:auto;box-shadow:0 8px 24px rgba(0,0,0,.14)}.menu .btn{text-align:left}
.crow{display:flex;justify-content:space-between;align-items:center;gap:8px}.crow>span:last-child{display:flex;gap:3px}
.btn.mini{padding:2px 7px;font-size:12.5px}.btn[draggable=true]{cursor:grab}
.sibtn{padding:1px 7px;font-size:13px}.sibtn.user{border-color:var(--accent)}.sibtn sup{font-size:9px;color:var(--accent)}
.tagpill{cursor:pointer;opacity:.75}.tagpill:hover{opacity:1}
.topicbar{background:var(--chip)}.topicbar a.btn{text-decoration:none}.tag.tlink{cursor:pointer;color:var(--accent)}
.tier3{background:var(--bg);padding-top:6px;padding-bottom:6px}.tlabel{align-self:center}.push{flex:1}
.tag.notetag{background:var(--citebg);color:var(--fg);font-weight:600}
.noteline{display:flex;flex-wrap:wrap;align-items:center;gap:6px}input.note{flex:1;min-width:220px;max-width:640px;
padding:4px 8px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit;font-size:13.5px}
input.note:focus{outline:none;border-color:var(--accent)}.nstate{color:var(--ok);font-size:12px}
.welcome{margin:10px 12px;padding:14px 16px;border:2px solid var(--accent);border-radius:10px;background:var(--chip);font-size:15px;line-height:1.5}
tr.banner td{background:var(--chip);font-weight:600;font-size:14.5px;border-top:2px solid var(--accent)}
tr.subbanner td{color:var(--muted);font-size:12.5px;font-weight:600;padding:4px 8px}
.cur{display:inline-flex;gap:6px;margin:4px 0}.pill.live{border-color:var(--ok);color:var(--ok)}
.pill.offline{border-color:var(--warn);color:var(--warn)}blockquote{border-left:3px solid var(--accent);margin:8px 0;padding:2px 12px;color:var(--muted)}
@media (max-width:700px){.hide-sm{display:none}main,.filters,header.bar{padding-left:10px;padding-right:10px}.report{padding:8px 12px}}
"""

JS_COMMON = r"""
const LS = 'paper_radar_marks_v1';
const PAGE = JSON.parse(document.getElementById('radar-data').textContent);
let store = {};
try { store = JSON.parse(localStorage.getItem(LS) || '{}'); } catch (e) { store = {}; }
// drop clicks whose starting point no longer matches what this (newer) page embeds, or that are already applied
for (const [doi, o] of Object.entries(store)) {
  const base = PAGE.marks[doi];
  if (base === undefined) continue;
  if (base !== o.base || base === o.mark) delete store[doi];
}
// 🏷️ Tech notes (v2.15): queued like marks, {doi: {note, base, t}}; '' clears a note
const LSN = 'paper_radar_notes_v1';
PAGE.notes = PAGE.notes || {};
let nstore = {};
try { nstore = JSON.parse(localStorage.getItem(LSN) || '{}'); } catch (e) { nstore = {}; }
for (const [doi, o] of Object.entries(nstore)) {
  if (PAGE.marks[doi] === undefined) continue;
  const base = PAGE.notes[doi] || '';
  if (base !== o.base || base === o.note) delete nstore[doi];
}
function persist() {
  try { localStorage.setItem(LS, JSON.stringify(store)); localStorage.setItem(LSN, JSON.stringify(nstore)); } catch (e) {}
}
persist();
function cleanNote(s) { return String(s || '').split(/\s+/).filter(Boolean).join(' ').slice(0, 200); }
function noteOf(doi) { return nstore[doi] ? nstore[doi].note : (PAGE.notes[doi] || ''); }
function setNote(doi, note) {
  note = cleanNote(note);
  if (note === noteOf(doi)) { refreshBars(); return; }
  const base = PAGE.notes[doi] || '';
  if (note === base) delete nstore[doi]; else nstore[doi] = {note, base, t: Date.now()};
  persist(); refreshBars(); if (window.onMarkChange) window.onMarkChange(doi);
  if (LIVE) flush(); else autoWriteFile();
}
function noteState(doi) {
  if (nstore[doi]) return LIVE ? '⏳ saving…' : '🟡 queued (offline)';
  return noteOf(doi) ? (LIVE ? '✓ saved' : '✓') : '';
}
// a mark = stage (normal | selected | archived) + '+cite' when ⭐ + '+si' / '+sim' for the user's silicon call;
// pre-v2.9 'cite' = 'selected+cite'
function normMark(m) { return m === 'cite' ? 'selected+cite' : (m || 'normal'); }
function markOf(doi) { return normMark(store[doi] ? store[doi].mark : PAGE.marks[doi]); }
function stageOf(doi) { return markOf(doi).split('+')[0]; }
function citedOf(doi) { return markOf(doi).split('+').includes('cite'); }
function siOf(doi) { const f = markOf(doi).split('+'); return f.includes('si') ? 'si' : f.includes('sim') ? 'sim' : ''; }
function fmtMark(st, c, si) { return st + (c ? '+cite' : '') + (si ? '+' + si : ''); }
function setMark(doi, mark) {
  const base = PAGE.marks[doi] || 'normal';
  if (mark === base) delete store[doi]; else store[doi] = {mark, base, t: Date.now()};
  persist(); refreshBars(); if (window.onMarkChange) window.onMarkChange(doi);
  if (LIVE) flush(); else autoWriteFile();   // tier 1: server · tier 2: remembered file handle · always: queue
}

// ---------- tier 1: live sync with radar_sync_server.py (not part of the Starter Edition) ----------
const SYNC = PAGE.sync || {hosts: [], port: 0, token: ''};
let LIVE = null;   // base URL of the reachable server
function hdr() { return {'Content-Type': 'application/json', 'X-Radar-Token': SYNC.token}; }
async function probe() {
  // served by radar_sync_server.py itself (iPhone / any browser over http): same origin first, no CORS or file:// limits
  const bases = (location.protocol.startsWith('http') ? [location.origin] : [])
    .concat(SYNC.hosts.map(h => `http://${h}:${SYNC.port}`));
  for (const base of [...new Set(bases)]) {
    try {
      const r = await fetch(base + '/status', {headers: hdr(), signal: AbortSignal.timeout(SYNC.timeout || 1500), cache: 'no-store'});
      if (!r.ok) continue;
      const s = await r.json();
      const serverT = Date.parse(s.updated_at) || 0;
      // a queued click survives only if made from the server's current mark, or after the server's last change
      for (const [doi, o] of Object.entries(store)) {
        const cur = s.marks[doi] || 'normal';
        if (cur === o.mark || (cur !== o.base && o.t < serverT)) delete store[doi];
      }
      for (const [doi, m] of Object.entries(s.marks)) PAGE.marks[doi] = m;
      for (const doi of Object.keys(PAGE.marks)) if (!(doi in s.marks)) PAGE.marks[doi] = 'normal';
      if (s.notes) {  // the same rule for queued 🏷️ notes
        for (const [doi, o] of Object.entries(nstore)) {
          const cur = s.notes[doi] || '';
          if (cur === o.note || (cur !== o.base && o.t < serverT)) delete nstore[doi];
        }
        PAGE.notes = Object.assign({}, s.notes);
      }
      LIVE = base; persist(); pill(); refreshBars(); if (window.onMarkChange) window.onMarkChange(null);
      if (window.onLive) window.onLive();  // the dashboard syncs its shared settings (bar layout)
      if (pending()) flush();
      return;
    } catch (e) { /* try the next host */ }
  }
  LIVE = null; pill();
}
let flushing = false;
async function flush() {
  if (!LIVE || flushing || !pending()) return;
  flushing = true;
  const marks = {}; for (const [d, o] of Object.entries(store)) marks[d] = o.mark;
  const notes = {}; for (const [d, o] of Object.entries(nstore)) notes[d] = o.note;
  try {
    const r = await fetch(LIVE + '/mark', {method: 'POST', headers: hdr(), body: JSON.stringify({marks, notes}),
                                          signal: AbortSignal.timeout(8000)});
    const res = await r.json();
    if (!r.ok || !res.ok) throw new Error(res.error || r.status);
    for (const [doi, m] of Object.entries(res.marks)) {
      PAGE.marks[doi] = m;
      if (store[doi] && store[doi].mark === marks[doi]) delete store[doi];  // a newer click stays queued
    }
    for (const [doi, n] of Object.entries(res.notes || {})) {
      if (n) PAGE.notes[doi] = n; else delete PAGE.notes[doi];
      if (nstore[doi] && nstore[doi].note === notes[doi]) delete nstore[doi];
    }
    persist(); pill('saved');
  } catch (e) { LIVE = null; pill(); autoWriteFile(); }
  flushing = false; refreshBars();
  if (LIVE && pending()) flush();
}

// ---------- tier 2: offline — remembered curation_marks.json file handle (Chromium desktop) ----------
function idb(mode, fn) {
  return new Promise((ok, bad) => {
    const rq = indexedDB.open('paper_radar', 1);
    rq.onupgradeneeded = () => rq.result.createObjectStore('kv');
    rq.onsuccess = () => { const t = rq.result.transaction('kv', mode); const q = fn(t.objectStore('kv'));
      t.oncomplete = () => ok(q && q.result); t.onerror = () => bad(t.error); };
    rq.onerror = () => bad(rq.error);
  });
}
let HANDLE = null;
idb('readonly', s => s.get('marks_handle')).then(h => { HANDLE = h || null; pill(); }).catch(() => {});
function marksJson() {
  const marks = {}; for (const [d, o] of Object.entries(store)) marks[d] = o.mark;
  const notes = {}; for (const [d, o] of Object.entries(nstore)) notes[d] = o.note;
  return JSON.stringify({exported: new Date().toISOString(), source: document.title, marks, notes}, null, 1);
}
async function writeHandle(h) {
  if ((await h.queryPermission({mode: 'readwrite'})) !== 'granted' &&
      (await h.requestPermission({mode: 'readwrite'})) !== 'granted') return false;
  const w = await h.createWritable(); await w.write(marksJson()); await w.close(); return true;
}
async function autoWriteFile() {
  if (LIVE || !HANDLE || !pending()) return;
  try { if (await writeHandle(HANDLE)) pill('file'); } catch (e) { /* permission lapsed: next click asks again */ }
}
async function chooseFile() {
  const h = await showSaveFilePicker({suggestedName: 'curation_marks.json',
    types: [{description: 'JSON', accept: {'application/json': ['.json']}}]});
  await idb('readwrite', s => s.put(h, 'marks_handle')); HANDLE = h; return h;
}
function pill(flash) {
  const el = document.getElementById('syncpill'); if (!el) return;
  if (LIVE) { el.textContent = flash === 'saved' ? '🟢 Live Sync · saved' : '🟢 Live Sync';
    el.title = 'Clicks go straight to ' + LIVE; el.className = 'btn pill live'; return; }
  el.className = 'btn pill offline';
  el.textContent = HANDLE ? (flash === 'file' ? '🟡 Offline · saved to file' : '🟡 Offline · auto-saving to file')
                          : '🟡 Offline Mode (Queued Locally)';
  el.title = 'Clicks are kept in this browser. ' +
    (window.showSaveFilePicker ? 'Click to pick paper_radar_starter › output › curation_marks.json once; later clicks save there automatically.'
                               : 'Use 💾 Save Marks to export them.');
}
async function pillClick() {
  if (LIVE) { probe(); return; }
  await probe(); if (LIVE) return;
  if (window.showSaveFilePicker) { try { await writeHandle(HANDLE || await chooseFile()); pill('file'); } catch (e) {} }
}
// ✅/🗄️ switch the stage (click again → Candidate) and never touch ⭐; ⭐ toggles on its own, and ⭐ on a
// Candidate also selects it
function toggle(doi, which) {
  let st = stageOf(doi), c = citedOf(doi);
  if (which === 'cite') { c = !c; if (c && st === 'normal') st = 'selected'; }
  else st = st === which ? 'normal' : which;
  setMark(doi, fmtMark(st, c, siOf(doi)));
}
// Si cell: auto → ✅ Silicon-Verified → ⚠️ Simulation-Only → auto (the reader's call after the PDF)
function cycleSi(doi) {
  const next = {'': 'si', si: 'sim', sim: ''}[siOf(doi)];
  setMark(doi, fmtMark(stageOf(doi), citedOf(doi), next));
}
function siBadge(doi, auto) { return {si: '✅', sim: '⚠️ sim'}[siOf(doi)] || auto; }
function siCell(doi, auto, tag) {
  const user = !!siOf(doi), b = siBadge(doi, auto);
  return `<${tag} class="btn sibtn ${b==='✅'?'ok':'warn'} ${user?'user':''}" onclick="event.stopPropagation();cycleSi('${doi}')" ` +
    `title="${user ? 'Set by you after reading the PDF' : 'Automatic guess (' + esc(auto) + ')'} · Click to set Silicon-Verified / ` +
    `Simulation-Only (User confirmed) / back to auto">${b}${user ? '<sup>✓</sup>' : ''}</${tag}>`;
}
function pending() { return Object.keys(store).length + Object.keys(nstore).length; }
function curButtons(doi) {
  const st = stageOf(doi), c = citedOf(doi);
  return `<span class="cur" onclick="event.stopPropagation()">` +
    `<button class="btn sel ${st==='selected'?'on':''}" onclick="toggle('${doi}','selected')">✅ Select</button>` +
    `<button class="btn cite ${c?'on':''}" onclick="toggle('${doi}','cite')">⭐ Cite</button>` +
    `<button class="btn arch ${st==='archived'?'on':''}" onclick="toggle('${doi}','archived')">🗄️ Archive</button></span>`;
}
function refreshCur() { document.querySelectorAll('[data-cur]').forEach(el => el.innerHTML = curButtons(el.dataset.cur)); }
function refreshBars() {
  const p = document.getElementById('pending'); if (p) p.textContent = pending();
  const n = document.getElementById('bibn'); if (n) n.textContent = markedDois(false).length;
  const k = document.getElementById('pooln'); if (k) k.textContent = markedDois(true).length;
  document.querySelectorAll('[data-nstate]').forEach(el => el.textContent = noteState(el.dataset.nstate));
  refreshCur();
}
// ⭐ papers, or (pool) ✅ Selected or ⭐ papers — known to the page or only clicked in this browser
function markedDois(pool) {
  const ok = d => citedOf(d) || (pool && stageOf(d) === 'selected');
  return [...new Set(Object.keys(PAGE.marks).concat(Object.keys(store)))].filter(ok);
}
function download(name, text, type) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], {type}));
  a.download = name; document.body.appendChild(a); a.click(); a.remove();
}
function downloadBib(pool) {  // cite.bib = every ⭐; selected_pool.bib = ✅ or ⭐
  const name = pool ? 'selected_pool.bib' : 'cite.bib';
  const bib = markedDois(pool).map(d => PAGE.bib[d]).filter(Boolean);
  if (!bib.length) { alert(pool ? 'No ✅ Selected or ⭐ Cite papers on this page.' : 'No ⭐ Cite papers on this page.'); return; }
  download(name, `% IC Paper Radar — ${name} exported from the browser\n\n` + bib.join('\n\n') + '\n', 'application/x-bibtex');
}
async function saveMarks() {
  if (!pending()) { alert(LIVE ? 'Everything is already synced.' : 'No unsaved clicks.'); return; }
  await probe(); if (LIVE) { await flush(); return; }
  if (window.showSaveFilePicker) {
    try { if (await writeHandle(HANDLE || await chooseFile())) { pill('file');
      alert('Saved. From now on this browser updates that file automatically after every click while offline. ' +
            'Keep it in the output folder (or your Downloads folder); the next run or briefing.py --sync applies it.'); }
      return;
    } catch (e) { if (e.name === 'AbortError') return; }
  }
  download('curation_marks.json', marksJson(), 'application/json');
  alert('Downloaded curation_marks.json. Leave it in Downloads (or move it into the output folder); ' +
        'the next run or python briefing.py --sync applies it.');
}
function theme() {
  const r = document.documentElement, cur = r.dataset.theme ||
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  r.dataset.theme = cur === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem('paper_radar_theme', r.dataset.theme); } catch (e) {}
}
try { const t = localStorage.getItem('paper_radar_theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
"""


def _page(title, head_extra, bar, body, data, script, mermaid=False):
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style>{head_extra}</head>
<body><header class="bar">{bar}</header>{body}
<script id="radar-data" type="application/json">{blob}</script>
<script>{JS_COMMON}{script}
refreshBars(); pill(); probe(); setInterval(() => {{ if (!LIVE) probe(); }}, 60000);</script>
{f'<script src="{MERMAID}"></script><script>if(window.mermaid){{mermaid.initialize({{startOnLoad:true,theme:matchMedia("(prefers-color-scheme: dark)").matches?"dark":"default"}});}}</script>' if mermaid else ''}
</body></html>"""


def _bar(title, home=None, extra=""):
    return (f'<h1>{html.escape(title)}</h1>'
            + (f'<a class="btn" href="{home}">← Dashboard</a>' if home else "") + extra
            + '<button id="syncpill" class="btn pill" onclick="pillClick()">⏳ Connecting…</button>'
            + '<button class="btn" onclick="downloadBib(false)" title="⭐ Cite papers only, for Overleaf">'
              '📥 Download cite.bib (⭐ <span id="bibn" class="count">0</span>)</button>'
            + '<button class="btn" onclick="downloadBib(true)" title="✅ Selected + ⭐ Cite">'
              '📥 Download selected_pool.bib (✅+⭐ <span id="pooln" class="count">0</span>)</button>'
            + '<button class="btn" onclick="saveMarks()" title="Only needed offline">💾 Save Marks '
              '(<span id="pending" class="count">0</span> queued)</button>'
            + '<button class="btn" onclick="theme()" title="light/dark">◐</button>')


# ---------- data ----------

def _topic_short(t, cfg):
    """'sub-100nW sensor design focusing on low-leakage techniques' → 'sub-100nW sensor low-leakage'
    (first 3 non-generic words; a `short` key in meta['topics'][slug] overrides it)."""
    if t.get("short"):
        return t["short"]
    generic = {w.lower() for w in cfg["topic"]["generic_words"]} - {"low", "ultra"}
    words = [w for w in t["query"].split() if w.lower() not in generic]
    return " ".join(words[:3]) or t["query"][:30]


def topic_dives(store, cfg):
    """meta['topics'] as page data, newest first. Each dive keeps its selection order (classics by relevance,
    then recent by relevance); `role` comes from `n_classic` (saved since 2026-10-28) or, for older dives,
    the same year rule topic.select() used (classic = before topic.recent_from_year)."""
    y0 = cfg["topic"]["recent_from_year"]
    out = []
    for slug, t in sorted((store.meta("topics") or {}).items(), key=lambda kv: kv[1]["date"], reverse=True):
        papers = [store.get(d) for d in t["dois"]]
        papers = [p for p in papers if p]
        if "n_classic" in t:
            roles = ["classic" if i < t["n_classic"] else "recent" for i in range(len(papers))]
        else:
            roles = ["classic" if 0 < (relations._ym(p.get("published")) or 0) // 12 < y0 else "recent" for p in papers]
        report = Path(cfg["paths"]["topic_dir"]) / f"{t['date']}_{slug}.md"
        out.append({"slug": slug, "query": t["query"], "date": t["date"], "short": _topic_short(t, cfg),
                    "href": f"{Path(cfg['paths']['topic_dir']).name}/{report.stem}.html" if report.exists() else "",
                    "papers": [{"doi": p["doi"], "role": r, "rank": i} for i, (p, r) in enumerate(zip(papers, roles))]})
    return out


def paper_records(store, cfg, dives=None):
    """Every catalog paper (+ all selected/cite/archived), with BibTeX keys assigned once for the whole set."""
    pool = {}
    in_topic = {}
    for t in dives if dives is not None else topic_dives(store, cfg):
        for x in t["papers"]:
            in_topic.setdefault(x["doi"], []).append({"slug": t["slug"], "role": x["role"]})
    for _, ps in catalog.gather(store, cfg):
        for p in ps:
            pool[p["doi"]] = p
    for p in store.where("user_mark IN ('selected','archived') OR cited=1"):
        pool[p["doi"]] = p
    if cfg.get("dashboard_corpus"):  # Starter Edition: the whole pre-loaded IEEE corpus is searchable under "All"
        for p in store.where("grp='ieee'"):
            pool.setdefault(p["doi"], p)
    keys, kwmap, recs = set(), catalog._kw_pillars(cfg), []
    for p in sorted(pool.values(), key=lambda p: p["doi"]):
        key = catalog.bib_key(p, keys)
        lin = p.get("lineage") or []
        digest = p.get("digest") or ""
        ym = relations._ym(p.get("published"))  # IEEE dates come as '2026-10-21', 'Oct. 2026', '14-18 June 2026'
        recs.append({
            "doi": p["doi"], "title": fetcher.tidy_tex(p["title"]), "venue": p["venue"], "venue_name": p.get("venue_name") or "",
            "date": f"{ym // 12}-{ym % 12 + 1:02d}" if ym else "", "raw_date": str(p.get("published") or ""),
            "year": catalog._year(p), "score": p.get("score") or 0,
            "authors": catalog._first_last(p), "all_authors": ", ".join((p.get("authors") or [])[:12]),
            # the automatic guess; the page shows the user's override (in the mark, "+si"/"+sim") on top of it
            "silicon_auto": catalog.silicon(p, cfg, auto=True), "pillar": catalog.pillar_of(p, kwmap) if p.get("grp") != "beyond" else 0,
            "beyond": p.get("grp") == "beyond", "lineage": bool(lin), "status": p.get("status"), "week": p.get("week") or "",
            "pin": catalog.PIN_TAG.get(p.get("pin"), ""), "catchup": bool(p.get("catchup")),
            # core radar = weekly candidates/reported (incl. catch-up, Beyond IEEE) and pinned papers; a
            # topic-dive-only paper is not core, so it stays out of 📋 Active and the pillar views
            "core": p.get("status") in ("candidate", "reported", "pinned") or bool(p.get("pin")),
            "topics": in_topic.get(p["doi"], []), "key": catalog.key_numbers(p),
            "hits": [h for h in p.get("hits") or [] if h not in ("silicon_verified", "simulation_only")][:10],
            "digest_html": md_to_html(digest) if digest else "<p class='muted'>No digest yet.</p>",
            "lineage_html": "".join(f"<p>📈 <strong>{'Extended from' if l['type'] == 'journal_extension_of' else 'Journal extension'}"
                                    f" {html.escape(str(l['venue']))} {l.get('year') or ''}:</strong> "
                                    f"<a href='https://doi.org/{l['doi']}'>{html.escape(l['title'])}</a> "
                                    f"<span class='muted'>({html.escape(l['signal'])})</span></p>" for l in lin),
            "abstract": p.get("abstract") or "", "mark": curation.mark_of(p), "note": p.get("user_note") or "",
            "bib": catalog.bib_entry(p, key)})
    return recs


def weekly_reports(cfg):
    """[{week, href}] of the weekly reports, newest first (each .md gets an .html next to it)."""
    d = Path(cfg["paths"]["weekly_dir"])
    return [{"week": f.stem, "href": f"{d.name}/{f.stem}.html"}
            for f in sorted(d.glob("????-W??.md"), reverse=True)] if d.exists() else []


# ---------- dashboard ----------

DASH_JS = r"""
const P = PAGE.papers, DIVES = PAGE.topics || [], DIVE = Object.fromEntries(DIVES.map(t => [t.slug, t]));
const BY_DOI = Object.fromEntries(P.map(p => [p.doi, p]));
// three tiers: 1 = the view (top bar) · 2 = 📅 Weekly Brief's pillar / 🌍 Beyond IEEE (wsel) or 🔎 Topic Dives'
// dive (topicSel) · 3 = the curation stage inside either (sub)
let view = PAGE.welcome ? 'all' : 'candidate', q = '', sortKey = 'date', sortDir = -1, topicSel = 'all', wsel = 'all',
  userSorted = false, sub = 'all';
let menu = '';  // which 📁 folder is open: 'more' (top bar), 'submore' (tier-3 status bar) or ''
const open = new Set(), tagOpen = new Set();
let tagsOn = false; try { tagsOn = localStorage.getItem('paper_radar_tags') === '1'; } catch (e) {}
// pillars come from config.json "pillars" (catalog.PILLARS): [{k: 'p1', n: 1, short: 'Pillar 1', name: '…'}]
const PILLARS = PAGE.pillars || [];
const GROUPS = PILLARS.map(x => [x.k, x.short, x.name]).concat([['beyond', '🌍 Beyond IEEE', '🌍 Beyond IEEE (Nature / Science): the rolling board']]);
const GROUPED = Object.fromEntries(PILLARS.map(x => [x.k, p => p.pillar === x.n]).concat([['beyond', p => p.beyond]]));
const GROUP_LABEL = Object.fromEntries(GROUPS.map(([k, l]) => [k, l]));
const WEEKS = PAGE.weeks || [];  // [{week, href}] newest first
let wkSel = WEEKS.length ? WEEKS[0].week : '';
// primary views stay on one row; the rest live in the 📁 More Views folder
const FILTERS = [['all','All'],['candidate','📋 Candidate'],['selected','✅ Selected'],['cite','⭐ To Cite'],
  ['weekly','📅 Weekly Brief'],['topic','🔎 Topic Dives'],
  ['silicon','🔬 Silicon-Verified Only'],['pinned','🏛️ Anchors & Pinned'],['lineage','📈 Journal Extensions'],['archived','🗄️ Archived']];
const TIERED = {weekly: true, topic: true};  // views with a tier-2 and a tier-3 bar
const VIEW_TITLE = {weekly: 'The radar\'s own papers: weekly + catch-up + pinned, by pillar, and 🌍 Beyond IEEE',
  topic: 'Papers from your --topic deep-dives, one banner per dive'};
// which views sit on the main bar and which in 📁 More Views, in order: the user's layout (drag & drop, or
// ⚙️ Customize views in the folder). Shared by every device (v2.12): saved by the sync server (POST /prefs →
// dashboard_prefs.json, also embedded in the page when it's generated) and in this browser; the newest (`t`) wins.
// Views added in a later version join their default place.
const LAYOUT_KEY = 'paper_radar_view_layout_v1';
const DEFAULT_MORE = ['silicon', 'pinned', 'lineage', 'archived'];
const DEFAULT_LAYOUT = {main: FILTERS.map(f => f[0]).filter(k => !DEFAULT_MORE.includes(k)), more: DEFAULT_MORE.slice(), t: 0};
let layout = loadLayout(), customizing = false;
function normLayout(l) {
  const known = new Set(FILTERS.map(f => f[0])), seen = new Set();
  // v2.15: the old top-level pillar / 🌍 Beyond buttons moved under 📅 Weekly Brief, which takes the first one's place
  let moved = false;
  const legacy = a => (Array.isArray(a) ? a : []).flatMap(k => /^p\d+$/.test(k) || k === 'beyond' ? (moved ? [] : (moved = true, ['weekly'])) : [k]);
  const clean = a => legacy(a).filter(k => known.has(k) && !seen.has(k) && seen.add(k));
  const out = l ? {main: clean(l.main), more: clean(l.more), t: Number(l.t) || 0} : {main: [], more: [], t: 0};
  for (const k of DEFAULT_LAYOUT.main) if (!seen.has(k)) { out.main.push(k); seen.add(k); }
  for (const k of DEFAULT_LAYOUT.more) if (!seen.has(k)) { out.more.push(k); seen.add(k); }
  return out;
}
function loadLayout() {
  let local = null; try { local = JSON.parse(localStorage.getItem(LAYOUT_KEY)); } catch (e) {}
  const shared = (PAGE.prefs || {}).layout;
  // a pre-v2.12 layout of this browser has no t: it still beats "no shared layout yet"
  const pick = !shared ? local : !local ? shared : ((Number(local.t) || 0) > (Number(shared.t) || 0) ? local : shared);
  return normLayout(pick);
}
function saveLayout() {
  layout.t = Date.now();
  try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); } catch (e) {}
  pushLayout(); render();
}
async function pushLayout() {
  if (!LIVE) return;  // offline: kept in this browser; sent on the next connection if it's still the newest
  try {
    await fetch(LIVE + '/prefs', {method: 'POST', headers: hdr(), body: JSON.stringify({prefs: {layout}}),
                                  signal: AbortSignal.timeout(8000)});
  } catch (e) {}
}
window.onLive = async () => {  // connected: adopt a newer shared layout, or share ours if it's newer
  try {
    const r = await (await fetch(LIVE + '/prefs', {headers: hdr(), signal: AbortSignal.timeout(4000), cache: 'no-store'})).json();
    const srv = (r.prefs || {}).layout, srvT = srv ? Number(srv.t) || 0 : -1;
    if (srv && srvT > (layout.t || 0)) {
      layout = normLayout(srv);
      try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); } catch (e) {}
      render();
    } else if ((layout.t || 0) > srvT || (!srv && localStorage.getItem(LAYOUT_KEY))) {
      if (!layout.t) layout.t = Date.now();  // first share of a pre-v2.12 layout
      pushLayout();
    }
  } catch (e) {}
};
function resetLayout() { layout = normLayout(null); saveLayout(); }
// move view k to `where` ('main' | 'more'), before view `before` (or at the end)
function moveView(k, where, before) {
  if (k === before) return;
  layout.main = layout.main.filter(x => x !== k); layout.more = layout.more.filter(x => x !== k);
  const a = layout[where], i = before ? a.indexOf(before) : -1;
  i < 0 ? a.push(k) : a.splice(i, 0, k);
  saveLayout();
}
function nudge(k, d) {  // ↑ / ↓ inside its own list
  const a = layout.main.includes(k) ? layout.main : layout.more, i = a.indexOf(k), j = i + d;
  if (j < 0 || j >= a.length) return;
  [a[i], a[j]] = [a[j], a[i]]; saveLayout();
}
// desktop drag & drop: a button onto a bar button (= before it), onto the bar (= end), onto 📁 (= into the folder)
function dragStart(e, k) { e.dataTransfer.setData('text/plain', k); e.dataTransfer.effectAllowed = 'move'; }
function dragOver(e) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }
function dropOn(e, where, before) {
  e.preventDefault(); e.stopPropagation();
  const k = e.dataTransfer.getData('text/plain');
  if (FILTERS.some(f => f[0] === k)) moveView(k, where, before);
}
// tier 3, inside 📅 Weekly Brief or 🔎 Topic Dives: one curation stage at a time ('all' = everything but 🗄️ Archived)
const SUBS = [['all','All'],['normal','📋 Candidate'],['selected','✅ Selected'],['cite','⭐ Cite'],
  ['pinned','🏛️ Anchors & Pinned'],['archived','🗄️ Archived']];
const SUB_MORE = ['pinned', 'archived'];
function reviewed(p) { return stageOf(p.doi) !== 'normal' || citedOf(p.doi); }
// tier 2: in 📅 Weekly Brief, the radar's own papers (weekly / catch-up / pinned) plus reviewed papers of a pillar
// or Beyond IEEE (w = 'all' or a group); in 🔎 Topic Dives, the papers of every dive or of one (t)
function inTier2(p, v, w, t) {
  if (v === 'weekly') return (p.core || (reviewed(p) && (p.pillar > 0 || p.beyond))) && (w === 'all' || GROUPED[w](p));
  if (v === 'topic') return t === 'all' ? p.topics.length > 0 : p.topics.some(x => x.slug === t);
  return false;
}
// tier 3: stage (st) and ⭐ (c) are independent: a ✅ Selected + ⭐ paper shows under both Selected and Cite
function stageOk(p, s) {
  const st = stageOf(p.doi), c = citedOf(p.doi);
  return s === 'all' ? st!=='archived' : s === 'pinned' ? !!p.pin && st!=='archived' : s === 'cite' ? c : st===s;
}
function matches(p) {
  const st = stageOf(p.doi), c = citedOf(p.doi);
  // the radar views show core papers (weekly / catch-up / pinned) and reviewed ones, never unreviewed topic-dive papers
  const radar = (p.core || st!=='normal' || c) && st!=='archived';
  const ok = TIERED[view] ? inTier2(p, view, wsel, topicSel) && stageOk(p, sub) : {all: true, candidate: st==='normal' && p.core,
    selected: st==='selected', cite: c, archived: st==='archived', silicon: siBadge(p.doi, p.silicon_auto)==='✅' && radar,
    pinned: !!p.pin && st!=='archived', lineage: p.lineage && radar}[view];
  if (!ok) return false;
  if (!q) return true;
  return (p.title+' '+p.all_authors+' '+p.venue+' '+p.venue_name+' '+p.key+' '+p.doi+' '+p.hits.join(' ')+' '+p.date+' '+
    noteOf(p.doi)+' '+p.topics.map(t => DIVE[t.slug] ? DIVE[t.slug].query : '').join(' ')).toLowerCase().includes(q);
}
function showTopic(slug) { if (view !== 'topic') sub = 'all'; view = 'topic'; topicSel = slug; userSorted = false; menu = ''; render(); }
function setView(k) { view = k; sub = 'all'; topicSel = 'all'; wsel = 'all'; userSorted = false; menu = ''; render(); }
function setW(w) { wsel = w; menu = ''; render(); }  // the tier-3 stage stays while switching pillars
function setSub(s) { sub = s; menu = ''; render(); }
function toggleMenu(m) { menu = menu === m ? '' : m; render(); }
// a 📁 folder: a button (highlighted, showing the active entry's name, when one of its entries is active) and,
// when open, a small menu below it
function folder(id, items, active, label, onpick) {
  const cur = items.find(([k]) => k === active);
  const btn = `<button class="btn ${cur?'on':''}" onclick="event.stopPropagation();toggleMenu('${id}')">📁 ${cur ? cur[1] : label} ▾</button>`;
  return `<span class="more">${btn}` + (menu === id ? `<span class="menu" onclick="event.stopPropagation()">` +
    items.map(([k, l, n]) => `<button class="btn ${active===k?'on':''}" onclick="${onpick}('${k}')">${l} <span class="muted count">${n}</span></button>`).join('') +
    `</span>` : '') + `</span>`;
}
// tier 3: the curation stage, counted within the current tier-2 selection
function statusBar() {
  const el = document.getElementById('statusbar');
  if (!TIERED[view] || (view === 'topic' && !DIVES.length)) { el.style.display = 'none'; el.innerHTML = ''; return; }
  el.style.display = '';
  const n = s => P.filter(p => inTier2(p, view, wsel, topicSel) && stageOk(p, s)).length;
  const scope = view === 'weekly' ? (wsel === 'all' ? 'All Weekly' : GROUP_LABEL[wsel])
                                  : (topicSel === 'all' ? 'All dives' : '🔎 ' + (DIVE[topicSel] || {}).short);
  el.innerHTML = `<span class="muted tlabel">${esc(scope)} · status:</span>` +
    SUBS.filter(([s]) => !SUB_MORE.includes(s)).map(([s, l]) =>
      `<button class="btn ${sub===s?'on':''}" ${s==='all'?'title="Everything except 🗄️ Archived"':''} onclick="setSub('${s}')">${l} <span class="muted count">${n(s)}</span></button>`).join('') +
    folder('submore', SUBS.filter(([s]) => SUB_MORE.includes(s)).map(([s, l]) => [s, l, n(s)]), sub, 'More', 'setSub');
}
// tier 2: 📅 Weekly Brief → All Weekly · Pillar 1–N · 🌍 Beyond IEEE + 📄 Open Weekly Report; 🔎 Topic Dives → dives
function tier2() {
  const el = document.getElementById('tier2');
  if (view === 'weekly') {
    el.style.display = '';
    const n = w => P.filter(p => inTier2(p, 'weekly', w, 'all') && stageOk(p, sub)).length;
    const b = (w, label, title) => `<button class="btn ${wsel===w?'on':''}" title="${escA(title)}" onclick="setW('${w}')">` +
      `${label} <span class="muted count">${n(w)}</span></button>`;
    el.innerHTML = `<span class="muted tlabel">📅 Weekly Brief:</span>` + b('all', 'All Weekly', 'Every pillar and 🌍 Beyond IEEE') +
      GROUPS.map(([k, l, t]) => b(k, l, t)).join('') + weekLink();
    return;
  }
  if (view === 'topic' && DIVES.length) {
    el.style.display = '';
    const pill = (slug, label, title) => `<button class="btn ${topicSel===slug?'on':''}" title="${escA(title)}" onclick="showTopic('${slug}')">${label}</button>`;
    el.innerHTML = `<span class="muted tlabel">🔎 Topic Dives:</span>` +
      pill('all', `All dives <span class="muted count">${DIVES.length}</span>`, 'every topic dive') + DIVES.map(t =>
      pill(t.slug, `🔎 ${esc(t.short)} <span class="muted">· ${t.date} · ${t.papers.length} papers</span>`, t.query) +
      (t.href ? `<a class="btn" href="${t.href}" target="_blank" title="${escA(t.query)}">📄 Open Topic Report</a>` : '')).join('');
    return;
  }
  el.style.display = 'none'; el.innerHTML = '';
}
function weekLink() {  // 📄 Open Weekly Report, the latest week by default; a selector when there are several
  if (!WEEKS.length) return '';
  const cur = WEEKS.find(w => w.week === wkSel) || WEEKS[0];
  const pick = WEEKS.length < 2 ? '' : `<select class="btn" title="Which week's report" onchange="wkSel=this.value;render()">` +
    WEEKS.map(w => `<option ${w.week===cur.week?'selected':''}>${w.week}</option>`).join('') + `</select>`;
  return `<span class="push"></span>${pick}<a class="btn" href="${cur.href}" target="_blank" title="The ${cur.week} weekly report">` +
    `📄 Open Weekly Report${WEEKS.length < 2 ? ' (' + cur.week + ')' : ''}</a>`;
}
function toggleTags() {
  tagsOn = !tagsOn; tagOpen.clear();
  try { localStorage.setItem('paper_radar_tags', tagsOn ? '1' : '0'); } catch (e) {}
  render();
}
function cmp(a, b) {
  const k = sortKey; let x = a[k], y = b[k];
  if (k === 'score') return (x - y) * sortDir;
  return String(x).localeCompare(String(y)) * sortDir;
}
function counts() {  // top bar: each view as a whole (tier 2 = all, tier 3 = All), regardless of the search
  const saved = [view, sub, wsel, topicSel, q];
  sub = 'all'; wsel = 'all'; topicSel = 'all'; q = '';
  const c = {}; for (const [k] of FILTERS) { view = k; c[k] = P.filter(matches).length; }
  [view, sub, wsel, topicSel, q] = saved;
  return c;
}
const LABEL = Object.fromEntries(FILTERS);
function viewBtn(k, c, where) {  // a draggable view button on the bar or in the folder
  return `<button class="btn ${view===k?'on':''}" draggable="true" ondragstart="dragStart(event,'${k}')" ` +
    `ondragover="dragOver(event)" ondrop="dropOn(event,'${where}','${k}')" ` +
    `${VIEW_TITLE[k] ? `title="${escA(VIEW_TITLE[k])}"` : ''} onclick="setView('${k}')">${LABEL[k]} <span class="muted count">${c[k]}</span></button>`;
}
function customizeRows(c) {  // ⚙️ Customize views: every view, with ↑ ↓ and bar ↔ folder (taps work on iPhone)
  const row = (k, where) => `<span class="crow"><span>${LABEL[k]} <span class="muted count">${c[k]}</span></span><span>` +
    `<button class="btn mini" onclick="nudge('${k}',-1)" title="Move up">↑</button>` +
    `<button class="btn mini" onclick="nudge('${k}',1)" title="Move down">↓</button>` +
    (where === 'main' ? `<button class="btn mini" onclick="moveView('${k}','more')" title="Into 📁 More Views">📁</button>`
                      : `<button class="btn mini" onclick="moveView('${k}','main')" title="Onto the main bar">📌</button>`) + `</span></span>`;
  return `<span class="muted">Main bar</span>` + layout.main.map(k => row(k, 'main')).join('') +
    `<span class="muted">📁 More Views</span>` + (layout.more.map(k => row(k, 'more')).join('') || '<span class="muted">(empty)</span>') +
    `<span class="crow"><button class="btn mini" onclick="customizing=false;render()">✓ Done</button>` +
    `<button class="btn mini" onclick="resetLayout()">↺ Reset default</button></span>`;
}
function mainBar(c) {
  const el = document.getElementById('filters');
  el.ondragover = dragOver; el.ondrop = e => dropOn(e, 'main');  // dropped on the bar's empty space: to its end
  const inMore = layout.more.includes(view);
  const fbtn = `<button class="btn ${inMore?'on':''}" ondragover="dragOver(event)" ondrop="dropOn(event,'more')" ` +
    `title="Drop a view here to put it in the folder" onclick="event.stopPropagation();toggleMenu('more')">📁 ` +
    `${inMore ? LABEL[view] + ` <span class="count">${c[view]}</span>` : 'More Views'} ▾</button>`;
  const menuHtml = menu !== 'more' ? '' : `<span class="menu" onclick="event.stopPropagation()" ondragover="dragOver(event)" ` +
    `ondrop="dropOn(event,'more')">` + (customizing ? customizeRows(c) :
      (layout.more.map(k => viewBtn(k, c, 'more')).join('') || '<span class="muted">Empty: drag a view here.</span>') +
      `<button class="btn mini" onclick="customizing=true;render()" title="Move any view between the bar and this folder">⚙️ Customize views</button>`) +
    `</span>`;
  el.innerHTML = layout.main.map(k => viewBtn(k, c, 'main')).join('') + `<span class="more">${fbtn}${menuHtml}</span>`;
}
let renderLater = false;
function render() {
  // never rebuild the table under a 🏷️ note being typed (live sync / re-probe would wipe it); its blur renders
  const ae = document.activeElement;
  if (ae && ae.classList && ae.classList.contains('note')) { renderLater = true; return; }
  renderLater = false;
  const c = counts();
  mainBar(c);
  const tb = document.getElementById('tagsbtn'); if (tb) tb.classList.toggle('on', tagsOn);
  tier2(); statusBar();
  let html = '', n = 0;
  if (view === 'topic') {
    // one banner per dive, 🏛️ classics then 🚀 recent, in the dive's relevance order unless a column was clicked
    const seen = new Set();
    for (const t of DIVES.filter(t => topicSel === 'all' || t.slug === topicSel)) {
      const groups = [['classic', '🏛️ Classics'], ['recent', '🚀 Recent SOTA']].map(([role, label]) => {
        let ps = t.papers.filter(x => x.role === role).map(x => BY_DOI[x.doi]).filter(p => p && matches(p));
        if (userSorted) ps = ps.slice().sort(cmp);
        return [label, ps];
      });
      const k = groups.reduce((s, [, ps]) => s + ps.length, 0);
      groups.forEach(([, ps]) => ps.forEach(p => seen.add(p.doi)));
      html += `<tr class="banner"><td colspan="8">🔎 Topic Dive: “${esc(t.query)}” (${t.date}) <span class="muted">· ${k} of ${t.papers.length} shown</span>` +
        (t.href ? ` · <a href="${t.href}" target="_blank">📄 Open Topic Report</a>` : '') + '</td></tr>';
      for (const [label, ps] of groups)
        if (ps.length) html += `<tr class="subbanner"><td colspan="8">${label} (${ps.length})</td></tr>` + ps.map(rowHtml).join('');
    }
    n = seen.size;
  } else {
    const rows = P.filter(matches).sort(cmp);
    n = rows.length;
    html = rows.map(rowHtml).join('');
  }
  document.getElementById('nrows').textContent = n;
  document.getElementById('tbody').innerHTML = html || '<tr><td colspan="8" class="muted">No papers match.</td></tr>';
}
function rowHtml(p) {
    const isOpen = open.has(p.doi);
    // [plain text for the tooltip, html]
    const tagList = [p.pin && [p.pin, `<span class="tag">${p.pin}</span>`], p.catchup && ['⏪ catch-up', '<span class="tag">⏪ catch-up</span>'],
      p.beyond && ['🌍 Beyond', '<span class="tag">🌍 Beyond</span>'], p.lineage && ['📈 Ext.', '<span class="tag">📈 Ext.</span>'],
      p.week && [p.week, `<span class="tag">${p.week}</span>`],
      ...p.topics.flatMap(t => { const d = DIVE[t.slug]; if (!d) return [];
        const role = t.role === 'classic' ? '🏛️ Classic' : '🚀 Recent';
        return [['🔎 ' + d.short, `<span class="tag tlink" title="${escA(d.query + ' (' + d.date + ')')}" onclick="event.stopPropagation();showTopic('${t.slug}')">🔎 ${esc(d.short)}</span>`],
                [role, `<span class="tag">${role}</span>`]]; })].filter(Boolean);
    // tags collapse into one "+N tags" pill (hover lists them, click expands this row) unless 🏷️ Tags is on
    const tags = !tagList.length ? '' : (tagsOn || tagOpen.has(p.doi)) ? tagList.map(t => t[1]).join('') :
      `<span class="tag tagpill" title="${escA(tagList.map(t => t[0]).join(' · '))}" ` +
      `onclick="event.stopPropagation();tagOpen.add('${p.doi}');render()">+${tagList.length} tag${tagList.length > 1 ? 's' : ''}</span>`;
    const note = noteOf(p.doi);  // the user's 🏷️ Tech note: always visible, even with the tags collapsed
    const main = `<tr class="paper ${citedOf(p.doi)?'cite':''}" id="r-${CSS.escape(p.doi)}" onclick="tg('${p.doi}')">` +
      `<td title="${esc(p.raw_date)}">${p.date}</td><td>${p.venue}</td><td><a href="https://doi.org/${p.doi}" target="_blank" onclick="event.stopPropagation()">${esc(p.title)}</a>` +
      (note ? `<div><span class="tag notetag" title="Your 🏷️ Tech note">🏷️ ${esc(note)}</span></div>` : '') +
      `<div class="muted">${esc(p.authors)} ${tags}</div></td><td class="count">${p.score}</td>` +
      `<td>${siCell(p.doi, p.silicon_auto, 'button')}</td><td class="hide-sm">${p.pillar||'–'}</td>` +
      `<td class="hide-sm muted">${esc(p.key)}</td><td data-cur="${p.doi}">${curButtons(p.doi)}</td></tr>`;
    const det = isOpen ? `<tr class="detail"><td colspan="8"><p class="muted">🔬 Silicon: ${siCell(p.doi, p.silicon_auto, 'button')} ` +
      `click to cycle ✅ Silicon-Verified → ⚠️ Simulation-Only → automatic (${esc(p.silicon_auto)})</p>` +
      `<p class="muted noteline">🏷️ Tech note: <input class="note" data-doi="${p.doi}" value="${escA(note)}" maxlength="200" ` +
      `placeholder="Key technique / takeaway (e.g. gate-leakage PTAT, floating inverter amp)…" onkeydown="noteKey(event, this)" ` +
      `onblur="saveNote(this)"> <span class="nstate" data-nstate="${p.doi}">${noteState(p.doi)}</span></p>${p.lineage_html}${p.digest_html}` +
      `<details><summary class="muted">Abstract · hits · BibTeX</summary><p>${esc(p.abstract)||'<span class=muted>No abstract.</span>'}</p>` +
      `<p class="muted">${p.hits.map(h=>'<span class=tag>'+esc(h)+'</span>').join('')}</p><pre>${esc(p.bib)}</pre></details></td></tr>` : '';
    return main + det;
}
function esc(s) { return String(s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function escA(s) { return esc(s).replace(/"/g, '&quot;'); }
function tg(doi) { open.has(doi) ? open.delete(doi) : open.add(doi); render(); }
// 🏷️ Tech note: saved on Enter or when the field loses focus; Esc restores the saved text
function noteKey(e, el) {
  if (e.key === 'Enter') { e.preventDefault(); el.blur(); }
  else if (e.key === 'Escape') { el.value = noteOf(el.dataset.doi); el.blur(); }
}
function saveNote(el) {
  const doi = el.dataset.doi;
  setTimeout(() => {  // after the blur, so render() isn't held back by the focused field
    if (cleanNote(el.value) !== noteOf(doi)) setNote(doi, el.value); else if (renderLater) render();
  }, 0);
}
function sortBy(k) { sortDir = sortKey === k ? -sortDir : (k==='title'||k==='venue' ? 1 : -1); sortKey = k; userSorted = true; render(); }
window.onMarkChange = (doi) => {
  if (!doi) return render();  // live sync refreshed all marks
  const r = document.getElementById('r-' + CSS.escape(doi));
  if (r && !matches(P.find(p => p.doi === doi))) { r.classList.add('fade'); setTimeout(render, 300); } else render();
};
document.getElementById('q').addEventListener('input', e => { q = e.target.value.toLowerCase().trim(); render(); });
document.addEventListener('click', () => { if (menu) { menu = ''; customizing = false; render(); } });  // click outside closes a 📁 folder
render();
"""


def write_dashboard(store, cfg, path):
    dives = topic_dives(store, cfg)
    recs = paper_records(store, cfg, dives)
    data = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "papers": recs, "topics": dives,
            "prefs": curation.load_prefs(cfg),  # the shared bar layout, for pages opened offline
            "marks": {r["doi"]: r["mark"] for r in recs}, "bib": {r["doi"]: r["bib"] for r in recs},
            "notes": {r["doi"]: r["note"] for r in recs if r["note"]},
            "pillars": [{"k": f"p{i}", "n": i, "short": f"Pillar {i}", "name": f"Pillar {i}: {n}"}  # tier 2 of 📅 Weekly Brief
                        for i, n in enumerate(cfg.get("pillars") or [], 1)],
            "weeks": weekly_reports(cfg), "sync": curation.page_sync_config(cfg),
            "welcome": not fetcher.pillars_ready(cfg)}
    n_store = store.db.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    welcome = (f"""<div class="welcome">👋 <b>Welcome to IC Paper Radar!</b> No research pillars are configured yet.
Open <code>README.md</code> to configure your research domains with AI"""
               + (f", or use the search bar below to browse the {n_store:,} IC papers in your store." if n_store else ".")
               + "</div>" if data["welcome"] else "")
    if not n_store:  # the same tip briefing.py prints
        welcome += f'<div class="welcome">💡 {html.escape(fetcher.STORE_TIP)}</div>'
    # tier 1 = views · tier 2 = 📅 Weekly Brief's pillars / 🔎 Topic Dives' dives · tier 3 = curation stage
    body = welcome + f"""<div class="filters" id="filters"></div>
<div class="filters topicbar" id="tier2" style="display:none"></div>
<div class="filters tier3" id="statusbar" style="display:none"></div>
<div class="filters"><input id="q" class="search" placeholder="Search title, author, venue, numbers, 🏷️ notes (e.g. 'SAR', 'PLL', 'nW', 'ISSCC')…">
<span class="muted" style="align-self:center"><span id="nrows" class="count">0</span> papers · generated {data['generated']} ·
<a href="INDEX.md">INDEX.md</a></span></div>
<main><div class="tablewrap"><table><thead><tr><th class="sort" onclick="sortBy('date')">Date</th>
<th class="sort" onclick="sortBy('venue')">Venue</th><th class="sort" onclick="sortBy('title')">Title</th>
<th class="sort" onclick="sortBy('score')">Score</th><th>Si</th><th class="hide-sm">Pillar</th><th class="hide-sm">Key numbers</th>
<th>Curation</th></tr></thead><tbody id="tbody"></tbody></table></div>
<p class="muted">Click a row for the full digest. Clicks are kept in this browser; <b>💾 Save Marks</b> sends them to the
Radar (curation_marks.json in output/ or Downloads), applied on the next run or <code>briefing.py --sync</code>.</p></main>"""
    tags_btn = ('<button id="tagsbtn" class="btn" onclick="toggleTags()" title="Show every row\'s tags '
                '(week, catch-up, anchor, 📈, topic) or collapse them into a +N pill">🏷️ Tags</button>')
    Path(path).write_text(_page("IC Paper Radar — Dashboard", "", _bar("📡 IC Paper Radar", extra=tags_btn), body, data, DASH_JS),
                          encoding="utf-8")
    return len(recs)


# ---------- report pages (.md → .html with real buttons) ----------

CUR_LINE = re.compile(r"^(\s*)- \*\*Curation\*\*: (?:\[[ xX]\] ✅ Select \| )?\[[ xX]\] ⭐ Cite \| \[[ xX]\] 🗄️ Archive "
                      r"<!-- doi:(\S+?) -->\s*$", re.M)


def write_report_html(md_path, store, home, sync):
    md = Path(md_path).read_text(encoding="utf-8")
    dois = CUR_LINE.findall(md)
    md = CUR_LINE.sub(lambda m: f"{m[1]}@@CUR:{m[2]}@@", md)
    body = md_to_html(md)
    body = re.sub(r"(?:<p>)?@@CUR:(\S+?)@@(?:</p>)?", r'<div data-cur="\1"></div>', body)
    marks, bib, keys = {}, {}, set()
    for _, d in dois:
        p = store.get(d)
        if p:
            marks[d] = curation.mark_of(p)
            bib[d] = catalog.bib_entry(p, catalog.bib_key(p, keys))
    title = (re.match(r"#\s+(.*)", md) or [None, Path(md_path).stem])[1]
    page = _page(title, "", _bar("📡 " + Path(md_path).stem, home),
                 f'<main><article class="report">{body}</article></main>',
                 {"marks": marks, "bib": bib, "sync": sync}, "", mermaid="```mermaid" in md)
    out = Path(md_path).with_suffix(".html")
    out.write_text(page, encoding="utf-8")
    return out


def write_all(store, cfg, log=print):
    root = Path(cfg["paths"]["onedrive_root"])
    n = write_dashboard(store, cfg, root / "DASHBOARD.html")
    pages = 0
    for d in (Path(cfg["paths"]["weekly_dir"]), Path(cfg["paths"]["topic_dir"])):
        for f in d.glob("*.md") if d.exists() else []:
            write_report_html(f, store, "../DASHBOARD.html", curation.page_sync_config(cfg))
            pages += 1
    write_phone_link(cfg)
    log(f"HTML: DASHBOARD.html ({n} papers) + {pages} report pages")


def write_phone_link(cfg):
    """IC_Paper_Radar/Open_on_iPhone.txt: the one-time key link for opening the pages from radar_sync_server.py
    (iPhone over Tailscale/LAN). Private like the pages themselves, which embed the same token."""
    sc = curation.page_sync_config(cfg)
    hosts = [h for h in sc["hosts"] if not h.startswith("127.")]
    if not hosts:  # Starter Edition: no sync server configured
        return
    lines = ["IC Paper Radar on a phone or another computer (served by radar_sync_server.py on this computer).", "",
             "1. Open this link once in Safari (it stores a key cookie, then drops the key from the address):"]
    lines += [f"   http://{h}:{sc['port']}/?k={sc['token']}" for h in hosts]
    lines += ["2. Bookmark / 'Add to Home Screen' the page it opens:"] + [f"   http://{h}:{sc['port']}/" for h in hosts]
    lines += ["", "The phone must reach this computer on the network (same Wi-Fi, or a VPN such as Tailscale; the",
              "computer must be reachable). Don't share the key link: it lets a browser change your marks.",
              "A new key (delete .radar_token) invalidates old ones."]
    (Path(cfg["paths"]["onedrive_root"]) / "Open_on_iPhone.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
