"""Execution-host guard.

With "portable_mode": true (the default) the scripts run on any Windows, macOS or Linux computer and
write everything to ./output (see paths.py). If you dedicate one machine to the radar, set
"portable_mode": false and "host_lock": "<that machine's hostname>" in config.json: the scripts then
refuse to run anywhere else (useful when the folder is synced to several computers).
"""
import socket
import sys

import config_file


def _config():
    try:
        return config_file.load()  # also creates config.json from config.example.json on the first run
    except Exception:
        return {}


def portable_mode():
    return _config().get("portable_mode") is True


def ensure_minisforum_env():
    cfg = _config()
    if cfg.get("portable_mode") is True:
        return
    lock, host = cfg.get("host_lock") or "", socket.gethostname()
    if not lock or host.lower() == lock.lower():
        return
    sys.stderr.write(f"[ENV ERROR] config.json locks this radar to host '{lock}' (this is '{host}'). "
                     "Run it there, or set \"portable_mode\": true.\n")
    raise SystemExit(3)
