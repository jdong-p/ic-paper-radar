"""Optional campus-VPN check for IC Paper Radar (stdlib only), for your own institution's VPN.

Set it up in config.json → "vpn": `campus_route_host` (a host only reachable inside your campus
network), `campus_networks` (your campus IP ranges) and `campus_dns` (an internal DNS server).
They ship empty; until they're filled the check reports "not configured".

Layer 1: an Up VPN adapter (WireGuard / Wintun / TAP / OpenVPN…) holding an IPv4 address.
Layer 2: the OS would route `campus_route_host` *through* that adapter (UDP-connect trick, no
         packets sent) AND a `campus_dns` server answers on TCP 53 within the timeout.

Note: with a split-tunnel VPN, IEEE Xplore may still see your home IP. `connected` means
"campus network reachable", not "IEEE institutional access".

briefing.py calls this only with --require-vpn / --fetch-pdf; the default daily run skips it.

Run standalone:  python vpn_checker.py [--notify]   (exit 0 = connected, 1 = disconnected;
                 --notify also shows the `msg *` popup when disconnected)
"""
import ipaddress
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

from env_guard import ensure_minisforum_env

ensure_minisforum_env()
HERE = Path(__file__).resolve().parent


def _load_vpn_cfg():
    try:
        return json.loads((HERE / "config.json").read_text(encoding="utf-8"))["vpn"]
    except Exception:
        return {"interface_patterns": ["WireGuard", "Wintun", "TAP-Windows", "OpenVPN"],
                "campus_networks": [], "campus_route_host": "", "campus_dns": [],
                "probe_timeout_s": 2, "notify": False}


def _vpn_adapters(patterns):
    """[(name, description, ipv4)] for Up adapters matching a VPN pattern."""
    ps = ("$a = Get-NetAdapter | ? Status -eq 'Up'; "
          "$a | % { $ip = (Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 "
          "-ErrorAction SilentlyContinue | select -First 1).IPAddress; "
          "[pscustomobject]@{n=$_.Name; d=$_.InterfaceDescription; ip=$ip} } | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=20).stdout.strip()
        rows = json.loads(out) if out else []
    except Exception:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    pats = [p.lower() for p in patterns]
    return [(r["n"], r["d"], r.get("ip")) for r in rows
            if any(p in f"{r['n']} {r['d']}".lower() for p in pats)]


def _route_source_ip(host):
    """Local source IP the OS would use to reach `host` (no packets are sent)."""
    try:
        dst = socket.gethostbyname(host)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((dst, 9))
        src = s.getsockname()[0]
        s.close()
        return dst, src
    except OSError:
        return None, None


def _tcp_open(host, port, timeout):
    try:
        socket.create_connection((host, port), timeout).close()
        return True
    except OSError:
        return False


def check_vpn_status() -> dict:
    cfg = _load_vpn_cfg()
    if not cfg.get("campus_route_host"):
        return {"connected": False, "interface": "", "campus_probe": False,
                "message": "🔴 Campus VPN check not configured — fill config.json → vpn "
                           "(campus_route_host, campus_networks, campus_dns) to use --require-vpn / --fetch-pdf.",
                "details": {}}
    timeout = cfg.get("probe_timeout_s", 2)
    nets = [ipaddress.ip_network(n) for n in cfg.get("campus_networks", [])]
    in_campus = lambda ip: bool(ip) and any(ipaddress.ip_address(ip) in n for n in nets)

    adapters = [a for a in _vpn_adapters(cfg["interface_patterns"]) if a[2]]
    iface = adapters[0] if adapters else None
    dst, src = _route_source_ip(cfg["campus_route_host"])
    routed = bool(iface) and src == iface[2]
    dns_ok = any(_tcp_open(d, 53, timeout) for d in cfg.get("campus_dns", []))
    campus_probe = routed and dns_ok
    connected = bool(iface) and campus_probe

    if connected:
        msg = (f"🟢 Campus Network Active — {iface[0]} ({iface[1]}) {iface[2]}; "
               f"{cfg['campus_route_host']} ({dst}) routed via tunnel, campus DNS reachable")
    elif iface:
        msg = (f"🔴 VPN Disconnected — adapter {iface[0]} is up ({iface[2]}) but campus probe "
               f"failed (routed via tunnel: {routed}, campus DNS: {dns_ok}). Session likely expired.")
    else:
        msg = "🔴 VPN Disconnected — no active VPN adapter with an IPv4 address."
    return {"connected": connected,
            "interface": f"{iface[0]} ({iface[1]}) {iface[2]}" if iface else "",
            "campus_probe": campus_probe,
            "message": msg,
            "details": {"route_host": cfg["campus_route_host"], "route_host_ip": dst,
                        "source_ip": src, "routed_via_tunnel": routed,
                        "source_ip_in_campus_range": in_campus(src), "campus_dns_tcp53": dns_ok}}


REMINDER = "Your campus VPN is NOT connected. Open your VPN app on this computer and connect, then run again."


def notify_disconnected():
    """Console banner + popup in every desktop session (msg.exe works from SSH session 0)."""
    bar = "!" * 78
    print(f"\n{bar}\n  🔴 VPN Disconnected\n  {REMINDER}\n{bar}\n", file=sys.stderr)
    if os.name == "nt":
        try:
            subprocess.run(["msg", "*", "/TIME:86400", f"IC Paper Radar: {REMINDER}"],
                           capture_output=True, timeout=10)
        except Exception:
            pass


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    st = check_vpn_status()
    print(st["message"])
    print(json.dumps(st, indent=2, ensure_ascii=False))
    if not st["connected"] and "--notify" in sys.argv:
        notify_disconnected()
    sys.exit(0 if st["connected"] else 1)
