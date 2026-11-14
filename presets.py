"""Domain presets (v3.0): the radar for fields beyond IC design. config.json "domain_preset" picks one:

  ic_ece       IC & Solid-State Circuits (default): IEEE + OpenAlex + Crossref (+ arXiv); ✅ Silicon-Verified / ⚠️ Simulation-Only
  bio_med      Biology, Biomedical & Medicine: PubMed E-utilities + bioRxiv/medRxiv + OpenAlex; 🧬 Wet-Lab / In-Vivo / 💻 In-Silico Only
  chem_mat     Chemistry, Materials & ChemE: OpenAlex + Crossref; 🧪 Exp. Synthesized / 💻 DFT / Sim Only
  general_eng  Robotics, Control & General Engineering: IEEE + OpenAlex (+ arXiv); 🛠️ Hardware Tested / ⚠️ Simulation-Only

The preset decides the evidence badge everywhere (dashboard, reports, master table). The internal values stay
silicon_verified / simulation_only, so marks, overlays and shared files are the same in every domain.
apply_changes() (STARTUP.html → 🧭 Domain preset → Apply) also writes the preset's evidence cues
(verification.silicon_cues / simulation_cues) and, only if asked, replaces the venue list with the preset's
starter venues (PubMed / bioRxiv / Crossref-by-ISSN journals) and catch_up.flagship_venues.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT = "ic_ece"


def _journal(short, name, *issn):
    return {"short": short, "name": name, "issn": list(issn), "type": "journal"}


PRESETS = {
    "ic_ece": {
        "label": "IC & Solid-State Circuits", "icon": "🔬", "sources": "IEEE API + OpenAlex + Crossref (+ arXiv)",
        "badge": {"si_icon": "✅", "sim_icon": "⚠️ sim", "si": "Silicon-Verified", "sim": "Simulation-Only",
                  "view": "🔬 Silicon-Verified Only", "head": "🔬 Silicon", "column": "Silicon"},
        "verification": None,  # the IC cues of config.example.json (the default config)
        "venues": None,        # config.example.json's IEEE venues
    },
    "bio_med": {
        "label": "Biology, Biomedical & Medicine", "icon": "🧬", "sources": "PubMed E-utilities + bioRxiv / medRxiv + OpenAlex",
        "badge": {"si_icon": "🧬", "sim_icon": "💻 in-silico", "si": "Wet-Lab / In-Vivo", "sim": "In-Silico Only",
                  "view": "🧬 Wet-Lab / In-Vivo Only", "head": "🧬 Evidence", "column": "Evidence"},
        "verification": {
            "silicon_cues": ["in vivo", "in vitro", "mice", "mouse model", "rats", "patients", "participants", "cohort",
                             "clinical trial", "randomized", "cell line", "cell lines", "knockout", "western blot",
                             "immunohistochemistry", "flow cytometry", "organoid", "biopsy", "animal model"],
            "simulation_cues": ["in silico", "computational model", "molecular docking", "molecular dynamics simulation",
                                "bioinformatic analysis", "simulation study", "simulated data", "virtual screening"]},
        "venues": [
            {"short": "PubMed", "name": "PubMed (NCBI E-utilities)", "source": "pubmed", "query": "", "max_results": 200,
             "type": "journal", "issn": []},
            {"short": "bioRxiv", "name": "bioRxiv", "source": "biorxiv", "categories": [], "max_pages": 10, "type": "journal", "issn": []},
            {"short": "medRxiv", "name": "medRxiv", "source": "medrxiv", "categories": [], "max_pages": 10, "type": "journal", "issn": []},
            _journal("Nat BME", "Nature Biomedical Engineering", "2157-846X"),
            _journal("Sci Transl Med", "Science Translational Medicine", "1946-6234", "1946-6242"),
            _journal("Cell", "Cell", "0092-8674", "1097-4172"),
        ],
    },
    "chem_mat": {
        "label": "Chemistry, Materials & ChemE", "icon": "🧪", "sources": "OpenAlex + Crossref",
        "badge": {"si_icon": "🧪", "sim_icon": "💻 sim", "si": "Exp. Synthesized", "sim": "DFT / Sim Only",
                  "view": "🧪 Exp. Synthesized Only", "head": "🧪 Evidence", "column": "Evidence"},
        "verification": {
            "silicon_cues": ["synthesized", "synthesised", "fabricated", "characterized", "characterised", "XRD",
                             "X-ray diffraction", "SEM", "TEM", "NMR", "XPS", "yield of", "experimentally", "measured"],
            "simulation_cues": ["density functional theory", "DFT calculations", "first-principles", "first principles",
                                "molecular dynamics", "ab initio", "machine-learned potential", "computational screening"]},
        "venues": [
            _journal("JACS", "Journal of the American Chemical Society", "0002-7863", "1520-5126"),
            _journal("Nat Mater", "Nature Materials", "1476-1122", "1476-4660"),
            _journal("Adv Mater", "Advanced Materials", "0935-9648", "1521-4095"),
            _journal("Chem Mater", "Chemistry of Materials", "0897-4756", "1520-5002"),
            _journal("ACS Nano", "ACS Nano", "1936-0851", "1936-086X"),
        ],
    },
    "general_eng": {
        "label": "Robotics, Control & General Engineering", "icon": "🛠️", "sources": "IEEE (Crossref) + OpenAlex (+ arXiv)",
        "badge": {"si_icon": "🛠️", "sim_icon": "⚠️ sim", "si": "Hardware Tested", "sim": "Simulation-Only",
                  "view": "🛠️ Hardware Tested Only", "head": "🛠️ Validation", "column": "Validation"},
        "verification": {
            "silicon_cues": ["real robot", "hardware experiments", "hardware experiment", "real-world experiments",
                             "field test", "field tests", "prototype", "testbed", "experimentally validated",
                             "physical robot", "on hardware", "measured"],
            "simulation_cues": ["in simulation", "simulation results", "simulated environment", "Gazebo", "MuJoCo",
                                "Simulink", "numerical simulations", "simulations show"]},
        "venues": [
            _journal("T-RO", "IEEE Transactions on Robotics", "1552-3098", "1941-0468"),
            _journal("RA-L", "IEEE Robotics and Automation Letters", "2377-3766"),
            _journal("TAC", "IEEE Transactions on Automatic Control", "0018-9286", "1558-2523"),
            _journal("Sci Robot", "Science Robotics", "2470-9476"),
        ],
    },
}


def key(cfg):
    k = (cfg or {}).get("domain_preset") or DEFAULT
    return k if k in PRESETS else DEFAULT


def badge(cfg):
    return PRESETS[key(cfg)]["badge"]


def icon(value, cfg):
    """silicon_verified / simulation_only / '' → the preset's badge (e.g. ✅, ⚠️ sim, ❔)."""
    b = badge(cfg)
    return {"silicon_verified": b["si_icon"], "simulation_only": b["sim_icon"]}.get(value or "", "❔")


