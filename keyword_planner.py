"""0-token keyword & weight planner (v3.0.5): from a few anchor DOIs and rough seed words per pillar, propose a
weighted positive_keywords matrix, metric regexes, a negative_override and VIP authors. Pure stdlib, no LLM.

  python briefing.py --plan-keywords "ring amplifier, pipelined ADC, low power; second pillar's words"
  POST /api/plan_keywords  ← {"pillars": [{"name", "seeds": [...]}], "anchors": [doi, ...]}   (STARTUP.html 🪄)

Per pillar:
  1. Seed corpus S: the anchors that fit the pillar (from the store; missing ones from OpenAlex, never written
     to the store), the store's best FTS5 hits for the seed words and the pillar name, and store papers that
     cite an anchor or share ≥ 2 references with one.
  2. Candidates: 1–3 word phrases (no stop word at either end), ALL-CAPS acronyms (3–6 letters, case
     sensitive like fetcher._kw_hit), the papers' index terms, the seeds, and unit patterns found in the
     abstracts matched against REGEX_LIBRARY (clean re:<label>::<regex> keys). Variants that score.py treats
     as one keyword (hyphen / space, plural -s/-es, case unless ALL CAPS) are merged.
  3. Weights from specificity: lift = share of S papers with the term (a title hit counts twice) ÷ share of
     the whole store with it (B, FTS5 phrase counts):
       +5 core target: a multi-word seed, or a top-lift phrase of the pillar name / anchor titles
       +4 specific topology / acronym · +3 mechanism or metric regex · +2 supporting term
       +1 broad context: in > 5 % of the store (e.g. low-power, sensor, CMOS): never more than +1
     Terms that are common anyway are capped (> 2 % of the store: +2, 1–2 %: +3; > 15 %: dropped unless a seed).
  4. Calibration: the planned weights (with the keywords already in config.json) are summed over the whole store
     from each term's FTS5 matches; while more than max(3 × the seed papers, 3 % of the store) papers outside the
     seed corpus would reach min_score − 1 (the silicon bonus and title boost come on top), the non-seed term that
     pulls in the most of them is lowered one step. The preview shows how many papers would pass.
  5. negative_override from the +5 / +4 core phrases; VIP authors ranked over the anchors (×3) and top hits.
The plan is a suggestion: STARTUP.html shows it in a preview to pick from; nothing is written by this module.
"""
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_PILLARS, MAX_SEEDS, MAX_ANCHORS = 9, 20, 30
BROAD_SHARE = 0.05          # in more than 5 % of the store → broad context, +1 at most
S_LIMIT, HITS_PER_TERM = 60, 25
KEEP_PER_PILLAR = 36
VIP_FOCUS = 0.2             # a suggested VIP author has ≥ 20 % of their store papers in the seed corpus
DOI_RX = re.compile(r"^10\.\d{4,9}/\S{1,200}$")
TOKEN_RX = re.compile(r"(?<![\w.µμ/-])[A-Za-zµμ][A-Za-z0-9µμ]*(?:-[A-Za-z0-9µμ]+)*")  # not "th" of "4th-Order"
# a phrase never ends in an adverb or a participle / adjective ("dynamically biased", "TDC-Assisted")
WEAK_END = re.compile(r"(ly|ed|ent|ant|ive|able|ible|ful|less|ous|ic)$")
CAP = {5: 4, 4: 12, 3: 10, 2: 8, 1: 4}  # suggestions per weight and pillar (seeds and metric regexes come on top)
ACRONYM_RX = re.compile(r"^[A-Z][A-Z0-9]{2,5}s?$")
CHUNK_RX = re.compile(r"[.,;:()\[\]{}!?\"“”'’/×=<>±~≈]|\s[-–—]\s|\band\b|\bor\b|\bwith\b|\bfor\b|\busing\b|\bvia\b")
STOP = set("""a an and are as at be been being by can could for from has have had in into is it its of on or our
over such that the their them then there these this those to under using via was we were which while with within
without both new also than more most very however thus here than per each other all any between based both but
not only one two three four five first second third after before during same up down out off about above below
we us they he she i you your may might must shall should will would do does did done""".split())
GENERIC = set("""proposed propose proposes present presents presented paper work approach method methods technique
techniques design designs designed circuit circuits chip chips measured measurement measurements result results
show shows shown demonstrate demonstrates demonstrated achieve achieves achieved achieving novel high low new system
systems performance technology process implementation implemented fabricated architecture prototype efficiency
power area energy consumption operation operating range respectively compared conventional order improved improve
improves improvement enables enable enabled reduce reduces reduced reduction increase increases increased provide
provides provided allow allows applications application analysis model models data time large small different various
several total overall typical better best higher lower state art use used make made obtained obtain number numbers
level levels type types mode modes based study studies article letter brief experimental experiments simulation
simulations simulated value values following well key main major significant significantly consuming consumes
consume featuring features feature employing employs employ eliminate eliminates eliminating requires require
required requiring leading leads often solutions solution driving robustness merit background input inputs output
outputs signal signals operate operates achieving enabling providing offering offers offer addresses address
compared comparing exhibits exhibit maintain maintains maintaining maintained realized realizes realize utilizes
utilize utilizing yields yield yielding issues issue problem problems challenge challenges limitation limitations
drawback drawbacks suppress suppresses suppressing suppressed mitigate mitigates mitigating""".split())
ACRO_STOP = {"IEEE", "THE", "AND", "FOR", "DOI", "USA", "II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII",
             "NOT", "WITH", "FROM", "THIS", "ALL", "ONE", "TWO", "NEW"}

