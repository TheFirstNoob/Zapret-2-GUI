"""Built-in self-diagnostics for end users.

Runs a fixed set of health checks and returns a structured report that the
GUI renders as a checklist.  Designed to answer the most common support
questions without the user touching logs: rights, install path, process,
service, preset validity, conflicts and connectivity (incl. Discord upload
host).  Every check has a hard timeout and never raises.
"""
from __future__ import annotations

import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib import request as _urlreq

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
    __slots__ = ("id", "name", "status", "detail", "tech")

    def __init__(self, id: str, name: str, status: str, detail: str = "", tech: str = "") -> None:
        self.id = id
        self.name = name
        self.status = status  # ok | warn | fail | skip
        self.detail = detail  # человекочитаемое объяснение для пользователя
        self.tech = tech      # техническая деталь для отчёта поддержки

    def to_dict(self) -> dict:
        d = {"id": self.id, "name": self.name, "status": self.status, "detail": self.detail}
        if self.tech:
            d["tech"] = self.tech
        return d


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
                     f"{s} — в пути кириллица; программа работает через короткие имена. "
                     "Если появятся проблемы, перенесите в C:\\Zapret2GUI\\",
                     tech="8.3 short path fallback active")
    return Check("path", "Путь установки", "fail",
                 f"{s} — в пути кириллица, а короткие имена недоступны: winws2 не запустится. "
                 "Перенесите программу в папку без кириллицы.",
                 tech="no 8.3 names available")


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
        ipset_catchall=cfg.ipset_catchall,
    )
    ok, err = validate_args(exe, args, cwd=root_dir)
    if ok:
        return Check("preset", f"Пресет «{profile}»", "ok",
                     "конфигурация в порядке",
                     tech=f"validate_args ok, {len(args)} args")
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
                                    "YouTube работает через QUIC (в браузере), его CDN доступен — "
                                    "TCP-проверка здесь неприменима",
                                    tech="TCP blackholed; QUIC path assumed via reachable CDN"))
                continue
            checks.append(Check(f"net_{host}", name, "fail",
                                "сайт не отвечает — соединение блокируется или обрывается",
                                tech="curl: no HTTP code (timeout/transport)"))
        elif kind == "canary":
            if 200 <= code < 400:
                checks.append(Check(f"net_{host}", name, "ok",
                                    "сайт отвечает — интернет работает",
                                    tech=f"HTTP {code}"))
            else:
                checks.append(Check(f"net_{host}", name, "warn",
                                    "сайт отвечает, но с необычным ответом — соединение всё же есть",
                                    tech=f"HTTP {code}"))
        else:
            # Any HTTP code >= 100 means the TLS connection passed the DPI.
            # 403/404/520 are expected "anonymous request" answers from CDNs.
            if code == 403:
                detail = ("соединение работает — код 403 это нормальный ответ CDN "
                          "на анонимный запрос, это не блокировка")
            else:
                detail = "сайт отвечает — соединение работает"
            checks.append(Check(f"net_{host}", name, "ok", detail, tech=f"HTTP {code}"))

    # Зеркальная сторона YouTube-прикола (§17/§22): i.ytimg.com по TCP режется
    # точечно (DPI/DNS), но сам youtube.com доступен, а браузер ходит через
    # QUIC — аватары/видео работают. Красный крест тут только пугает.
    if any(c.id == "net_i.ytimg.com" and c.status == "fail" for c in checks) and any(
            c.id == "net_www.youtube.com" and c.status == "ok" for c in checks):
        for c in checks:
            if c.id == "net_i.ytimg.com" and c.status == "fail":
                c.status = "ok"
                c.detail = ("YouTube работает (аватары, видео, комментарии) — TCP-проба "
                            "к CDN не проходит, браузер ходит через QUIC, это не блокировка")
                c.tech = "TCP to i.ytimg.com dropped; www.youtube.com reachable — QUIC path OK"
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
        return {"kind": "dns",
                "detail": "домен не удалось превратить в IP-адрес — вероятна блокировка DNS",
                "tech": f"getaddrinfo: {e}", "steps": steps}
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
                "detail": "к сайту не открывается соединение — блокировка на уровне IP-адреса",
                "tech": "TCP connect :443 failed", "steps": steps}
    steps["tcp"] = "ok"

    real_ok = _first_success(ips, host)
    steps["real_sni"] = "ok" if real_ok else "blocked"
    if real_ok:
        return {"kind": "ok", "detail": "сайт доступен",
                "tech": "TLS handshake ok", "steps": steps}

    benign = None
    for sni in ("www.google.com", "www.cloudflare.com"):
        if _first_success(ips, sni):
            benign = sni
            break
    steps["benign_sni"] = "ok" if benign else "blocked"
    if benign:
        return {"kind": "sni_block",
                "detail": ("сайт заблокирован по имени — именно такой блок Zapret 2 "
                           "и должен обходить"),
                "tech": f"real SNI blocked, benign SNI ({benign}) passes",
                "steps": steps}
    return {"kind": "tls_block",
            "detail": "соединение режется глубже, чем по имени сайта — обход может не помочь",
            "tech": "TLS blocked even with foreign SNI", "steps": steps}


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
        checks.append(Check(f"block_{host}", f"Тип блокировки: {name}", st,
                            info["detail"], tech=info.get("tech", "")))
    return checks


