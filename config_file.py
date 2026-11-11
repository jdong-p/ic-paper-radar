"""Settings files: config.json is yours (Git ignores it), config.example.json is the tracked starter template.

load() first creates config.json as a copy of config.example.json when there is none (the first run of any
command), then lays your config.json over the template, so a `git pull` that adds a key to
config.example.json gives you its default without touching your file, and never conflicts with it.

Merge rules: dicts merge key by key and your values win; lists, strings and numbers are taken whole from
your file. Maps whose keys are your own data (OWN_MAPS: keyword weights, synonyms, the conference mapping)
are taken whole too, so a default entry you deleted never comes back.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
EXAMPLE = HERE / "config.example.json"
OWN_MAPS = {("positive_keywords",), ("topic", "synonyms"), ("lineage", "conferences")}


def ensure():
    """Copy config.example.json to config.json when config.json is missing; never overwrites. True if created."""
    if CONFIG.exists() or not EXAMPLE.exists():
        return False
    try:
        with open(CONFIG, "xb") as fh:  # exclusive: two first runs at once can't clobber each other
            fh.write(EXAMPLE.read_bytes())
    except FileExistsError:
        return False
    sys.stderr.write("[INFO] Created config.json from config.example.json. Your settings go in config.json "
                     "(Git ignores it, so `git pull` never overwrites it).\n")
    return True


def merge(base, mine, path=()):
    """`mine` laid over `base` (see the module docstring); neither argument is modified."""
    if not (isinstance(base, dict) and isinstance(mine, dict)) or path in OWN_MAPS:
        return mine
    out = dict(base)
    for k, v in mine.items():
        out[k] = merge(base[k], v, path + (k,)) if k in base else v
    return out


def load():
    """Your config.json over the config.example.json defaults. Raises on a missing or invalid config.json."""
    ensure()
    mine = json.loads(CONFIG.read_text(encoding="utf-8"))
    if not EXAMPLE.exists():
        return mine
    return merge(json.loads(EXAMPLE.read_text(encoding="utf-8")), mine)
