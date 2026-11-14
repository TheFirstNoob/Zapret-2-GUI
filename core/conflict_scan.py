from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

# Известные DPI-bypass-тулы, использующие драйвер WinDivert: работа рядом
# с winws2 - ЖЁСТКИЙ конфликт (один из них перестаёт видеть пакеты).
DPI_TOOL_IMAGES = {
    "winws.exe": "Zapret 1",
    "byedpi.exe": "ByeDPI",
    "goodbyedpi.exe": "GoodbyeDPI",
    "spider.exe": "ByeDPI (spider)",
    "zapret.exe": "Zapret (legacy launcher)",
    "fpwin.exe": "FastProxy",
    "intosy.exe": "Intosy",
}

# VPN-клиенты/туннели - не фатальны (WinDivert не делят), но могут
# перекрывать обход или быть перекрытыми им; повод для предупреждения.
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

# Короткий TTL-кэш дорогих опросов (аудит 2026-11-14, T21): tasklist/sc/
# Get-NetAdapter занимают сотни мс, а скан вызывается из диагностики и может
# повторяться подряд. 12 с - осознанно короткое окно: пользователь не увидит
# устаревший список спустя минуту, но повторный скан в том же отчёте
# бесплатен. Пустой результат НЕ кэшируем: это вероятный сбой опроса, и
# «ложно-зелёный» скан на 12 с хуже лишнего вызова.
_CACHE_TTL_SEC = 12.0
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, List[str]]] = {}


def _now() -> float:
    """Монотонное время (подменяется в тестах)."""
    return time.monotonic()


def _cached_list(key: str, loader: Callable[[], List[str]]) -> List[str]:
    """Список от loader с TTL-кэшем; пустой/сбойный результат не кэшируется."""
    now = _now()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and (now - hit[0]) < _CACHE_TTL_SEC:
            return list(hit[1])
    values = list(loader())
    if values:
        with _cache_lock:
            _cache[key] = (now, list(values))
    return values


def clear_cache() -> None:
    """Сбросить кэш скана (тесты и повторная диагностика после изменений)."""
    with _cache_lock:
        _cache.clear()


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


def _load_running_images() -> List[str]:
    from core.proc import running_images
    return running_images(timeout=10)


def _load_adapter_descriptions() -> List[str]:
    # encoding обязателен: вывод PowerShell OEM (cp866), text=True без него
    # даёт UnicodeDecodeError при разборе - чек молча пропадал бы целиком
    # (остальные пробы здесь с encoding, см. _running_images/_running_services).
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetAdapter -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty InterfaceDescription"],
            capture_output=True, text=True, timeout=10,
            encoding="oem", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return [l.strip() for l in r.stdout.splitlines() if l.strip()]
    except (subprocess.TimeoutExpired, OSError):
        return []


def _load_running_services() -> List[str]:
    """Имена ЗАПУЩЕННЫХ служб.

    2026-11-14: запрос со state= active на актуальной Windows возвращает
    rc=87 "Invalid state= field" -> список всегда пуст и чек конфликтов с
    VPN-службами был ложно-зелёным. Берём state= all и фильтруем по строке
    STATE (значение RUNNING всегда английское, заголовок может быть
    локализован)."""
    try:
        r = subprocess.run(
            ["sc", "query", "type=", "service", "state=", "all"],
            capture_output=True, text=True, timeout=15,
            encoding="oem", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        names: List[str] = []
        cur: Optional[str] = None
        for line in r.stdout.splitlines():
            if "SERVICE_NAME" in line:
                cur = line.split(":", 1)[1].strip() if ":" in line else None
            elif cur and "RUNNING" in line.upper():
                names.append(cur)
                cur = None
        return names
    except (subprocess.TimeoutExpired, OSError):
        return []


def _running_images() -> List[str]:
    return _cached_list("images", _load_running_images)


def _adapter_descriptions() -> List[str]:
    return _cached_list("adapters", _load_adapter_descriptions)


def _running_services() -> List[str]:
    return _cached_list("services", _load_running_services)


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

    # Один опрос служб на скан: раньше sc query вызывался в цикле на каждую
    # VPN-службу (5 вызовов подряд) - теперь один + TTL-кэш.
    running = [s.lower() for s in _running_services()]
    for svc, name in VPN_SERVICES.items():
        prefix = svc.rstrip("$").lower()
        if any(s.startswith(prefix) for s in running):
            rep.vpn_services.append(name)

    return rep


def describe(report: ConflictReport) -> Optional[str]:
    """Человекочитаемый текст для диагностики или None, если ничего не найдено."""
    lines = []
    for t in report.dpi_tools:
        lines.append(f"Чужой DPI-тулз {t} - жёсткий конфликт (общий WinDivert), остановите его")
    for s in report.vpn_services:
        lines.append(f"VPN-служба {s} активна - может перехватывать трафик")
    for c in report.vpn_clients:
        lines.append(f"VPN-клиент {c} запущен - может перехватывать трафик")
    for a in report.tun_adapters:
        lines.append(f"Туннельный адаптер: {a}")
    return "; ".join(lines) if lines else None