# unit patterns: (label, regex used as the keyword, what it measures). The regex is the keyword itself
# (re:<label>::<regex>, case sensitive like every re: key); found in ≥ 2 seed papers (or an anchor) → proposed.
REGEX_LIBRARY = [
    ("nW-power", r"\d+(\.\d+)?\s?nW\b", "nanowatt power"),
    ("pW-power", r"\d+(\.\d+)?\s?pW\b", "picowatt power"),
    ("µW-power", r"\d+(\.\d+)?\s?(µ|μ|u)W\b", "microwatt power"),
    ("fJ-energy", r"\d+(\.\d+)?\s?fJ\b", "femtojoule energy (e.g. FoM per conversion step)"),
    ("pJ-energy", r"\d+(\.\d+)?\s?pJ\b", "picojoule energy"),
    ("ppm", r"\d+(\.\d+)?\s?ppm\b", "ppm accuracy / drift"),
    ("±°C-inaccuracy", r"±\s?\d+(\.\d+)?\s?°C", "temperature inaccuracy"),
    ("dB-metric", r"\d+(\.\d+)?\s?dB\b", "a dB figure (SNDR, PSRR, CMRR …)"),
    ("MS/s-rate", r"\d+(\.\d+)?\s?[kMG]S/s\b", "sampling rate"),
    ("fs-jitter", r"\d+(\.\d+)?\s?fs\b", "femtosecond jitter"),
    ("nV/√Hz-noise", r"nV\s?/\s?(√|sqrt)\s?Hz", "input-referred noise density"),
    ("GHz", r"\d+(\.\d+)?\s?GHz\b", "a GHz frequency"),
    ("Gb/s-rate", r"\d+(\.\d+)?\s?Gb/s\b", "data rate"),
    ("molar-conc", r"\d+(\.\d+)?\s?(µ|μ|u|n|p)M\b", "molar concentration (µM, nM, pM)"),
    ("mg/kg-dose", r"\d+(\.\d+)?\s?mg/kg\b", "dose"),
    ("wt%", r"\d+(\.\d+)?\s?wt\s?%", "weight percent"),
    ("eV", r"\d+(\.\d+)?\s?eV\b", "electron-volt energy (band gap, …)"),
    ("mAh/g", r"\d+(\.\d+)?\s?mAh\s?g", "specific capacity"),
]


# ---------------------------------------------------------------- text helpers

def _variant_key(term):
    """The key score.py would treat as the same keyword: lower case (unless ALL CAPS), hyphen = space, a final
    plural -s / -es dropped."""
    t = term.strip()
    words = re.split(r"[\s-]+", t)
    if words and len(words[-1]) > 3 and not words[-1].isupper():
        w = words[-1]
        if re.search(r"(ches|shes|sses|xes|zes)$", w.lower()):
            words[-1] = w[:-2]
        elif w.lower().endswith("s") and not w.lower().endswith(("ss", "us", "is")):
            words[-1] = w[:-1]
    elif words and ACRONYM_RX.match(words[-1]) and words[-1].endswith("s"):
        words[-1] = words[-1][:-1]
    k = " ".join(words)
    return k if k.isupper() else k.lower()


def _inside(short, long):
    """Is `short` a whole-word part of `long`, hyphens counting as spaces ('shaping' in 'noise-shaping SAR')?"""
    f = lambda t: " " + re.sub(r"[\s-]+", " ", _variant_key(t).lower()) + " "
    return f(short) in f(long)


def _is_acronym(tok):
    base = tok[:-1] if tok.endswith("s") and tok[:-1].isupper() else tok
    return bool(ACRONYM_RX.match(tok)) and sum(c.isupper() for c in base) >= 2 and base not in ACRO_STOP \
        and not base.isdigit()


def _bad_end(tok, generic, last=False):
    l = tok.lower()
    if l in STOP or l in generic or len(l) < 2 or l.isdigit():
        return True
    tail = l.rsplit("-", 1)[-1]
    return bool(last and not tok.isupper() and WEAK_END.search(tail) and tail not in ("ic", "ent"))


