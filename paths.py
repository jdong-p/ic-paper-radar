"""Output locations. With "portable_mode": true (Starter Edition) every output, system and archive path
lives under ./output next to these scripts, whatever config.json's "paths" say, so the folder works
unchanged on Windows and macOS. "marks_extra_dirs" may use ~ (e.g. "~/Downloads").
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "output"


def resolve(cfg):
    p = cfg.setdefault("paths", {})
    p["marks_extra_dirs"] = [str(Path(d).expanduser()) for d in p.get("marks_extra_dirs", [])]
    if not cfg.get("portable_mode"):
        return cfg
    p.update(onedrive_root=str(OUTPUT), weekly_dir=str(OUTPUT / "Weekly_Briefings"),
             topic_dir=str(OUTPUT / "Topic_Dives"), system_dir=str(OUTPUT / "_system"),
             archive_dir=str(OUTPUT / "_archive"), pdf_dir=str(OUTPUT / "PDFs"))
    p.setdefault("store_file", "paper_store.sqlite")  # relative to the scripts
    p.setdefault("pdf_queue_file", "pending_pdf_queue.json")
    for k in ("onedrive_root", "weekly_dir", "topic_dir", "system_dir", "archive_dir"):
        Path(p[k]).mkdir(parents=True, exist_ok=True)
    return cfg
