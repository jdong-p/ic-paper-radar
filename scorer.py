"""v3.0 scoring boosters on top of the rule score (fetcher.score): bibliographic coupling and a personal taste
model learnt from your own marks. Pure stdlib, 0 API calls, 0 tokens. briefing.py calls prepare(store, cfg) once
per run; until then (or in another process) the boosters are simply off and the score is the v2 rule score.

  coupling:+3   the paper's references share ≥ coupling_min_shared (2) works with the references of one of your
                core papers (🏛️ anchors, 📌 pinned, ✅ selected, ⭐ cited): a new paper with 0 citations that builds on
                the same literature as your favourites. Bibliographic coupling (Kessler 1963).
  taste:+N      −2 … +4 from a smoothed Bernoulli Naive Bayes over title + abstract words, trained on your
                positives (✅ selected, ⭐ cited, 📌/🏛️ pinned) vs negatives (🗄️ archived), once both have at least
                taste_min_examples (8). The idea of arxiv-sanity-lite's per-user classifier (Karpathy, MIT),
                done with log-odds instead of an SVM so it needs no packages.
Settings (config.json → "scoring", all optional): title_multiplier (1.5, used by fetcher.score), coupling_bonus
(3), coupling_min_shared (2), taste_min_examples (8), taste (true).
"""
import math
import re
from collections import Counter

CTX = {"core": [], "model": None, "pos": 0, "neg": 0}
STOP = set("""a an and are as at be been by can for from has have in into is it its of on or our over such that the
their them then there these this those to under using via was we were which while with within without both new also
paper results result show shows shown proposed propose present presents presented based work approach method methods
two one three first high low large small different various several than more most very however thus""".split())
WORD = re.compile(r"[a-zµ][a-z0-9µ]+(?:-[a-z0-9µ]+)*")


def settings(cfg):
    sc = cfg.get("scoring") or {}
    return {"title_multiplier": sc.get("title_multiplier", 1.5), "coupling_bonus": sc.get("coupling_bonus", 3),
            "coupling_min_shared": sc.get("coupling_min_shared", 2), "taste_min_examples": sc.get("taste_min_examples", 8),
            "taste": sc.get("taste", True) is not False}


def tokens(p):
    """The distinct content words of title + abstract (lower case, ≥ 3 letters, no stop words)."""
    text = f"{p.get('title') or ''} {p.get('abstract') or ''}".lower()
    return {t for t in WORD.findall(text) if len(t) >= 3 and t not in STOP}


POS_SQL = "user_mark='selected' OR cited=1 OR pin IS NOT NULL"
NEG_SQL = "user_mark='archived' AND COALESCE(cited,0)=0 AND pin IS NULL"


def train(pos, neg, alpha=1.0):
    """Per word: log P(word | positive) − log P(word | negative), Laplace-smoothed document frequencies. Words
    seen in fewer than 2 examples are dropped (one paper's quirks are not taste)."""
    dp, dn = Counter(), Counter()
    for p in pos:
        dp.update(tokens(p))
    for p in neg:
        dn.update(tokens(p))
    n_p, n_n = len(pos), len(neg)
    llr = {}
    for t in set(dp) | set(dn):
        if dp[t] + dn[t] >= 2:
            llr[t] = math.log((dp[t] + alpha) / (n_p + 2 * alpha)) - math.log((dn[t] + alpha) / (n_n + 2 * alpha))
    return {"llr": llr}


def taste(p, model):
    """−2 … +4: the words' mean log-odds (scaled by √n so long abstracts don't saturate) through a logistic;
    P = 0.5 → 0, P → 1 → +4, P → 0 → −2. Fewer than 3 known words → 0."""
    known = [model["llr"][t] for t in tokens(p) if t in model["llr"]]
    if len(known) < 3:
        return 0
    s = sum(known) / math.sqrt(len(known))
    pr = 1 / (1 + math.exp(-max(min(s, 30), -30)))
    return max(-2, min(4, round(8 * (pr - 0.5)) if pr >= 0.5 else round(4 * (pr - 0.5))))


def prepare(store, cfg, log=print):
    """Load the coupling core and train the taste model from this store's marks (once per run)."""
    st = settings(cfg)
    anchors = [a.lower() for a in cfg.get("anchors") or []]
    sql = POS_SQL + (f" OR lower(doi) IN ({','.join('?' * len(anchors))})" if anchors else "")
    core = store.where(sql, tuple(anchors))
    CTX["core"] = [(p["doi"], frozenset(p.get("refs") or [])) for p in core if len(p.get("refs") or []) >= 3]
    pos, neg = store.where(POS_SQL), store.where(NEG_SQL)
    CTX["pos"], CTX["neg"] = len(pos), len(neg)
    need = st["taste_min_examples"]
    CTX["model"] = train(pos, neg) if st["taste"] and len(pos) >= need and len(neg) >= need else None
    log(f"Scoring v3: coupling core {len(CTX['core'])} papers; taste model "
        + (f"on ({len(pos)}+ / {len(neg)}− marks, {len(CTX['model']['llr'])} words)" if CTX["model"]
           else f"off ({len(pos)}+ / {len(neg)}− marks; needs {need} of each)"))
    return CTX


def reset():
    CTX.update(core=[], model=None, pos=0, neg=0)


def extra(p, cfg):
    """[(label, points)] for fetcher.score: coupling and taste (empty until prepare() ran)."""
    out = []
    refs = p.get("refs") or []
    if refs and CTX["core"]:
        st = settings(cfg)
        r = set(refs)
        best = max((len(r & c) for d, c in CTX["core"] if d != p.get("doi")), default=0)
        if best >= st["coupling_min_shared"]:
            out.append(("coupling", int(st["coupling_bonus"])))
    if CTX["model"]:
        t = taste(p, CTX["model"])
        if t:
            out.append(("taste", t))
    return out