def _surface(w):
    """'Pipelined-SAR' → 'pipelined-SAR', 'Ring' → 'ring': Title Case is lowered, acronyms / inner capitals kept."""
    return "-".join(x if x.isupper() or any(c.isupper() for c in x[1:]) else x.lower() for x in w.split("-"))


def candidates(text, generic):
    """{variant key: Counter(surface forms)} of the 1–3 word phrases and acronyms in one text."""
    out = defaultdict(Counter)
    for chunk in CHUNK_RX.split(text or ""):
        toks = [t for t in TOKEN_RX.findall(chunk) if len(t) >= 2]
        for i, t in enumerate(toks):
            if _is_acronym(t):
                out[_variant_key(t)][t[:-1] if t.endswith("s") and t[:-1].isupper() else t] += 1
            for n in (1, 2, 3):
                g = toks[i:i + n]
                if len(g) < n or _bad_end(g[0], generic) or _bad_end(g[-1], generic, last=True)                         or g[0].lower().endswith("ly"):
                    continue
                if n == 1 and (len(t) < 5 or "-" not in t and t.lower() in generic or t.isupper()):
                    continue  # single words: longer technical words only (acronyms are counted above)
                if any(w.lower() in STOP for w in g[1:-1]):
                    continue
                surface = " ".join(_surface(w) for w in g)
                out[_variant_key(surface)][surface] += 1
    return out


def _paper_text(p):
    return f"{p.get('title') or ''}. {p.get('abstract') or ''}"


# ---------------------------------------------------------------- inputs

def pillar_names(cfg):
    if cfg.get("pillars"):
        return [str(x) for x in cfg["pillars"]]
    import catalog
    return [catalog.PILLARS[k] for k in sorted(catalog.PILLARS) if k]


def clean_request(req, cfg):
    """{"pillars": [{"name", "seeds"}], "anchors": [...]} → (pillars, anchors), validated; missing parts come from
    the config (its pillar names and anchors)."""
    req = req if isinstance(req, dict) else {}
    ps = req.get("pillars")
    if ps is None:
        ps = [{"name": n, "seeds": []} for n in pillar_names(cfg)]
    if not isinstance(ps, list) or not ps or len(ps) > MAX_PILLARS:
        raise ValueError(f"pillars: 1 to {MAX_PILLARS} pillars, each {{name, seeds}}")
    pillars = []
    for i, p in enumerate(ps, 1):
        if not isinstance(p, dict) or not isinstance(p.get("name", ""), str):
            raise ValueError(f"pillar {i}: expected {{name, seeds}}")
        seeds = p.get("seeds") or []
        if isinstance(seeds, str):
            seeds = re.split(r"[,;\n]+", seeds)
        if not isinstance(seeds, list) or len(seeds) > MAX_SEEDS or not all(isinstance(s, str) for s in seeds):
            raise ValueError(f"pillar {i}: seeds must be a list of at most {MAX_SEEDS} words / phrases")
        seeds = [re.sub(r"\s+", " ", s).strip()[:80] for s in seeds if s.strip()]
        name = re.sub(r"\s+", " ", p.get("name") or "").strip()[:160] or f"Pillar {i}"
        pillars.append({"n": i, "name": name, "seeds": list(dict.fromkeys(seeds))})
    an = req.get("anchors")
    an = (cfg.get("anchors") or []) if an is None else an
    if not isinstance(an, list) or len(an) > MAX_ANCHORS:
        raise ValueError(f"anchors: a list of at most {MAX_ANCHORS} DOIs")
    anchors = []
    for d in an:
        d = re.sub(r"^https?://(dx\.)?doi\.org/", "", str(d or "").strip(), flags=re.I).lower()
        if d and not DOI_RX.match(d):
            raise ValueError(f"anchors: {d!r} is not a DOI")
        if d:
            anchors.append(d)
    return pillars, list(dict.fromkeys(anchors))


def _anchor_papers(store, cfg, dois, log):
    """[(paper, source)] for the anchor DOIs: the store's row, else OpenAlex (not written anywhere)."""
    out, missing = {}, []
    for d in dois:
        p = store.get(d)
        if p:
            out[d] = (p, "store")
        else:
            missing.append(d)
    if missing:
        try:
            import fetcher
            import pins
            works = fetcher.openalex_by_doi(missing, cfg, pins.OA_SELECT, log=lambda m: None)
            for d, w in works.items():
                out[d] = (pins._from_oa(w, cfg), "openalex")
        except Exception as e:
            log(f"  anchors from OpenAlex: {e}")
    return [(out[d][0], out[d][1]) if d in out else ({"doi": d, "title": "", "abstract": ""}, "missing")
            for d in dois]


