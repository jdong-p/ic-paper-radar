#!/bin/sh
# Engineer Paper Radar: double-click (macOS) to open the Setup & Control Center (STARTUP.html) with working buttons.
# It runs "python3 briefing.py --gui": a small server on http://127.0.0.1 (this computer only) that opens
# your browser. Keep this window open while you use the page; close it (or Ctrl+C) to stop.
cd "$(dirname "$0")" || exit 1
exec python3 briefing.py --gui