def _example():
    try:
        return json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def summary():
    """For STARTUP.html: [{key, label, icon, sources, badge, venues: [short…]}]."""
    out = []
    for k, p in PRESETS.items():
        ven = p["venues"] if p["venues"] is not None else _example().get("venues") or []
        out.append({"key": k, "label": p["label"], "icon": p["icon"], "sources": p["sources"], "badge": p["badge"],
                    "venues": [v["short"] for v in ven]})
    return out


def apply_changes(k, cfg, replace_venues=False):
    """[(config path, value)] that switch this radar to preset k: domain_preset, the evidence cues (bonus and
    penalty kept) and, with replace_venues, the venue list + catch_up.flagship_venues. ValueError if unknown."""
    if k not in PRESETS:
        raise ValueError(f"unknown domain preset {k!r} (one of {', '.join(PRESETS)})")
    p, ex = PRESETS[k], _example()
    out = [(["domain_preset"], k)]
    ver = p["verification"] or {kk: (ex.get("verification") or {}).get(kk) for kk in ("silicon_cues", "simulation_cues")}
    for kk in ("silicon_cues", "simulation_cues"):
        if ver.get(kk):
            out.append((["verification", kk], list(ver[kk])))
    if replace_venues:
        ven = p["venues"] if p["venues"] is not None else ex.get("venues")
        if not ven:
            raise ValueError("this radar has no template venue list for that preset (config.example.json)")
        out.append((["venues"], json.loads(json.dumps(ven))))
        out.append((["catch_up", "flagship_venues"], [v["short"] for v in ven if not v.get("source")][:6]))
    return out