def _name_phrases(name, generic):
    """'Pillar 1 — Temperature Sensors & Precision/Low-Power References' → ['Temperature Sensors', 'Precision',
    'Low-Power References'] (FTS terms and 'in the pillar name' flags)."""
    name = re.sub(r"^Pillar\s*\d+\s*[—–:-]\s*", "", name)
    parts = [p.strip() for p in re.split(r"[&/,;:()+]|\s[-–—]\s|\band\b", name) if p.strip()]
    return [p for p in parts if any(w.lower() not in generic and w.lower() not in STOP for w in TOKEN_RX.findall(p))
            and len(TOKEN_RX.findall(p)) <= 4]


# ---------------------------------------------------------------- the planner

class _Background:
    """Which store papers contain a term (title, abstract, index terms), as a set of rowids: FTS5 phrase matches,
    else a scan of normalized texts; regexes by scanning the raw texts. df = the size of that set."""

    def __init__(self, store):
        import store as store_mod
        self.store, self.sm = store, store_mod
        self.n = store.db.execute("SELECT COUNT(*) FROM papers WHERE COALESCE(title,'') != ''").fetchone()[0] or 1
        self.cache, self._texts, self._norm = {}, None, None

    def texts(self):
        if self._texts is None:
            self._texts = [(r, f"{t or ''} {a or ''} {i or ''}") for r, t, a, i in
                           self.store.db.execute("SELECT rowid, title, abstract, index_terms FROM papers")]
        return self._texts

    def ids(self, term):
        if term in self.cache:
            return self.cache[term]
        out = frozenset()
        if term.startswith("re:"):
            try:
                rx = re.compile(term.split("::", 1)[1])
                out = frozenset(r for r, t in self.texts() if rx.search(t))
            except re.error:
                pass
        elif getattr(self.store, "fts", False):
            q = self.sm.fts_query(term, prefix=True)
            if q:
                try:
                    out = frozenset(r for (r,) in self.store.db.execute(
                        "SELECT rowid FROM papers_fts WHERE papers_fts MATCH ?", (f"{{title abstract index_terms}} : ({q})",)))
                except Exception:
                    out = self._scan(term)
        else:
            out = self._scan(term)
        self.cache[term] = out
        return out

    def df(self, term):
        return len(self.ids(term))

    def author_n(self, name):
        """How many store papers list this author (FTS5 on the authors column; 0 = unknown)."""
        words = re.findall(r"[^\W\d_]+", name)
        q = '"' + " ".join(words) + '"' if words else ""  # one phrase: the name's words next to each other
        if not q or not getattr(self.store, "fts", False):
            return 0
        try:
            return self.store.db.execute("SELECT COUNT(*) FROM papers_fts WHERE papers_fts MATCH ?",
                                         (f"{{authors}} : ({q})",)).fetchone()[0]
        except Exception:
            return 0

    def _scan(self, term):
        if self._norm is None:
            self._norm = [(r, " " + re.sub(r"[^a-z0-9µμ]+", " ", t.lower()) + " ") for r, t in self.texts()]
        k = " " + re.sub(r"[^a-z0-9µμ]+", " ", _variant_key(term).lower()).strip() + " "
        return frozenset(r for r, t in self._norm if k in t)


def _seed_corpus(store, pillar, anchors, generic, log):
    """{doi: (paper, why)} for one pillar: its anchors, FTS hits for the seeds + name phrases, citing / coupled."""
    import store as store_mod
    S = {}
    for a in anchors:
        S[a["doi"]] = (a, "anchor")
    terms = pillar["seeds"] + _name_phrases(pillar["name"], generic)
    if terms:
        try:
            match = store_mod.fts_any(terms) if getattr(store, "fts", False) else None
            hits = store.fts_search(" ".join(terms), limit=S_LIMIT, match=match) if match else \
                [p for t in terms for p in store.fts_search(t, limit=HITS_PER_TERM)]
        except Exception as e:
            log(f"  search: {e}")
            hits = []
        for p in hits:
            if len(S) >= S_LIMIT:
                break
            S.setdefault(p["doi"], (p, "search"))
    refs = Counter()
    for a in anchors:
        for k in ([f"oa:{a['oa_id']}"] if a.get("oa_id") else []) + [f"doi:{a['doi']}"]:
            for (d,) in store.db.execute("SELECT doi FROM papers WHERE refs LIKE ? LIMIT 15", (f'%"{k}"%',)):
                if len(S) < S_LIMIT + 15:
                    S.setdefault(d, (store.get(d), "cites an anchor"))
        for r in (a.get("refs") or [])[:30]:
            for (d,) in store.db.execute("SELECT doi FROM papers WHERE refs LIKE ? LIMIT 200", (f'%"{r}"%',)):
                refs[d] += 1
    for d, n in refs.most_common(15):
        if n >= 2 and d not in S:
            S[d] = (store.get(d), "shares references with an anchor")
    return {d: v for d, v in S.items() if v[0]}


