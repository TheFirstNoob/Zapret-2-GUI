from __future__ import annotations

import json
import platform
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import VERSION


def _run(cmd: list[str], timeout: int = 5, encoding: str = "cp866") -> str:
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = r.stdout.decode(encoding, errors="replace")
        return out.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def get_system_info() -> dict:
    # Более читаемое название Windows (10/11/etc)
    win_ver = platform.win32_ver()
    info = {
        "os": platform.platform(),
        "windows_release": win_ver[0] if win_ver[0] else "",
        "windows_version": win_ver[1] if win_ver[1] else "",
        "windows_edition": win_ver[2] if win_ver[2] else "",
        "os_version": platform.version(),
        "python": platform.python_version(),
        "hostname": platform.node(),
        "arch": platform.machine(),
        "timestamp": datetime.now().isoformat(),
    }
    return info


def get_dns_info() -> list[dict]:
    dns_servers = []
    try:
        out = _run(["ipconfig", "/all"], timeout=10)
        lines = out.splitlines()
        current_adapter = ""
        for line in lines:
            s = line.strip()
            if s.startswith("Адаптер") or s.startswith("Adapter"):
                current_adapter = s.split(":")[0].replace("Адаптер ", "").replace("Adapter ", "").strip()
            if "DNS-сервер" in s or "DNS Server" in s:
                parts = s.split(":")[-1].strip()
                for ip in parts.split():
                    if ip and ip != ".":
                        dns_servers.append({"adapter": current_adapter, "dns": ip})
    except Exception:
        pass
    return dns_servers


def get_network_info() -> dict:
    ipconfig_out = _run(["ipconfig"], timeout=10)
    gw = ""
    for line in ipconfig_out.splitlines():
        s = line.strip()
        if "Шлюз" in s or "Gateway" in s:
            gw = s
            break
    return {
        "interface": ipconfig_out[:500],
        "gateway": gw[:200],
        # netsh выдаёт UTF-8 (не cp866).
        "wifi_ssid": _run(["netsh", "wlan", "show", "interfaces"], timeout=5, encoding="utf-8")[:300],
    }


def get_routing_info() -> dict:
    """Собирает короткий tracert до публичного DNS для анализа хопов провайдера."""
    return {
        "trace_1dot": _run(["tracert", "-d", "-h", "8", "-w", "1500", "1.1.1.1"], timeout=20),
    }


def get_isp_info() -> dict:
    """Пытается определить провайдера через whois (ограниченно)."""
    # nslookup на русской Windows выдаёт cp1251, а не cp866.
    out = _run(["nslookup", "-type=TXT", "o-o.myaddr.l.google.com", "ns1.google.com"], timeout=10, encoding="cp1251")
    return {
        "nslookup_txt": out[:500],
    }


def collect_all() -> dict:
    return {
        "collected_at": datetime.now().isoformat(),
        "system": get_system_info(),
        "dns": get_dns_info(),
        "network": get_network_info(),
        "routing": get_routing_info(),
        "isp": get_isp_info(),
    }


def export_data_package(
    consent: bool,
    city: str,
    isp: str,
    vpn_active: bool = False,
    zapret1_strategy: str = "",
    root_dir: Optional[Path] = None,
    result_dir: Optional[Path] = None,
    bat_path: Optional[Path] = None,
    zapret1_cmdline: str = "",
    phase0_results: Optional[dict] = None,
    phase1_results: Optional[dict] = None,
    phase2_results: Optional[dict] = None,
    mode: str = "lite",
) -> tuple[bool, str]:
    """Собирает всё в ZIP: system info, результаты тестов, .bat, командную строку Zapret 1."""
    if not consent:
        return False, "Пользователь не дал согласие"

    if result_dir is None:
        result_dir = Path.cwd()
    if root_dir is None:
        root_dir = result_dir

    if bat_path is None and zapret1_strategy and Path(zapret1_strategy).exists():
        bat_path = Path(zapret1_strategy)

    def _maybe(val: str) -> str:
        return val.strip() if val and val.strip() else "Пропущено пользователем"

    now = datetime.now()
    data = {
        "meta": {
            "version": VERSION,
            "exported_at": now.isoformat(),
            "mode": mode,
            "vpn_active": vpn_active,
            "user_city": _maybe(city),
            "user_isp": _maybe(isp),
            "zapret1_strategy": _maybe(zapret1_strategy),
            "zapret1_cmdline": _maybe(zapret1_cmdline),
        },
        "collect": collect_all(),
        "test_results": {
            "phase0_zapret1": phase0_results or {},
            "phase1_naked": phase1_results or {},
            "phase2_zapret2": phase2_results or {},
        },
    }

    tag = f"full_{now.strftime('%Y%m%d_%H%M%S')}" if mode == "full" else f"lite_{now.strftime('%Y%m%d_%H%M%S')}"
    zip_name = f"zapret2_report_{tag}.zip"
    zip_path = result_dir / zip_name

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("system_info.json", json.dumps(data, indent=2, ensure_ascii=False))

            session_log = root_dir / "test_session.log"
            if session_log.exists():
                zf.write(session_log, "test_session.log")

            debug_log = root_dir / "debug_winws2.log"
            if debug_log.exists():
                zf.write(debug_log, "debug_winws2.log")

            presets_dir = root_dir / "presets"
            if presets_dir.is_dir():
                for pf in presets_dir.glob("*.txt"):
                    zf.write(pf, f"presets/{pf.name}")

            # Hostlists matter for diagnosis: a blocked domain missing from
            # every list a preset references means its desync profile never
            # fires (no_action) — strategies look identical and nothing works.
            lists_dir = root_dir / "lists"
            if lists_dir.is_dir():
                for lf in sorted(lists_dir.glob("*.txt")):
                    try:
                        if lf.stat().st_size <= 300_000:
                            zf.write(lf, f"lists/{lf.name}")
                    except OSError:
                        pass

            if bat_path and bat_path.exists():
                zf.write(bat_path, bat_path.name)

        return True, str(zip_path)
    except OSError as e:
        return False, str(e)
