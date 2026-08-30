from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

# Known DPI-bypass tools that share the WinDivert driver — running them
# alongside winws2 is a HARD conflict (one of them stops seeing packets).
DPI_TOOL_IMAGES = {
    "winws.exe": "Zapret 1",
    "byedpi.exe": "ByeDPI",
    "goodbyedpi.exe": "GoodbyeDPI",
    "spider.exe": "ByeDPI (spider)",
    "zapret.exe": "Zapret (legacy launcher)",
    "fpwin.exe": "FastProxy",
    "intosy.exe": "Intosy",
}

# VPN clients / tunnels — not fatal (no WinDivert sharing) but they can
# shadow the bypass or be shadowed by it; worth a warning.
VPN_IMAGES = {
    "openvpn.exe": "OpenVPN",
    "wireguard.exe": "WireGuard",
    "nordvpn.exe": "NordVPN",
    "expressvpn.exe": "ExpressVPN",
    "protonvpn.exe": "ProtonVPN",
    "windscribe.exe": "Windscribe",
    "tailscale.exe": "Tailscale",
    "zerotier-one.exe": "ZeroTier",
    "usque.exe": "usque (MASQUE)",
    "maskd.exe": "maskd (MASQUE)",
    "cloudflared.exe": "cloudflared (tunnel)",
    "hamachi.exe": "LogMeIn Hamachi",
}

TUN_HINTS = (
    "TAP-", "TUN", "Wintun", "WireGuard", "OpenVPN", "ZeroTier",
    "Tailscale", "Cloudflare", "Hamachi", "Sangfor",
)

VPN_SERVICES = {
    "CloudflareWARP": "Cloudflare WARP",
    "WireGuardTunnel$": "WireGuard",
    "OpenVPNService": "OpenVPN",
    "Tailscale": "Tailscale",
    "ZeroTierOne": "ZeroTier",
}


@dataclass
class ConflictReport:
    dpi_tools: List[str] = field(default_factory=list)
    vpn_clients: List[str] = field(default_factory=list)
    tun_adapters: List[str] = field(default_factory=list)
    vpn_services: List[str] = field(default_factory=list)

    @property
    def hard_conflict(self) -> bool:
        return bool(self.dpi_tools)

    @property
    def warnings(self) -> bool:
        return bool(self.vpn_clients or self.tun_adapters or self.vpn_services)


def _running_images() -> List[str]:
    try:
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
            encoding="oem", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = []
        for line in r.stdout.strip().splitlines():
            parts = line.split(",")
            if parts:
                out.append(parts[0].strip('"').lower())
        return out
    except (subprocess.TimeoutExpired, OSError):
        return []


def _adapter_descriptions() -> List[str]:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetAdapter -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty InterfaceDescription"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return [l.strip() for l in r.stdout.splitlines() if l.strip()]
    except (subprocess.TimeoutExpired, OSError):
        return []


def _running_services() -> List[str]:
    try:
        r = subprocess.run(
            ["sc", "query", "type=", "service", "state=", "active"],
            capture_output=True, text=True, timeout=10,
            encoding="oem", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        names = []
        for line in r.stdout.splitlines():
            if "SERVICE_NAME" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    names.append(parts[1].strip())
        return names
    except (subprocess.TimeoutExpired, OSError):
        return []


def scan() -> ConflictReport:
    rep = ConflictReport()

    images = _running_images()
    for img, name in DPI_TOOL_IMAGES.items():
        if img in images:
            rep.dpi_tools.append(f"{name} ({img})")

    for img, name in VPN_IMAGES.items():
        if img in images:
            rep.vpn_clients.append(f"{name} ({img})")

    for desc in _adapter_descriptions():
        low = desc.lower()
        if any(hint.lower() in low for hint in TUN_HINTS):
            rep.tun_adapters.append(desc)

    for svc, name in VPN_SERVICES.items():
        if any(s.lower().startswith(svc.rstrip("$").lower()) for s in _running_services()):
            rep.vpn_services.append(name)

    return rep


def describe(report: ConflictReport) -> Optional[str]:
    """Human text for diagnostics, or None when nothing found."""
    lines = []
    for t in report.dpi_tools:
        lines.append(f"Чужой DPI-тулз {t} — жёсткий конфликт (общий WinDivert), остановите его")
    for s in report.vpn_services:
        lines.append(f"VPN-служба {s} активна — может перехватывать трафик")
    for c in report.vpn_clients:
        lines.append(f"VPN-клиент {c} запущен — может перехватывать трафик")
    for a in report.tun_adapters:
        lines.append(f"Туннельный адаптер: {a}")
    return "; ".join(lines) if lines else None