def _assign_anchors(anchor_papers, pillars, generic):
    """{pillar n: [paper]}: each anchor goes to the pillar(s) whose seeds / name phrases it mentions most; one that
    mentions none goes to every pillar."""
    out = {p["n"]: [] for p in pillars}
    for a in anchor_papers:
        text = _paper_text(a)
        import fetcher
        sc = {p["n"]: sum(1 for t in p["seeds"] + _name_phrases(p["name"], generic) if fetcher._kw_hit(t, text))
              for p in pillars}
        best = max(sc.values()) if sc else 0
        for n, v in sc.items():
            if v == best:
                out[n].append(a)
    return out


def _weight(c, n_s, bg):
    """(weight, why) for one candidate, or (None, …) to drop it; then capped by how common it is in the store."""
    w, why = _weight0(c, n_s, bg)
    share_b = c["b"] / bg.n
    if w is None or c["kind"] == "seed" or w >= 5 or w <= 2:
        return w, why
    cap = 2 if share_b > 0.02 else 3 if share_b > 0.01 else w
    if cap < w:
        return cap, f"capped at +{cap}: in {share_b:.1%} of the store · {why}"
    return w, why


def _weight0(c, n_s, bg):
    share_s = c["s"] / max(n_s, 1)
    share_b = c["b"] / bg.n
    lift = (c["s_score"] / max(n_s, 1)) / ((c["b"] + 1) / (bg.n + 1))
    c["lift"] = round(lift, 1)
    words = len(re.split(r"[\s-]+", c["k"])) if not c["k"].startswith("re:") else 1
    if share_b > BROAD_SHARE:
        if share_b > 0.15 and c["kind"] != "seed":
            return None, ""
        if c["kind"] == "seed" or share_s >= 0.15:
            return 1, f"broad: in {share_b:.0%} of the store, so +1 at most"
        return None, ""
    if c["kind"] == "regex":
        return 3, "metric regex found in the seed papers"
    if c["kind"] == "seed":
        if words >= 2:
            return 5, "your seed phrase"
        return (4 if lift >= 6 or c["acronym"] else 3), "your seed word"
    if c["s"] < 2 and not c["in_anchor_title"]:
        return None, ""
    if words >= 2 and lift >= 20 and (c["in_name"] or c["in_anchor_title"] >= 2) and c["s"] >= max(4, 0.1 * n_s):
        return 5, "defines the pillar name / anchor titles"
    lone = words == 1 and not c["acronym"] and "-" not in c["k"]
    if lone and (lift < 4 or (c["k"].lower().endswith("ing") and lift < 8)):
        return (1, "context word") if c["s"] >= 3 and share_s >= 0.2 else (None, "")
    if c["s"] >= 3 and ((lift >= 10 and (words >= 2 or c["acronym"])) or (c["acronym"] and lift >= 6)):
        return 4, "specific: frequent here, rare in the store"
    if lift >= 4 and c["s"] >= 2:
        return 3, "mechanism / technical term"
    if lift >= 2:
        return 2, "supporting term"
    if c["s"] >= 3:
        return 1, "context word"
    return None, ""