def _check_dns_health() -> Check:
    """plain 53 / DoT 853 / DoH 443 — many RU ISPs poison or block DNS layers."""
    import socket as _s
    results = []

    try:
        _s.getaddrinfo("rutracker.org", 443)
        results.append("обычный DNS отвечает")
    except OSError:
        results.append("обычный DNS молчит")

    def _tcp_ok(ip: str, port: int, timeout: float = 3.0) -> bool:
        try:
            with _s.create_connection((ip, port), timeout=timeout):
                return True
        except OSError:
            return False

    dot_ok = _tcp_ok("8.8.8.8", 853) or _tcp_ok("1.1.1.1", 853)
    results.append("защищённый DNS (TCP): " + ("работает" if dot_ok else "недоступен"))

    doh_ok = False
    try:
        req = _urlreq.Request(
            "https://1.1.1.1/dns-query?name=rutracker.org&type=A",
            headers={"Accept": "application/dns-json"},
        )
        with _urlreq.urlopen(req, timeout=4) as resp:
            doh_ok = resp.status == 200
    except Exception:
        doh_ok = False
    results.append("защищённый DNS (HTTPS): " + ("работает" if doh_ok else "недоступен"))

    if dot_ok and doh_ok:
        status, detail = "ok", "; ".join(results)
    elif not dot_ok and not doh_ok and "молчит" in results[0]:
        status, detail = "fail", "; ".join(results) + " — блокируется весь DNS"
    elif not dot_ok and not doh_ok:
        status, detail = "fail", "; ".join(results) + " — защищённый DNS недоступен"
    else:
        status, detail = "warn", "; ".join(results)
    return Check("dns_health", "DNS (обычный и защищённый)", status, detail)


