"""Discord/Cloudflare fix (0.12): hosts + scoped DNS + NRPT + rotation.

Зачем: после 18.11.2026 у части провайдеров режется TLS к Cloudflare-эджам,
которые использует Discord (и другие CF-сервисы). DNS-подмена/desync не
помогают; рабочий локальный вариант - направить домены на другой
Cloudflare-anycast IP, который не попадает под блок.

Модуль НЕ меняет системный DNS. Он делает:
  * hosts: apex-домены (NRPT не матчит apex) на выбранный candidate IP;
  * NRPT: subdomains Discord/Cloudflare/auth-зон -> 127.0.0.1;
  * локальный DNS (UDP+TCP) отвечает A=candidate, AAAA=NODATA;
  * случайный health-checked candidate на запуск/ротацию (не на каждый запрос);
  * backup hosts и state в logs/.

Требует admin (hosts + NRPT + bind :53). Всё обратимо: disable убирает
наши записи/правила и останавливает DNS; backup остаётся для ручного restore.
"""
from __future__ import annotations

import atexit
import ipaddress
import json
import random
import os
import socket
import ssl
import struct
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.admin import is_admin
from core.applog import log as applog

HOSTS_PATH = Path(r"C:\Windows\System32\drivers\etc\hosts")
LOCAL_DNS = "127.0.0.1"
DNS_PORT = 53
NRPT_DISPLAY = "Zapret2GUI DiscordFix"

# fallback, если lists/discord-candidates.json не приехал
DEFAULT_CANDIDATES = [
    "23.227.38.5", "23.227.38.24", "23.227.38.74", "23.227.38.112",
    "23.227.38.177", "23.227.38.234",
]

# apex-домены: hosts, т.к. NRPT не матчит apex
APEX_HOSTS = [
    # Discord
    "discord.com", "www.discord.com", "gateway.discord.gg",
    "cdn.discordapp.com", "discordapp.com", "discordapp.net",
    "discord.media", "media.discordapp.net", "updates.discord.com",
    "discord.gg",
    # Cloudflare/auth/captcha
    "cloudflare.com", "www.cloudflare.com", "dash.cloudflare.com",
    "api.cloudflare.com", "support.cloudflare.com",
    "cloudflareaccess.com", "cloudflare-dns.com",
    "challenges.cloudflare.com", "cloudflare-ech.com",
    "auth0.com", "www.auth0.com",
    "api.epicgames.dev", "www.epicgames.com", "store.epicgames.com",
    "fandom.com", "www.fandom.com",
]

# Статический hosts-режим: только точные имена, которые не меняются.
# Динамические c-*.discord.media сюда не входят (hosts не умеет wildcard).
STATIC_HOSTS = [
    "discord.com", "www.discord.com", "gateway.discord.gg",
    "cdn.discordapp.com", "discordapp.com", "discordapp.net",
    "discord.media", "media.discordapp.net",
    "images-ext-1.discordapp.net", "images-ext-2.discordapp.net",
    "updates.discord.com", "discord.gg",
    "cloudflare.com", "challenges.cloudflare.com", "auth0.com",
    "api.epicgames.dev", "fandom.com",
]

# NRPT: любые subdomains этих зон -> локальный DNS
NRPT_ZONES = [
    ".discord", ".discord.com", ".discord.gg", ".discord.media",
    ".discordapp.com", ".discordapp.net",
    ".cloudflare.com", ".cloudflareaccess.com", ".cloudflare-dns.com",
    ".auth0.com", ".epicgames.dev", ".epicgames.com", ".fandom.com",
]

BLOCK_BEGIN = "# >>> Zapret2GUI DiscordFix >>>"
BLOCK_END = "# <<< Zapret2GUI DiscordFix <<<"


class DiscordFixError(RuntimeError):
    pass


def _in_helper() -> bool:
    return os.environ.get("ZAPRET2_DISCORD_FIX_HELPER") == "1"


def _task_module():
    """Ленивая ссылка на Планировщик задач (в тестах можно вернуть None)."""
    if os.environ.get("ZAPRET2_DISCORD_FIX_NO_TASK") == "1":
        return None
    try:
        from core import discord_fix_task as task
        return task
    except Exception:
        return None