def plan(cfg, store, pillars, anchors, log=print):
    """The plan (see the module docstring) as a JSON-ready dict."""
    import fetcher
    generic = GENERIC | {str(w).lower() for w in (cfg.get("topic") or {}).get("generic_words") or []}
    bg = _Background(store)
    anchor_papers = _anchor_papers(store, cfg, anchors, log)
    by_pillar = _assign_anchors([p for p, src in anchor_papers if src != "missing"], pillars, generic)
    have = {fetcher._kw_norm(k): (k, w) for k, w in (cfg.get("positive_keywords") or {}).items() if not k.startswith("_")}
    out_p, authors, author_papers = [], defaultdict(Counter), defaultdict(set)
    best_of = {}  # variant key → (pillar n, share) for the one-pillar-per-keyword rule
    s_dois = set()  # every pillar's seed corpus (calibration keeps those passing)
    for pl in pillars:
        S = _seed_corpus(store, pl, by_pillar[pl["n"]], generic, log)
        n_s = len(S)
        name_keys = {_variant_key(x) for x in _name_phrases(pl["name"], generic)}
        name_text = pl["name"]
        anchor_title_list = [a.get("title") or "" for a in by_pillar[pl["n"]]]
        anchor_titles = " ".join(anchor_title_list)
        stats = {}
        for doi, (p, why) in S.items():
            title_c = candidates(p.get("title") or "", generic)
            body_c = candidates(_paper_text(p), generic)
            for k, forms in body_c.items():
                st = stats.setdefault(k, {"forms": Counter(), "s": 0, "s_score": 0})
                st["forms"].update(forms)
                st["s"] += 1
                st["s_score"] += 2 if k in title_c else 1
            for term in p.get("index_terms") or []:
                k = _variant_key(str(term))
                st = stats.setdefault(k, {"forms": Counter(), "s": 0, "s_score": 0, "index": True})
                st["forms"][" ".join(_surface(w) for w in str(term).split())] += 1
                st["index"] = True
            w = 3 if why == "anchor" else 1
            for a in p.get("authors") or []:
                if a:
                    authors[fetcher._name_key(a)][a] += w
                    author_papers[fetcher._name_key(a)].add(doi)
        cands = []
        for k, st in stats.items():
            if st["s"] < 2 and not fetcher._kw_hit(k, anchor_titles):
                continue
            surface = st["forms"].most_common(1)[0][0]
            cands.append({"k": surface, "kind": "acronym" if _is_acronym(surface) else ("index" if st.get("index") else "phrase"),
                          "s": st["s"], "s_score": st["s_score"], "acronym": _is_acronym(surface)})
        for seed in pl["seeds"]:  # the seeds always count, even when no seed paper has them
            k = _variant_key(seed)
            st = stats.get(k, {"s": 0, "s_score": 0})
            cands = [c for c in cands if _variant_key(c["k"]) != k]
            cands.append({"k": seed, "kind": "seed", "s": st["s"], "s_score": st["s_score"], "acronym": seed.isupper()})
        texts = [_paper_text(p) for p, _ in S.values()]
        anchor_texts = [_paper_text(a) for a in by_pillar[pl["n"]]]
        for label, rx, what in REGEX_LIBRARY:
            c_rx = re.compile(rx)
            s = sum(1 for t in texts if c_rx.search(t))
            if s >= 2 or any(c_rx.search(t) for t in anchor_texts):
                cands.append({"k": f"re:{label}::{rx}", "kind": "regex", "s": s, "s_score": s, "acronym": False,
                              "what": what})
        # background counts only for what can still make it (the cheapest filter first)
        cands.sort(key=lambda c: (c["kind"] not in ("seed", "regex"), -c["s_score"]))
        rows = []
        for c in cands[:400]:
            c["b"] = bg.df(c["k"])
            c["in_name"] = _variant_key(c["k"]) in name_keys or (not c["k"].startswith("re:") and fetcher._kw_hit(c["k"], name_text) is not None)
            c["in_anchor_title"] = 0 if c["k"].startswith("re:") else \
                sum(1 for t in anchor_title_list if fetcher._kw_hit(c["k"], t))
            w, why = _weight(c, n_s, bg)
            if w is None:
                continue
            ex = have.get(fetcher._kw_norm(c["k"]))
            rows.append({"k": c["k"], "w": w, "kind": c["kind"], "why": why, "s": c["s"], "n_s": n_s, "b": c["b"],
                         "store": bg.n, "lift": c["lift"], "exists": bool(ex), "current": ex[1] if ex else None,
                         **({"what": c["what"]} if c.get("what") else {})})
        # seeds first, then by weight and coverage; a phrase that contains an already kept keyword of weight ≥ 3
        # would score the same papers twice, and one inside a kept phrase that covers as many papers adds nothing
        rows.sort(key=lambda r: (r["kind"] != "seed", -r["w"], -r["s"], -r["lift"], r["k"].lower()))
        kept, per_w, n_rx = [], Counter(), 0
        for r in rows:
            if r["kind"] == "regex":
                if n_rx < 4:
                    kept.append(r)
                    n_rx += 1
                continue
            if r["kind"] != "seed":
                if any(o["kind"] != "regex" and len(o["k"]) < len(r["k"]) and (o["w"] >= 3 or o["w"] >= r["w"])
                       and _inside(o["k"], r["k"]) for o in kept):
                    continue
                if any(o["kind"] != "regex" and len(o["k"]) > len(r["k"]) and o["w"] >= r["w"]
                       and o["s"] >= 0.8 * r["s"] and _inside(r["k"], o["k"]) for o in kept):
                    continue
                if per_w[r["w"]] >= CAP[r["w"]]:
                    continue
                per_w[r["w"]] += 1
            kept.append(r)
        rows = sorted(kept, key=lambda r: (-r["w"], r["kind"] != "seed", -r["s"]))[:KEEP_PER_PILLAR + 8]
        for r in rows:
            vk = _variant_key(r["k"]) if not r["k"].startswith("re:") else r["k"]
            share = r["s"] / max(n_s, 1)
            if vk not in best_of or share > best_of[vk][1]:
                best_of[vk] = (pl["n"], share)
        s_dois.update(S)
        out_p.append({"n": pl["n"], "name": pl["name"], "seeds": pl["seeds"], "seed_papers": n_s,
                      "anchors": [a["doi"] for a in by_pillar[pl["n"]]],
                      "examples": [p.get("title") for p, why in list(S.values())[:6]],
                      "keywords": rows})
    for op in out_p:  # one keyword, one pillar: where it is most frequent
        op["keywords"] = [r for r in op["keywords"]
                          if best_of.get(_variant_key(r["k"]) if not r["k"].startswith("re:") else r["k"], (op["n"],))[0] == op["n"]]
    s_ids = set()
    dl = list(s_dois)
    for i in range(0, len(dl), 500):
        chunk = dl[i:i + 500]
        s_ids |= {r for (r,) in store.db.execute(f"SELECT rowid FROM papers WHERE doi IN ({','.join('?' * len(chunk))})", chunk)}
    calib = _calibrate(out_p, bg, s_ids, cfg)
    # negative_override from the core phrases
    core = []
    for op in out_p:
        core += [r["k"] for r in op["keywords"] if r["w"] >= 4 and not r["k"].startswith("re:")
                 and (r["kind"] == "seed" or (r["s"] >= 3 and len(re.split(r"[\s-]+", r["k"])) >= 2))][:4]
    core = list(dict.fromkeys(core))[:10]
    body = "|".join(r"[\s-]".join(re.escape(w) for w in re.split(r"[\s-]+", k)) for k in core)
    suggest = f"(?i){body}" if body else ""
    cur = (cfg.get("negative_override") or "").strip()
    merged = (f"{cur}|{body}" if cur.startswith("(?i)") else f"{cur}|{suggest}") if cur and body else (cur or suggest)
    for x in (suggest, merged):
        if x:
            re.compile(x)
    # VIP authors: frequent across the anchors (×3) and seed papers, and focused: a prolific author whose papers
    # are mostly outside the seed corpus would add vip_boost to all of them (off-topic floods), so ≥ VIP_FOCUS of
    # their store papers must be seed papers
    vips_have = cfg.get("vip_authors") or []
    vip = []
    for key, forms in sorted(authors.items(), key=lambda kv: -sum(kv[1].values()))[:40]:
        total = sum(forms.values())
        name = max(forms, key=lambda f: (forms[f], len(f)))
        if total < 2 or not key[1] or len(key[1]) < 2 or fetcher.vip_match([name], vips_have):
            continue
        n_s, n_b = len(author_papers[key]), bg.author_n(name)
        focus = n_s / n_b if n_b else 1.0
        if focus < VIP_FOCUS:
            continue
        vip.append({"name": name, "score": total, "seed_papers": n_s, "store": n_b, "focus": round(min(focus, 1.0), 2)})
    vip = sorted(vip, key=lambda v: -v["score"] * v["focus"])[:8]
    return {"ok": True, "store_papers": bg.n, "fts": bool(getattr(store, "fts", False)),
            "anchors": [{"doi": p["doi"], "title": p.get("title") or "", "source": src} for p, src in anchor_papers],
            "pillars": out_p,
            "negative_override": {"terms": core, "suggest": suggest, "current": cur, "merged": merged},
            "vip_authors": vip, "min_score": cfg.get("min_score", 5), "calibration": calib}