def run_diagnostics(root_dir: Path, cfg: AppConfig, progress_cb=None) -> dict:
    root_dir = Path(root_dir)

    checks: list[Check] = []

    def _add(ck: Check) -> None:
        checks.append(ck)
        if progress_cb is not None:
            try:
                progress_cb(ck.name)
            except Exception:
                pass

    _add(Check("version", "Версия", "ok", VERSION))

    # rights
    _add(Check("admin", "Права администратора",
               "ok" if is_admin() else "fail",
               "есть" if is_admin() else "нет — WinDivert не загрузится"))

    # install path
    _add(_check_path(root_dir))

    # zapret2 process
    pid = _pid_of("winws2.exe")
    if pid is not None:
        strategy = cfg.last_profile or DEFAULT_PROFILE
        _add(Check("winws2", "Процесс winws2", "ok",
                            f"запущен (PID {pid}), пресет «{strategy}»"))
    else:
        _add(Check("winws2", "Процесс winws2", "fail",
                            "не запущен — обход неактивен"))

    # zapret 1 conflict
    z1 = _pid_of("winws.exe")
    if z1 is not None:
        _add(Check("zapret1", "Zapret 1", "warn",
                            f"winws.exe запущен (PID {z1}) — два WinDivert-фильтра конфликтуют"))
    else:
        _add(Check("zapret1", "Zapret 1", "ok", "не запущен"))

    # environment scan: other DPI tools / VPN clients / tunnel adapters
    try:
        from core.conflict_scan import scan as scan_conflicts, describe as describe_conflicts
        cr = scan_conflicts()
        if cr.hard_conflict:
            _add(Check("env", "Конфликт DPI-тулзов", "fail",
                                describe_conflicts(cr) or "обнаружен"))
        elif cr.warnings:
            _add(Check("env", "Окружение (VPN/туннели)", "warn",
                                describe_conflicts(cr) or "обнаружено"))
        else:
            _add(Check("env", "Окружение", "ok", "конфликтов нет"))
    except Exception as e:
        _add(Check("env", "Окружение", "skip", f"не удалось проверить: {e}"))

    # TCP timestamps (ts-fooling silently dead when disabled)
    try:
        from core.tcp_timestamps import timestamps_enabled as ts_enabled
        if ts_enabled():
            _add(Check("tcp_ts", "TCP timestamps", "ok",
                       "включены — обход работает в полную силу",
                       tech="timestamps enabled"))
        else:
            _add(Check("tcp_ts", "TCP timestamps", "warn",
                       "выключены — часть приёмов обхода молча не работает",
                       tech="timestamps disabled, tcp_ts= silent"))
    except Exception as e:
        _add(Check("tcp_ts", "TCP timestamps", "skip", f"не удалось проверить: {e}"))

    # service
    try:
        from core.service_manager import is_installed as svc_installed, status as svc_status
        if svc_installed():
            st = svc_status()
            if st == "running":
                _add(Check("service", "Служба zapret2", "ok", "установлена и работает"))
            elif _pid_of("winws2.exe") is not None:
                _add(Check("service", "Служба zapret2", "warn",
                                    "служба остановлена в SCM, но winws2 работает (запущен вручную)"))
            else:
                _add(Check("service", "Служба zapret2", "warn",
                                    "установлена, но не запущена (автозапуск после перезагрузки)"))
        else:
            _add(Check("service", "Служба zapret2", "skip",
                                "не установлена — обход только при открытом GUI"))
    except Exception as e:
        _add(Check("service", "Служба zapret2", "warn", f"не удалось проверить: {e}"))

    # preset validation
    _add(_check_preset(root_dir, cfg))

    # debug log
    _add(_check_debug_log(root_dir, bool(cfg.winws2_debug)))

    # connectivity (bypass active or not — see winws2 check for context)
    if progress_cb is not None:
        try:
            progress_cb("Связь (канарейки)")
        except Exception:
            pass
    net_checks = _check_net()
    checks.extend(net_checks)

    # block-type classification for the failed host(s): DNS vs IP vs SNI
    if progress_cb is not None:
        try:
            progress_cb("Тип блокировки")
        except Exception:
            pass
    checks.extend(_check_block_types(net_checks))

    # DNS health: plain resolver vs DoT (853) vs DoH (443)
    _add(_check_dns_health())

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
        if c.get("tech"):
            line += f"  [{c['tech']}]"
        lines.append(line)
    s = report.get("summary", {})
    lines += ["", f"Итог: OK={s.get('ok', 0)}, внимание={s.get('warn', 0)}, ошибок={s.get('fail', 0)}"]
    return "\n".join(lines)