def _task_status() -> tuple[bool, str]:
    task = _task_module()
    if task is None:
        return False, "not_installed"
    try:
        return bool(task.installed()), str(task.state())
    except Exception:
        return False, "not_installed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _logs(root: Path) -> Path:
    p = Path(root) / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _state_path(root: Path) -> Path:
    return _logs(root) / "discord_fix_state.json"


def _backup_path(root: Path) -> Path:
    return _logs(root) / "discord_fix_hosts_backup.txt"


def _pool_path(root: Path) -> Path:
    return Path(root) / "lists" / "discord-candidates.json"


def load_pool(root: Path) -> list[str]:
    p = _pool_path(root)
    data = DEFAULT_CANDIDATES
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            data = [str(x) for x in raw if str(x).strip()]
    except (OSError, ValueError):
        pass
    out = []
    for ip in data:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            continue
        if ip not in out:
            out.append(ip)
    return out or list(DEFAULT_CANDIDATES)


def _read_state(root: Path) -> dict:
    try:
        data = json.loads(_state_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(root: Path, data: dict) -> None:
    p = _state_path(root)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _probe(ip: str, timeout: float = 2.0) -> bool:
    try:
        ctx = ssl.create_default_context()
        s = socket.create_connection((ip, 443), timeout=timeout)
        s.settimeout(timeout)
        ss = ctx.wrap_socket(s, server_hostname="discord.com")
        ss.close()
        return True
    except Exception:
        return False


def _probe_host(ip: str, host: str, timeout: float = 2.0) -> bool:
    """Проверить candidate именно с SNI нужного домена (валидный сертификат)."""
    try:
        ctx = ssl.create_default_context()
        s = socket.create_connection((ip, 443), timeout=timeout)
        s.settimeout(timeout)
        with ctx.wrap_socket(s, server_hostname=host) as ss:
            return bool(ss.getpeercert())
    except Exception:
        return False


def _direct_works(host: str, timeout: float = 2.0) -> bool:
    """Работает ли домен через текущий DNS/hosts без candidate."""
    try:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return False
    seen = set()
    for info in infos:
        ip = str(info[4][0])
        if ip in seen:
            continue
        seen.add(ip)
        if _probe_host(ip, host, timeout):
            return True
    return False


def choose_candidate(root: Path) -> str:
    pool = load_pool(root)
    rnd = random.SystemRandom()
    candidates = list(pool)
    rnd.shuffle(candidates)
    for ip in candidates[:20]:
        if _probe(ip):
            return ip
    raise DiscordFixError("ни один candidate IP не прошёл TLS-проверку")


STATIC_CANDIDATE_LIMIT = 8


def _select_static_mapping(root: Path) -> tuple[dict[str, str], dict[str, bool], list[str]]:
    """Для каждого статического домена: direct -> candidate только если direct мёртв."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        direct_list = list(pool.map(_direct_works, STATIC_HOSTS))
    direct = dict(zip(STATIC_HOSTS, direct_list))
    needed = [host for host in STATIC_HOSTS if not direct[host]]
    mapping: dict[str, str] = {}
    if not needed:
        return mapping, direct, needed
    pool_ips = list(load_pool(root))
    random.SystemRandom().shuffle(pool_ips)
    best: dict[str, str] = {}
    for ip in pool_ips[:STATIC_CANDIDATE_LIMIT]:
        if not _probe(ip):
            continue
        with ThreadPoolExecutor(max_workers=8) as pool:
            checks = list(pool.map(lambda h: (h, _probe_host(ip, h)), needed))
        current = {host: ip for host, ok in checks if ok}
        if len(current) > len(best):
            best = current
        if len(best) == len(needed):
            break
    return best, direct, needed


def _write_hosts_static(mapping: dict[str, str]) -> list[str]:
    """Заменить только записи для mapping, сохранив остальной hosts.

    Возвращает удалённые строки, чтобы disable мог их восстановить.
    """
    lines = _read_hosts()
    out: list[str] = []
    removed: list[str] = []
    skip = False
    for line in lines:
        s = line.strip()
        if s == BLOCK_BEGIN:
            skip = True
            continue
        if s == BLOCK_END:
            skip = False
            continue
        if skip:
            continue
        parts = s.split()
        if (s and not s.startswith("#") and len(parts) >= 2
                and any(h.lower() in mapping for h in parts[1:])):
            removed.append(line)
            continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    out += ["", BLOCK_BEGIN, "# static hosts fallback; disable via Zapret2GUI"]
    for host, ip in mapping.items():
        out.append(f"{ip} {host}")
    out.append(BLOCK_END)
    try:
        tmp = HOSTS_PATH.with_suffix(".z2tmp")
        tmp.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
        tmp.replace(HOSTS_PATH)
    except OSError as e:
        raise DiscordFixError(f"не удалось записать hosts: {e}") from e
    return removed


def _restore_hosts_removed(removed: list[str]) -> None:
    if not removed:
        return
    lines = _read_hosts()
    existing = set(lines)
    add = [line for line in removed if line not in existing]
    if not add:
        return
    try:
        HOSTS_PATH.write_text("\n".join(lines + add).rstrip() + "\n", encoding="utf-8")
    except OSError as e:
        raise DiscordFixError(f"не удалось восстановить hosts: {e}") from e


def _read_hosts() -> list[str]:
    try:
        return HOSTS_PATH.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as e:
        raise DiscordFixError(f"не удалось прочитать hosts: {e}") from e


def _host_matches(name: str) -> bool:
    n = name.lower().rstrip(".")
    if n in APEX_HOSTS:
        return True
    return any(n == z[1:] or n.endswith(z) for z in NRPT_ZONES)


def scan_hosts(root: Path) -> dict:
    lines = _read_hosts()
    entries = []
    for idx, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 2:
            continue
        for host in parts[1:]:
            if _host_matches(host):
                entries.append({"line": idx, "ip": parts[0], "host": host})
    managed = bool(_read_state(root).get("enabled"))
    return {"entries": entries, "count": len(entries), "managed": managed}


def _flush_dns() -> None:
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True,
                       timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _ps(script: str, timeout: float = 20.0) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        if r.returncode != 0:
            raise DiscordFixError(f"PowerShell rc={r.returncode}: {out[:300]}")
        return out
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DiscordFixError(f"PowerShell: {type(e).__name__}") from e


def _nrpt_add() -> None:
    zones = ",".join("'" + z + "'" for z in NRPT_ZONES)
    _ps(
        "$ErrorActionPreference='Stop'; "
        f"$zones=@({zones}); "
        f"Get-DnsClientNrptRule | Where-Object {{$_.DisplayName -eq '{NRPT_DISPLAY}'}} | "
        "Remove-DnsClientNrptRule -Force -ErrorAction SilentlyContinue; "
        f"foreach($z in $zones){{ Add-DnsClientNrptRule -Namespace $z "
        f"-NameServers '{LOCAL_DNS}' -DisplayName '{NRPT_DISPLAY}' | Out-Null }}"
    )


def _nrpt_remove() -> None:
    _ps(
        "$ErrorActionPreference='SilentlyContinue'; "
        f"Get-DnsClientNrptRule | Where-Object {{$_.DisplayName -eq '{NRPT_DISPLAY}'}} | "
        "Remove-DnsClientNrptRule -Force"
    )


def _nrpt_count() -> int:
    try:
        out = _ps(
            f"@(Get-DnsClientNrptRule | Where-Object {{$_.DisplayName -eq '{NRPT_DISPLAY}'}}).Count"
        )
        for token in out.split():
            if token.isdigit():
                return int(token)
    except DiscordFixError:
        pass
    return 0


def _write_hosts(ip: str) -> None:
    lines = _read_hosts()
    # backup делает apply; здесь только чистим и пишем
    out = []
    for line in lines:
        s = line.strip()
        if s in (BLOCK_BEGIN, BLOCK_END):
            continue
        parts = s.split()
        if s and not s.startswith("#") and len(parts) >= 2 and any(_host_matches(h) for h in parts[1:]):
            continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    out += ["", BLOCK_BEGIN, "# temporary workaround; disable via Zapret2GUI"]
    for host in APEX_HOSTS:
        out.append(f"{ip} {host}")
    out.append(BLOCK_END)
    try:
        tmp = HOSTS_PATH.with_suffix(".z2tmp")
        tmp.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
        tmp.replace(HOSTS_PATH)
    except OSError as e:
        raise DiscordFixError(f"не удалось записать hosts: {e}") from e


class _DnsServer:
    def __init__(self, ip: str) -> None:
        self.ip = ip
        self._stop = threading.Event()
        self._udp: Optional[socket.socket] = None
        self._tcp: Optional[socket.socket] = None
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        try:
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            u.bind((LOCAL_DNS, DNS_PORT))
            u.settimeout(0.5)
            t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            t.bind((LOCAL_DNS, DNS_PORT))
            t.listen(20)
            t.settimeout(0.5)
        except OSError as e:
            raise DiscordFixError(f"не удалось занять DNS-порт {LOCAL_DNS}:{DNS_PORT}: {e}") from e
        self._udp, self._tcp = u, t
        for target in (self._udp_loop, self._tcp_loop):
            th = threading.Thread(target=target, daemon=True)
            th.start()
            self._threads.append(th)

    def stop(self) -> None:
        self._stop.set()
        for s in (self._udp, self._tcp):
            try:
                if s:
                    s.close()
            except OSError:
                pass
        for th in self._threads:
            th.join(timeout=1.0)
        self._threads.clear()

    @property
    def running(self) -> bool:
        return bool(self._threads and any(t.is_alive() for t in self._threads))

    def _answer_a(self, query: bytes, qend: int) -> bytes:
        hdr = query[:2] + struct.pack("!HHHHH", 0x8180, 1, 1, 0, 0)
        ans = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 30, 4) + socket.inet_aton(self.ip)
        return hdr + query[12:qend] + ans

    @staticmethod
    def _nodata(query: bytes, qend: int) -> bytes:
        return query[:2] + struct.pack("!HHHHH", 0x8180, 1, 0, 0, 0) + query[12:qend]

    @staticmethod
    def _forward(query: bytes) -> Optional[bytes]:
        for up in (("1.1.1.1", 53), ("8.8.8.8", 53)):
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(1.2)
                s.sendto(query, up)
                data, _ = s.recvfrom(4096)
                return data
            except Exception:
                pass
            finally:
                if s:
                    try:
                        s.close()
                    except OSError:
                        pass
        return None

    @staticmethod
    def _query_name(q: bytes) -> tuple[Optional[str], int, int]:
        i, labels = 12, []
        while i < len(q):
            n = q[i]
            if n == 0:
                i += 1
                break
            if n & 0xC0 or i + 1 + n > len(q):
                return None, 0, 0
            i += 1
            labels.append(q[i:i + n].decode("ascii", "ignore"))
            i += n
        if i + 4 > len(q):
            return None, 0, 0
        qtype = struct.unpack("!H", q[i:i + 2])[0]
        return ".".join(labels).lower(), qtype, i + 4

    def _dispatch(self, q: bytes) -> Optional[bytes]:
        name, qtype, qend = self._query_name(q)
        if not name or not qend:
            return None
        if _host_matches(name):
            if qtype == 1:
                return self._answer_a(q, qend)
            return self._nodata(q, qend)
        return self._forward(q)

    def _udp_loop(self) -> None:
        while not self._stop.is_set():
            try:
                q, addr = self._udp.recvfrom(4096)  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                r = self._dispatch(q)
                if r:
                    self._udp.sendto(r, addr)  # type: ignore[union-attr]
            except Exception as e:
                applog("discord_fix", f"dns udp: {e!r}")

    def _tcp_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._tcp.accept()  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._tcp_conn, args=(conn,), daemon=True).start()

    def _tcp_conn(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(2.0)
            head = conn.recv(2)
            if len(head) < 2:
                return
            n = struct.unpack("!H", head)[0]
            data = b""
            while len(data) < n:
                chunk = conn.recv(n - len(data))
                if not chunk:
                    return
                data += chunk
            r = self._dispatch(data)
            if r:
                conn.sendall(struct.pack("!H", len(r)) + r)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass


_SERVER: Optional[_DnsServer] = None
_LOCK = threading.Lock()


def _server_status() -> tuple[bool, str]:
    global _SERVER
    with _LOCK:
        if _SERVER and _SERVER.running:
            return True, _SERVER.ip
        return False, ""


def _stop_server() -> None:
    global _SERVER
    with _LOCK:
        if _SERVER:
            _SERVER.stop()
            _SERVER = None


def _start_server(ip: str) -> None:
    global _SERVER
    with _LOCK:
        if _SERVER:
            _SERVER.stop()
        srv = _DnsServer(ip)
        srv.start()
        _SERVER = srv


def _shutdown_cleanup() -> None:
    """GUI закрывается - снять локальный DNS/NRPT, чтобы не оставлять
    систему с указателем на мёртвый 127.0.0.1:53. hosts остаются; при следующем
    запуске ensure_started поднимет заново (и проверит IP).

    Если helper работает как задача Планировщика, GUI его не трогает.
    """
    if not _in_helper():
        try:
            from core.utils import app_root
            st = _read_state(app_root())
            if st.get("enabled") and st.get("mode") == "task":
                return
        except Exception:
            pass
    _stop_server()
    try:
        _nrpt_remove()
    except Exception:
        pass


atexit.register(_shutdown_cleanup)


def ensure_started(root: Path) -> None:
    """После рестарта GUI: если обход включён, поднять DNS/NRPT заново.

    hosts уже лежат на месте; NRPT-правила тоже. Нужен только локальный DNS
    (он живёт в процессе GUI) и flush кэша.
    """
    st = _read_state(root)
    if not st.get("enabled"):
        return
    if st.get("mode") == "hosts":
        # Лёгкий режим: DNS-сервера/задачи нет, hosts уже записан.
        return
    if not _in_helper():
        svc = _task_module()
        if svc is not None:
            try:
                root_key = str(Path(root).resolve())
                if svc.installed():
                    if st.get("mode") != "task" or not st.get("task_root"):
                        st["mode"] = "task"
                        st["task_root"] = root_key
                        _write_state(root, st)
                    stale_root = bool(st.get("task_root")) and st.get("task_root") != root_key
                    if stale_root:
                        # приложение перенесли: задача всё ещё указывает на старый путь
                        if _try_task_enable(root):
                            st["mode"] = "task"
                            st["task_root"] = root_key
                            _write_state(root, st)
                            return
                        applog("discord_fix", "task path stale, reinstall failed")
                        return
                    if svc.state() != "running":
                        ok, msg = svc.start()
                        applog("discord_fix", f"task start: {msg}")
                        return
                    return
                elif st.get("mode") == "task":
                    # задачу удалили/потеряли: восстановить
                    if _try_task_enable(root):
                        st["mode"] = "task"
                        st["task_root"] = root_key
                        _write_state(root, st)
                        return
                    st["mode"] = "gui"
                    st.pop("task_root", None)
                    _write_state(root, st)
            except Exception:
                pass
    running, _ = _server_status()
    if running:
        return
    if not is_admin():
        applog("discord_fix", "ensure_started skipped: no admin")
        return
    ip = str(st.get("selected_ip") or "")
    if not ip:
        return
    try:
        # Один быстрый health-check на старт GUI: если старый candidate
        # умер - выбираем новый. Это не периодический опрос.
        if not _probe(ip):
            new_ip = choose_candidate(root)
            applog("discord_fix", f"startup probe failed for {ip}; rotate to {new_ip}")
            st["previous_ip"] = ip
            st["selected_ip"] = new_ip
            st["updated"] = _now()
            _write_state(root, st)
            ip = new_ip
        _write_hosts(ip)
        _start_server(ip)
        _nrpt_add()
        _flush_dns()
        applog("discord_fix", f"ensure_started ip={ip}")
    except Exception as e:
        applog("discord_fix", f"ensure_started failed: {e!r}")


def run_helper() -> None:
    """Фоновый режим для задачи Планировщика (без GUI).

    Задача стартует main.py --discord-fix-helper под SYSTEM. Держим DNS/NRPT
    до остановки задачи; GUI может закрываться.
    """
    os.environ["ZAPRET2_DISCORD_FIX_HELPER"] = "1"
    try:
        from core.utils import app_root
        root = app_root()
        applog("discord_fix", f"helper start root={root}")
        while True:
            st = _read_state(root)
            if not st.get("enabled"):
                applog("discord_fix", "helper: state disabled - exit")
                break
            try:
                ensure_started(root)
            except Exception as e:  # noqa: BLE001
                applog("discord_fix", f"helper ensure: {e!r}")
            time.sleep(8.0)
    finally:
        try:
            _stop_server()
            _nrpt_remove()
        except Exception:
            pass
        applog("discord_fix", "helper stopped")


def status(root: Path) -> dict:
    st = _read_state(root)
    running, running_ip = _server_status()
    enabled = bool(st.get("enabled"))
    task_installed, task_state = _task_status()
    nrpt = _nrpt_count() if running else 0
    hosts_ok = False
    try:
        txt = HOSTS_PATH.read_text(encoding="utf-8-sig", errors="replace")
        hosts_ok = BLOCK_BEGIN in txt and BLOCK_END in txt
    except OSError:
        pass
    mode = str(st.get("mode") or "")
    if not mode:
        mode = "task" if task_installed else ("gui" if running else "off")
    return {
        "enabled": enabled,
        "dns_running": running,
        "dns_ip": running_ip,
        "selected_ip": str(st.get("selected_ip") or running_ip or ""),
        "nrpt_rules": nrpt,
        "hosts_block": hosts_ok,
        "pool_size": len(load_pool(root)),
        "task_installed": task_installed,
        "task_state": task_state,
        "task_root": str(st.get("task_root") or ""),
        "mode": mode,
        "mapped_hosts": dict(st.get("mapped_hosts") or {}),
        "skipped_hosts": list(st.get("skipped_hosts") or []),
        "warning": ("Лёгкий hosts-обход: статические домены; динамический голос/стрим не покрыт."
                    if mode == "hosts" else
                    "Временный обход Cloudflare/Discord; при блокировке пула нужен WARP."),
    }



def _try_task_enable(root: Path) -> bool:
    """Поставить/запустить задачу Планировщика. False - откат на GUI."""
    if _in_helper():
        return False
    svc = _task_module()
    if svc is None:
        return False
    try:
        try:
            if svc.installed():
                svc.stop()
        except Exception:
            pass
        ok, _msg = svc.install(root)
        if not ok:
            applog("discord_fix", f"task install failed: {_msg}")
            return False
        ok, msg = svc.start()
        if not ok:
            applog("discord_fix", f"service start failed: {msg}")
            try:
                svc.remove()
            except Exception:
                pass
            return False
        applog("discord_fix", "service installed and started")
        return True
    except Exception as e:  # noqa: BLE001
        applog("discord_fix", f"service enable exception: {e!r}")
        return False


def enable_static(root: Path) -> dict:
    """Лёгкий hosts-only режим: без задачи, NRPT и локального DNS."""
    if not is_admin():
        raise DiscordFixError("нужны права администратора")
    if _read_state(root).get("enabled"):
        raise DiscordFixError("сначала отключите текущий режим обхода")
    # Лёгкий режим не должен сосуществовать с локальным DNS/задачей
    # от старого полного режима: убираем их, иначе они снова перепишут hosts.
    _stop_server()
    try:
        _nrpt_remove()
    except DiscordFixError:
        pass
    svc = _task_module()
    if svc is not None:
        try:
            if svc.installed():
                svc.stop()
                svc.remove()
        except Exception as e:  # noqa: BLE001
            applog("discord_fix", f"hosts-mode old task cleanup: {e!r}")
    mapping, direct, needed = _select_static_mapping(root)
    if not needed:
        raise DiscordFixError("статические домены доступны напрямую — hosts-обход не нужен")
    if not mapping:
        raise DiscordFixError("candidate не прошёл проверку ни для одного проблемного домена")
    try:
        _backup_path(root).write_text("\n".join(_read_hosts()) + "\n", encoding="utf-8")
    except OSError as e:
        raise DiscordFixError(f"не удалось сохранить backup hosts: {e}") from e
    removed = _write_hosts_static(mapping)
    selected = next(iter(mapping.values()))
    st = {
        "enabled": True,
        "mode": "hosts",
        "selected_ip": selected,
        "mapped_hosts": mapping,
        "skipped_hosts": [h for h in needed if h not in mapping],
        "static_direct": direct,
        "removed_hosts_lines": removed,
        "created": _now(),
        "updated": _now(),
        "pool_size": len(load_pool(root)),
        "hosts_backup": str(_backup_path(root)),
    }
    _write_state(root, st)
    _flush_dns()
    applog("discord_fix", f"enabled hosts-only ip={selected} mapped={len(mapping)}")
    return status(root)


def enable(root: Path, ip: Optional[str] = None) -> dict:
    if not is_admin():
        raise DiscordFixError("нужны права администратора")
    if _read_state(root).get("enabled"):
        raise DiscordFixError("сначала отключите текущий режим обхода")
    selected = ip or choose_candidate(root)
    if not _probe(selected):
        raise DiscordFixError(f"candidate {selected} не прошёл TLS-проверку")
    # backup hosts
    try:
        _backup_path(root).write_text("\n".join(_read_hosts()) + "\n", encoding="utf-8")
    except OSError as e:
        raise DiscordFixError(f"не удалось сохранить backup hosts: {e}") from e
    old_state = _read_state(root)
    st = {
        "enabled": True,
        "selected_ip": selected,
        "created": old_state.get("created") or _now(),
        "updated": _now(),
        "pool_size": len(load_pool(root)),
        "hosts_backup": str(_backup_path(root)),
    }
    try:
        _write_hosts(selected)
        _write_state(root, st)
        if _try_task_enable(root):
            st["mode"] = "task"
            st["task_root"] = str(root.resolve())
            _write_state(root, st)
            _flush_dns()
            applog("discord_fix", f"enabled task ip={selected}")
            return status(root)
        st["mode"] = "gui"
        st.pop("task_root", None)
        _write_state(root, st)
        _start_server(selected)
        _nrpt_add()
        _flush_dns()
    except Exception:
        _stop_server()
        try:
            _nrpt_remove()
        except DiscordFixError:
            pass
        try:
            HOSTS_PATH.write_text(_backup_path(root).read_text(encoding="utf-8"), encoding="utf-8")
            _flush_dns()
        except OSError:
            pass
        raise
    applog("discord_fix", f"enabled ip={selected} nrpt={_nrpt_count()}")
    return status(root)


def disable(root: Path) -> dict:
    st = _read_state(root)
    svc = _task_module()
    if svc is not None:
        try:
            if svc.installed():
                svc.stop()
                svc.remove()
        except Exception as e:  # noqa: BLE001
            applog("discord_fix", f"service remove: {e!r}")
    _stop_server()
    try:
        _nrpt_remove()
    except DiscordFixError:
        pass
    try:
        lines = _read_hosts()
        out, skip = [], False
        for line in lines:
            s = line.strip()
            if s == BLOCK_BEGIN:
                skip = True
                continue
            if s == BLOCK_END:
                skip = False
                continue
            if not skip:
                out.append(line)
        HOSTS_PATH.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    except OSError as e:
        raise DiscordFixError(f"не удалось очистить hosts: {e}") from e
    if st.get("mode") == "hosts":
        _restore_hosts_removed(list(st.get("removed_hosts_lines") or []))
    try:
        _state_path(root).unlink(missing_ok=True)
    except OSError:
        pass
    _flush_dns()
    applog("discord_fix", "disabled")
    return status(root)


def rotate(root: Path) -> dict:
    st = _read_state(root)
    if not st.get("enabled"):
        raise DiscordFixError("обход не включён")
    if st.get("mode") == "hosts":
        disable(root)
        return enable_static(root)
    selected = choose_candidate(root)
    old = st.get("selected_ip")
    svc = _task_module()
    service_mode = False
    if svc is not None and not _in_helper():
        try:
            service_mode = bool(svc.installed())
            if service_mode:
                svc.stop()
        except Exception:
            service_mode = False
    try:
        _write_hosts(selected)
        st.update(selected_ip=selected, updated=_now(), previous_ip=old)
        _write_state(root, st)
        if service_mode:
            ok, msg = svc.start()
            if not ok:
                raise DiscordFixError(f"service start failed: {msg}")
            _flush_dns()
            applog("discord_fix", f"rotated service {old} -> {selected}")
            return status(root)
        _start_server(selected)
        _nrpt_add()
        _flush_dns()
    except Exception:
        _stop_server()
        if old:
            try:
                _write_hosts(str(old))
                _start_server(str(old))
            except Exception:
                pass
        raise
    applog("discord_fix", f"rotated {old} -> {selected}")
    return status(root)
