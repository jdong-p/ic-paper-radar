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
                Cold start (v3.0.1): most people curate by selecting and simply leave the rest, so with fewer than
                8 🗄️ archived papers the negatives are topped up (to taste_max_negatives, 24) with passed-over
                papers: reported in a finalized week, never marked, cited or pinned, lowest score and oldest
                first, each counting taste_implicit_weight (0.5) of an explicit archive.
Settings (config.json → "scoring", all optional): title_multiplier (1.5, used by fetcher.score), coupling_bonus
(3), coupling_min_shared (2), taste_min_examples (8), taste_max_negatives (24), taste_implicit_weight (0.5),
taste (true).
"""
import math
import re
from collections import Counter

CTX = {"core": [], "model": None, "pos": 0, "neg": 0, "implicit": 0}
STOP = set("""a an and are as at be been by can for from has have in into is it its of on or our over such that the
their them then there these this those to under using via was we were which while with within without both new also
paper results result show shows shown proposed propose present presents presented based work approach method methods
two one three first high low large small different various several than more most very however thus""".split())
WORD = re.compile(r"[a-zµ][a-z0-9µ]+(?:-[a-z0-9µ]+)*")


def settings(cfg):
    sc = cfg.get("scoring") or {}
    return {"title_multiplier": sc.get("title_multiplier", 1.5), "coupling_bonus": sc.get("coupling_bonus", 3),
            "coupling_min_shared": sc.get("coupling_min_shared", 2), "taste_min_examples": sc.get("taste_min_examples", 8),
            "taste_max_negatives": sc.get("taste_max_negatives", 24),
            "taste_implicit_weight": sc.get("taste_implicit_weight", 0.5),
            "taste": sc.get("taste", True) is not False}


def tokens(p):
    """The distinct content words of title + abstract (lower case, ≥ 3 letters, no stop words)."""
    text = f"{p.get('title') or ''} {p.get('abstract') or ''}".lower()
    return {t for t in WORD.findall(text) if len(t) >= 3 and t not in STOP}


POS_SQL = "user_mark='selected' OR cited=1 OR pin IS NOT NULL"
NEG_SQL = "user_mark='archived' AND COALESCE(cited,0)=0 AND pin IS NULL"
# passed over: shown in a finalized week and left alone (no ✅ ⭐ 🗄️ 📌): implicit negatives for the cold start
IMPLICIT_SQL = "status='reported' AND COALESCE(user_mark,'normal')='normal' AND COALESCE(cited,0)=0 AND pin IS NULL"


def train(pos, neg, alpha=1.0, implicit=(), weight=0.5):
    """Per word: log P(word | positive) − log P(word | negative), Laplace-smoothed document frequencies. Words
    seen in fewer than 2 examples are dropped (one paper's quirks are not taste). `implicit` negatives count
    `weight` each, in the word counts and in the number of negatives."""
    dp, dn = Counter(), Counter()
    for p in pos:
        dp.update(tokens(p))
    for p in neg:
        dn.update(tokens(p))
    for p in implicit:
        for t in tokens(p):
            dn[t] += weight
    n_p, n_n = len(pos), len(neg) + weight * len(implicit)
    llr = {}
    for t in set(dp) | set(dn):
        if dp[t] + dn[t] >= 2:
            llr[t] = math.log((dp[t] + alpha) / (n_p + 2 * alpha)) - math.log((dn[t] + alpha) / (n_n + 2 * alpha))
    model = {"llr": llr, "offset": 0.0}
    # calibration: the decision point halfway between the mean raw score of the positives and of the negatives,
    # so a paper unlike both lands near 0 instead of being pulled down by the larger positive class
    rp = [x for x in (_raw(p, model) for p in pos) if x is not None]
    rn = [x for x in (_raw(p, model) for p in list(neg) + list(implicit)) if x is not None]
    if rp and rn:
        model["offset"] = (sum(rp) / len(rp) + sum(rn) / len(rn)) / 2
    return model


def _raw(p, model):
    """The words' summed log-odds / √n (so long abstracts don't saturate); None with fewer than 3 known words."""
    known = [model["llr"][t] for t in tokens(p) if t in model["llr"]]
    return sum(known) / math.sqrt(len(known)) if len(known) >= 3 else None


def taste(p, model):
    """−2 … +4: the calibrated raw score (minus the model's offset) through a logistic; P = 0.5 → 0, P → 1 → +4,
    P → 0 → −2. Fewer than 3 known words → 0."""
    s = _raw(p, model)
    if s is None:
        return 0
    s -= model.get("offset", 0.0)
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
    need = st["taste_min_examples"]
    implicit = []
    if len(neg) < need and len(pos) >= need:  # cold start: top up with passed-over papers
        implicit = store.where(f"{IMPLICIT_SQL} ORDER BY score ASC, first_seen ASC LIMIT ?",
                               (max(0, st["taste_max_negatives"] - len(neg)),))
    CTX["pos"], CTX["neg"], CTX["implicit"] = len(pos), len(neg), len(implicit)
    on = st["taste"] and len(pos) >= need and len(neg) + len(implicit) >= need
    CTX["model"] = train(pos, neg, implicit=implicit, weight=st["taste_implicit_weight"]) if on else None
    neg_txt = f"{len(neg)}−" + (f" + {len(implicit)} passed over (×{st['taste_implicit_weight']})" if implicit else "")
    log(f"Scoring v3: coupling core {len(CTX['core'])} papers; taste model "
        + (f"on ({len(pos)}+ / {neg_txt}, {len(CTX['model']['llr'])} words)" if CTX["model"]
           else f"off ({len(pos)}+ / {neg_txt}; needs {need} of each)"))
    return CTX


def reset():
    CTX.update(core=[], model=None, pos=0, neg=0, implicit=0)


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