def _calibrate(out_p, bg, s_ids, cfg):
    """Lower the weights that would flood the radar (see the module docstring, step 4). Edits the rows in place;
    returns {pass, share, seed_cover, seed_papers, budget, before, lowered}."""
    import fetcher
    thr = (cfg.get("min_score", 5) or 5) - 1  # the silicon bonus (+1) and the title boost come on top
    terms = [(r, bg.ids(r["k"])) for op in out_p for r in op["keywords"]]
    planned = {fetcher._kw_norm(r["k"]) for r, _ in terms}
    base = Counter()
    for k, w in list((cfg.get("positive_keywords") or {}).items())[:400]:
        if not k.startswith("_") and w and fetcher._kw_norm(k) not in planned:
            for i in bg.ids(k):
                base[i] += w
    budget = max(3 * len(s_ids), int(0.03 * bg.n))
    base_pass = {i for i, v in base.items() if v >= thr}  # what the keywords already in config.json pass anyway

    def passing():
        sc = Counter(base)
        for r, ids in terms:
            if r["w"]:
                for i in ids:
                    sc[i] += r["w"]
        return {i for i, v in sc.items() if v >= thr}

    now = passing()
    before, steps = len(now), 0
    while len(now - base_pass - s_ids) > budget and steps < 120:  # only what the plan adds counts
        out = now - base_pass - s_ids
        best, most = None, 0
        for r, ids in terms:
            if r["kind"] == "seed" or r["w"] <= 0 or r["w"] >= 5:
                continue
            e = len(ids & out)
            if e > most:
                best, most = r, e
        if best is None:
            break
        best.setdefault("w0", best["w"])
        best["w"] -= 1
        steps += 1
        now = passing()
    lowered = 0
    for r, _ in terms:
        if "w0" in r and r["w"] != r["w0"]:
            lowered += 1
            r["why"] = f"lowered from +{r.pop('w0')} so it doesn't pull in off-topic papers · {r['why']}"
    for op in out_p:
        op["keywords"] = [r for r in op["keywords"] if r["w"] > 0]
    return {"pass": len(now), "share": round(len(now) / bg.n, 3), "seed_papers": len(s_ids),
            "base": len(base_pass), "added": len(now - base_pass),
            "seed_cover": round(len(now & s_ids) / max(1, len(s_ids)), 2), "budget": budget, "before": before,
            "lowered": lowered, "threshold": thr}


