"""Built-in self-diagnostics for end users.

Runs a fixed set of health checks and returns a structured report that the
GUI renders as a checklist.  Designed to answer the most common support
questions without the user touching logs: rights, install path, process,
service, preset validity, conflicts and connectivity (incl. Discord upload
host).  Every check has a hard timeout and never raises.
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.admin import is_admin
from core.config import AppConfig, DEFAULT_PROFILE, VERSION
from core.launcher import build_args_from_preset, validate_args
from core.utils import short_path

# Upload host: 403 from Google Storage means the connection is fine.
DISCORD_UPLOAD_HOST = "discord-attachments-uploads-prd.storage.googleapis.com"

# Connectivity checks: host, human name, expected-any-code (canary must be 2xx-3xx).
# i.ytimg.com is checked BEFORE www.youtube.com so the YouTube TCP quirk
# (§17: TCP blocked everywhere, browser works via QUIC) can be explained
# using the CDN reachability result instead of showing a false red cross.
_NET_CHECKS = [
    ("www.google.com", "Интернет (канарейка)", "canary"),
    ("discord.com", "Discord", "any"),
    (DISCORD_UPLOAD_HOST, "Discord — отправка файлов", "any"),
    ("i.ytimg.com", "YouTube CDN", "any"),
    ("www.youtube.com", "YouTube", "youtube"),
]

_DEBUG_LOG_WARN_BYTES = 50 * 1024 * 1024


class Check:
    __slots__ = ("id", "name", "status", "detail")

    def __init__(self, id: str, name: str, status: str, detail: str = "") -> None:
        self.id = id
        self.name = name
        self.status = status  # ok | warn | fail | skip
        self.detail = detail

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "status": self.status, "detail": self.detail}


def _pid_of(image_name: str) -> Optional[int]:
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="oem", errors="replace",
            timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in r.stdout.splitlines():
            parts = line.split(",")
            if len(parts) >= 2 and image_name.lower() in parts[0].lower():
                try:
                    return int(parts[1].strip('"'))
                except ValueError:
                    return None
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _curl_code(host: str, timeout: int = 6) -> Optional[int]:
    """HTTP status code via curl, None on timeout/transport error."""
    try:
        r = subprocess.run(
            ["curl.exe", "-4", "-s", "-m", str(timeout),
             "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
             "-o", "NUL", "-w", "%{http_code}", f"https://{host}/"],
            capture_output=True, text=True, encoding="oem", errors="replace",
            timeout=timeout + 3, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        code = r.stdout.strip()
        return int(code) if code.isdigit() else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _check_path(root_dir: Path) -> Check:
    s = str(root_dir)
    if all(ord(c) < 128 for c in s):
        return Check("path", "Путь установки", "ok", s)
    if str(short_path(root_dir)) != s:
        return Check("path", "Путь установки", "warn",
                     f"{s} — кириллица в пути, работает через короткие имена 8.3. "
                     "Если возникнут проблемы, перенесите в C:\\Zapret2GUI\\")
    return Check("path", "Путь установки", "fail",
                 f"{s} — кириллица без коротких имён 8.3, winws2 не запустится. "
                 "Перенесите программу в путь без кириллицы.")


def _check_preset(root_dir: Path, cfg: AppConfig) -> Check:
    profile = cfg.last_profile or DEFAULT_PROFILE
    exe = root_dir / "bin" / "winws2.exe"
    preset = root_dir / "presets" / f"{profile}.txt"
    if not preset.exists():
        return Check("preset", f"Пресет «{profile}»", "fail", "файл не найден")
    if not exe.exists():
        return Check("preset", f"Пресет «{profile}»", "fail", "winws2.exe не найден")
    args = build_args_from_preset(
        root_dir, root_dir / "lua", root_dir / "blobs", preset,
        debug=cfg.winws2_debug, game_filter_mode=cfg.game_filter_mode,
        discord_voice=cfg.discord_voice, autohostlist=cfg.autohostlist,
    )
    ok, err = validate_args(exe, args, cwd=root_dir)
    if ok:
        return Check("preset", f"Пресет «{profile}»", "ok",
                     f"валиден, аргументов: {len(args)}")
    return Check("preset", f"Пресет «{profile}»", "fail", err)


def _check_debug_log(root_dir: Path, debug_enabled: bool) -> Check:
    log = root_dir / "debug_winws2.log"
    if not log.exists():
        return Check("debug_log", "Debug-лог winws2", "ok", "отсутствует (выключен)")
    size = log.stat().st_size
    if size > _DEBUG_LOG_WARN_BYTES:
        return Check("debug_log", "Debug-лог winws2", "fail",
                     f"{size / 1024 / 1024:.0f} МБ — лог огромен! Выключите DEBUG-тоггл и удалите файл")
    if debug_enabled:
        return Check("debug_log", "Debug-лог winws2", "warn",
                     f"{size / 1024:.0f} КБ — DEBUG включён, это замедляет работу")
    return Check("debug_log", "Debug-лог winws2", "ok",
                 f"{size / 1024:.0f} КБ — остался от прошлого запуска с DEBUG, можно удалить")


def _check_net() -> list[Check]:
    checks: list[Check] = []
    for host, name, kind in _NET_CHECKS:
        code = _curl_code(host)
        if code is None or code < 100:
            # YouTube TCP quirk: the page is blackholed on EVERY tested setup,
            # but the browser works via QUIC.  If the CDN (i.ytimg.com) is
            # reachable, report the quirk instead of a false red cross.
            if kind == "youtube" and any(c.id == "net_i.ytimg.com" and c.status == "ok"
                                         for c in checks):
                checks.append(Check(f"net_{host}", name, "ok",
                                    "TCP-проверка неприменима — YouTube работает через QUIC "
                                    "(известный TLS-прикол), CDN доступен"))
                continue
            checks.append(Check(f"net_{host}", name, "fail",
                                "нет ответа (таймаут/обрыв/DPI)"))
        elif kind == "canary":
            if 200 <= code < 400:
                checks.append(Check(f"net_{host}", name, "ok", f"HTTP {code}"))
            else:
                checks.append(Check(f"net_{host}", name, "warn",
                                    f"HTTP {code} — канарейка странная, но соединение есть"))
        else:
            # Any HTTP code >= 100 means the TLS connection passed the DPI.
            # 403/404/520 are expected "anonymous request" answers from CDNs.
            detail = f"HTTP {code}"
            if code == 403:
                detail = "HTTP 403 — не блокировка (CDN так отвечает анонимным запросам)"
            checks.append(Check(f"net_{host}", name, "ok", detail))
    return checks


def classify_block(host: str, timeout: float = 2.5, max_ips: int = 2) -> dict:
    """Determine WHAT kind of block a host faces (pure stdlib, no curl).

    Probes, in order:
    1. DNS resolution                      -> "dns" (hijack / no answer)
    2. TCP connect to :443 (any IP)        -> "ip_block" (SYN-level/port filter)
    3. TLS handshake with the REAL SNI     -> "ok" (site reachable)
    4. TLS handshake to the SAME IP with a
       benign SNI (google/cloudflare)      -> "sni_block": the IP is clean, the
       block is triggered ONLY by the SNI — exactly what a desync must defeat.
       If even a foreign SNI fails         -> "tls_block" (not SNI-bound:
       IP/port level or deep DPI).

    The SNI-swap step is the key validator: on "sni_block" a working zapret
    MUST be able to bypass the site.  If no preset bypasses it anyway, the
    problem is the engine/lists, not "the DPI is too strong".
    Never raises; TLS certs are ignored (handshake completion is the signal).
    """
    import socket
    import ssl
    from concurrent.futures import ThreadPoolExecutor, as_completed

    steps: dict = {}
    try:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    except OSError as e:
        return {"kind": "dns", "detail": f"не удалось зарезолвить {host}: {e}", "steps": steps}
    ips = list(dict.fromkeys(i[4][0] for i in infos))[:max_ips]
    steps["ips"] = ips

    def _tls(ip: str, sni: str) -> bool:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            raw = socket.create_connection((ip, 443), timeout=timeout)
            with ctx.wrap_socket(raw, server_hostname=sni) as ss:
                return True
        except (OSError, ssl.SSLError):
            return False

    def _probe(ip: str, sni: Optional[str]) -> bool:
        """TCP connect probe when sni is None, TLS-handshake probe otherwise."""
        if sni is None:
            try:
                s = socket.create_connection((ip, 443), timeout=timeout)
                s.close()
                return True
            except OSError:
                return False
        return _tls(ip, sni)

    def _first_success(ips, sni) -> bool:
        # Note: NOT a `with` block — exiting a context manager calls
        # shutdown(wait=True) and blocks until blackholed probes time out,
        # adding ~timeout to every step.  wait=False lets them die on their own.
        pool = ThreadPoolExecutor(max_workers=max_ips)
        futs = [pool.submit(_probe, ip, sni) for ip in ips]
        try:
            for fut in as_completed(futs):
                if fut.result():
                    return True
        finally:
            pool.shutdown(wait=False)
        return False

    tcp_ok = _first_success(ips, None)
    if not tcp_ok:
        return {"kind": "ip_block",
                "detail": "TCP-коннект к :443 не проходит (блок на уровне IP/порта/SYN)",
                "steps": steps}
    steps["tcp"] = "ok"

    real_ok = _first_success(ips, host)
    steps["real_sni"] = "ok" if real_ok else "blocked"
    if real_ok:
        return {"kind": "ok", "detail": "TLS-хендшейк проходит — сайт доступен", "steps": steps}

    benign = None
    for sni in ("www.google.com", "www.cloudflare.com"):
        if _first_success(ips, sni):
            benign = sni
            break
    steps["benign_sni"] = "ok" if benign else "blocked"
    if benign:
        return {"kind": "sni_block",
                "detail": (f"SNI-блок: тот же IP c SNI {benign} проходит TLS, с реальным SNI — нет. "
                           "Блок специфичен для домена — работающий desync обязан его обходить"),
                "steps": steps}
    return {"kind": "tls_block",
            "detail": "TLS не проходит даже с чужим SNI — блок не по SNI (IP/порт-уровень или глубокий DPI)",
            "steps": steps}


def _check_block_types(net_checks: list[Check]) -> list[Check]:
    """Classify WHY the failed connectivity hosts are blocked (max 1 host,
    youtube preferred — it is the most common and most informative case)."""
    failed = {c.id.removeprefix("net_"): c for c in net_checks if c.status == "fail"}
    names = {h: n for h, n, _k in _NET_CHECKS}
    if "www.youtube.com" in failed:
        order = ["www.youtube.com"]
    elif "discord.com" in failed:
        order = ["discord.com"]
    else:
        order = list(failed)
    checks: list[Check] = []
    for host in order[:1]:
        info = classify_block(host)
        st = {"ok": "ok", "dns": "fail", "ip_block": "fail",
              "sni_block": "warn", "tls_block": "fail"}.get(info["kind"], "warn")
        name = names.get(host, host)
        checks.append(Check(f"block_{host}", f"Тип блокировки: {name}", st, info["detail"]))
    return checks


def run_diagnostics(root_dir: Path, cfg: AppConfig) -> dict:
    root_dir = Path(root_dir)

    checks: list[Check] = []
    checks.append(Check("version", "Версия", "ok", VERSION))

    # rights
    checks.append(Check("admin", "Права администратора",
                        "ok" if is_admin() else "fail",
                        "есть" if is_admin() else "нет — WinDivert не загрузится"))

    # install path
    checks.append(_check_path(root_dir))

    # zapret2 process
    pid = _pid_of("winws2.exe")
    if pid is not None:
        strategy = cfg.last_profile or DEFAULT_PROFILE
        checks.append(Check("winws2", "Процесс winws2", "ok",
                            f"запущен (PID {pid}), пресет «{strategy}»"))
    else:
        checks.append(Check("winws2", "Процесс winws2", "fail",
                            "не запущен — обход неактивен"))

    # zapret 1 conflict
    z1 = _pid_of("winws.exe")
    if z1 is not None:
        checks.append(Check("zapret1", "Zapret 1", "warn",
                            f"winws.exe запущен (PID {z1}) — два WinDivert-фильтра конфликтуют"))
    else:
        checks.append(Check("zapret1", "Zapret 1", "ok", "не запущен"))

    # service
    try:
        from core.service_manager import is_installed as svc_installed, status as svc_status
        if svc_installed():
            st = svc_status()
            if st == "running":
                checks.append(Check("service", "Служба zapret2", "ok", "установлена и работает"))
            elif _pid_of("winws2.exe") is not None:
                checks.append(Check("service", "Служба zapret2", "warn",
                                    "служба остановлена в SCM, но winws2 работает (запущен вручную)"))
            else:
                checks.append(Check("service", "Служба zapret2", "warn",
                                    "установлена, но не запущена (автозапуск после перезагрузки)"))
        else:
            checks.append(Check("service", "Служба zapret2", "skip",
                                "не установлена — обход только при открытом GUI"))
    except Exception as e:
        checks.append(Check("service", "Служба zapret2", "warn", f"не удалось проверить: {e}"))

    # preset validation
    checks.append(_check_preset(root_dir, cfg))

    # debug log
    checks.append(_check_debug_log(root_dir, bool(cfg.winws2_debug)))

    # connectivity (bypass active or not — see winws2 check for context)
    net_checks = _check_net()
    checks.extend(net_checks)

    # block-type classification for the failed host(s): DNS vs IP vs SNI
    checks.extend(_check_block_types(net_checks))

    summary = {"ok": 0, "warn": 0, "fail": 0, "skip": 0}
    for c in checks:
        summary[c.status] = summary.get(c.status, 0) + 1

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "elapsed_sec": None,
        "summary": summary,
        "checks": [c.to_dict() for c in checks],
    }


def format_report_text(report: dict) -> str:
    """Plain-text report for clipboard sharing (support tickets)."""
    icon = {"ok": "[OK]  ", "warn": "[ВНИМ]", "fail": "[FAIL]", "skip": "[----]"}
    lines = [
        f"Zapret2 GUI — диагностика {report.get('timestamp', '')} (v{VERSION})",
        "",
    ]
    for c in report.get("checks", []):
        line = f"{icon.get(c['status'], '[??]')} {c['name']}"
        if c.get("detail"):
            line += f" — {c['detail']}"
        lines.append(line)
    s = report.get("summary", {})
    lines += ["", f"Итог: OK={s.get('ok', 0)}, внимание={s.get('warn', 0)}, ошибок={s.get('fail', 0)}"]
    return "\n".join(lines)