def open_store(cfg):
    import store as store_mod
    p = HERE / cfg["paths"]["store_file"]
    if not p.exists():
        raise ValueError("the paper store is empty: fetch papers first (🌐 Fetch New Papers Now) or add anchors")
    return store_mod.Store(p)


def api(cfg, req, log=lambda m: None):
    """POST /api/plan_keywords → the plan (ok: false and an error for bad input)."""
    try:
        pillars, anchors = clean_request(req, cfg)
    except ValueError as e:
        return 400, {"ok": False, "error": str(e)}
    if not any(p["seeds"] for p in pillars) and not anchors:
        return 400, {"ok": False, "error": "add a few rough seed words or 2–5 anchor DOIs first"}
    try:
        s = open_store(cfg)
    except ValueError as e:
        return 400, {"ok": False, "error": str(e)}
    try:
        return 200, plan(cfg, s, pillars, anchors, log)
    finally:
        s.db.close()


def cli(cfg, seeds_arg, log=print):
    """briefing.py --plan-keywords [SEEDS]: SEEDS = the rough words of pillar 1; those of pillar 2; … Prints the
    plan and a config.json fragment, and writes it to _system/keyword_plan.json."""
    names = pillar_names(cfg)
    groups = [g for g in (seeds_arg or "").split(";")]
    if not names:
        names = [f"Pillar {i}" for i in range(1, max(1, len([g for g in groups if g.strip()])) + 1)]
    req = {"pillars": [{"name": n, "seeds": groups[i] if i < len(groups) else ""} for i, n in enumerate(names)]}
    code, res = api(cfg, req, log)
    if code != 200:
        log(f"[plan-keywords] {res['error']}")
        return 2
    log(f"🪄 Keyword plan from {len(res['anchors'])} anchors and your seeds · store: {res['store_papers']} papers "
        f"({'FTS5' if res['fts'] else 'scan'}) · min_score {res['min_score']}")
    for a in res["anchors"]:
        log(f"   anchor {a['doi']}: {a['source']}{' · ' + a['title'][:80] if a['title'] else ''}")
    frag = {}
    for p in res["pillars"]:
        log(f"\nP{p['n']} {p['name']}  ({p['seed_papers']} seed papers)")
        frag[f"_pillar{p['n']}_{re.sub(r'[^a-z0-9]+', '_', p['name'].lower()).strip('_')[:30]}"] = 0
        for r in p["keywords"]:
            label = r["k"][3:].split("::")[0] + "  (regex)" if r["k"].startswith("re:") else r["k"]
            log(f"   +{r['w']}  {label:<42} {r['why']} · {r['s']}/{r['n_s']} seed papers · "
                f"{r['b']}/{r['store']} in store" + ("  [already yours]" if r["exists"] else ""))
            if not r["exists"]:
                frag[r["k"]] = r["w"]
    cb = res["calibration"]
    log(f"\nCalibration: with these weights ≈ {cb['pass']} papers ({cb['share']:.1%} of the store) reach "
        f"min_score − 1, covering {cb['seed_cover']:.0%} of the {cb['seed_papers']} seed papers"
        + (f"; your current keywords alone pass {cb['base']}, the plan adds {cb['added']}" if cb["base"] else "")
        + (f" ({cb['lowered']} weights lowered; {cb['before']} before)" if cb["lowered"] else ""))
    no = res["negative_override"]
    log(f"\nnegative_override: {no['merged'] or '(none)'}")
    log("VIP authors: " + (", ".join(f"{v['name']} ({v['seed_papers']}/{v['store']} papers in your seed set)"
                                     for v in res["vip_authors"]) or "(none)"))
    log("\nconfig.json fragment (positive_keywords to add):\n" + json.dumps(frag, ensure_ascii=False, indent=2))
    try:
        import curation
        f = curation.system_dir(cfg) / "keyword_plan.json"
        f.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"\nFull plan: {f} · or use 🪄 Auto-Plan in STARTUP.html to pick and apply.")
    except Exception:
        pass
    return 0
