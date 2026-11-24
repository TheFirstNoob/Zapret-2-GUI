"""Temporary YouTube GGC DNS steering worker (test build).

Separate from the Discord worker: no scheduled task, no hosts changes.
Session-only: local DNS on 127.0.0.1:53 + NRPT suffix .googlevideo.com.
Requires admin. Default off. Chrome/Edge Secure DNS may bypass NRPT.
"""
from __future__ import annotations

import atexit
import json
import socket
import ssl
import struct
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.admin import is_admin
from core.applog import log as applog

LOCAL_DNS = "127.0.0.1"
DNS_PORT = 53
DISPLAY = "Zapret2GUI YouTubeFix"
ZONE = ".googlevideo.com"

# Candidates are only preflight-qualified (TLS/SNI), not media-proven.
# Put likely-reachable edges first; user can override via API/state.
GOOGLE_EDGE_CANDIDATES = [
    "74.125.131.102",
    "142.251.155.155",
    "74.125.131.114",
    "74.125.131.130",
    "173.194.220.198",
    "74.125.205.157",
    "74.125.205.95",
    "74.125.131.100",
]

BLOCK_BEGIN = "# >>> Zapret2GUI YouTubeFix >>>"
BLOCK_END = "# <<< Zapret2GUI YouTubeFix <<<"


class YouTubeFixError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _logs(root: Path) -> Path:
    p = Path(root) / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _state_path(root: Path) -> Path:
    return _logs(root) / "youtube_fix_state.json"


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


def _ps(script: str, timeout: float = 20.0) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        if r.returncode != 0:
            raise YouTubeFixError(f"PowerShell rc={r.returncode}: {out[:300]}")
        return out
    except (OSError, subprocess.TimeoutExpired) as e:
        raise YouTubeFixError(f"PowerShell: {type(e).__name__}") from e


def _nrpt_add() -> None:
    _ps(
        "$ErrorActionPreference='Stop'; "
        f"Get-DnsClientNrptRule | Where-Object {{$_.DisplayName -eq '{DISPLAY}'}} | "
        "Remove-DnsClientNrptRule -Force -ErrorAction SilentlyContinue; "
        f"Add-DnsClientNrptRule -Namespace '{ZONE}' -NameServers '{LOCAL_DNS}' "
        f"-DisplayName '{DISPLAY}' | Out-Null"
    )


def _nrpt_remove() -> None:
    _ps(
        "$ErrorActionPreference='SilentlyContinue'; "
        f"Get-DnsClientNrptRule | Where-Object {{$_.DisplayName -eq '{DISPLAY}'}} | "
        "Remove-DnsClientNrptRule -Force"
    )


def _nrpt_count() -> int:
    try:
        out = _ps(
            f"@(Get-DnsClientNrptRule | Where-Object {{$_.DisplayName -eq '{DISPLAY}'}}).Count"
        )
        for tok in out.split():
            if tok.isdigit():
                return int(tok)
    except YouTubeFixError:
        pass
    return 0


def _flush_dns() -> None:
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True,
                       timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        pass


def _is_googlevideo(name: str) -> bool:
    n = (name or "").lower().rstrip(".")
    return n == "googlevideo.com" or n.endswith(ZONE)


def _probe_edge(ip: str, timeout: float = 2.5) -> bool:
    """TLS/SNI preflight only; it does NOT qualify media delivery."""
    try:
        ctx = ssl.create_default_context()
        s = socket.create_connection((ip, 443), timeout=timeout)
        s.settimeout(timeout)
        with ctx.wrap_socket(s, server_hostname="redirector.googlevideo.com"):
            return True
    except Exception:
        return False


def choose_edge(preferred: str = "", exclude: str = "") -> str:
    if preferred and preferred != exclude:
        try:
            if _probe_edge(preferred):
                return preferred
        except Exception:
            pass
    for ip in GOOGLE_EDGE_CANDIDATES:
        if ip == exclude:
            continue
        if _probe_edge(ip):
            return ip
    raise YouTubeFixError("ни один Google edge candidate не прошёл TLS preflight")


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
            raise YouTubeFixError(
                f"не удалось занять DNS-порт {LOCAL_DNS}:{DNS_PORT}: {e}") from e
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
        if _is_googlevideo(name):
            if qtype == 1:
                return self._answer_a(q, qend)
            if qtype == 28:
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
                applog("youtube_fix", f"dns udp: {e!r}")

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


def _start_server(ip: str) -> None:
    global _SERVER
    with _LOCK:
        if _SERVER:
            _SERVER.stop()
        srv = _DnsServer(ip)
        srv.start()
        _SERVER = srv


def _stop_server() -> None:
    global _SERVER
    with _LOCK:
        if _SERVER:
            _SERVER.stop()
            _SERVER = None


def _server_status() -> tuple[bool, str]:
    with _LOCK:
        if _SERVER and _SERVER.running:
            return True, _SERVER.ip
        return False, ""


def status(root: Path) -> dict:
    st = _read_state(root)
    running, ip = _server_status()
    return {
        "enabled": bool(st.get("enabled")) and running,
        "dns_running": running,
        "selected_ip": str(st.get("selected_ip") or ip or ""),
        "nrpt_rules": _nrpt_count(),
        "mode": "youtube" if (st.get("enabled") and running) else "off",
        "zone": ZONE,
        "warning": ("Тестовый YouTube GGC worker: NRPT .googlevideo.com + локальный DNS. "
                    "Chrome/Edge Secure DNS может обойти; WARP при нерабочем edge."),
    }


def enable(root: Path, ip: str = "") -> dict:
    if not is_admin():
        raise YouTubeFixError("нужны права администратора")
    st = _read_state(root)
    if st.get("enabled"):
        raise YouTubeFixError("YouTube-режим уже включён")
    # Discord local DNS already owns 53; do not steal it.
    try:
        from core.discord_fix import status as dstatus
        if dstatus(Path(root)).get("dns_running"):
            raise YouTubeFixError("порт 53 занят Discord-воркером: сначала выключите его")
    except YouTubeFixError:
        raise
    except Exception:
        pass
    selected = choose_edge(str(ip or ""))
    _nrpt_add()
    try:
        _start_server(selected)
    except Exception:
        try:
            _nrpt_remove()
        except Exception:
            pass
        raise
    _write_state(root, {
        "enabled": True,
        "selected_ip": selected,
        "created": _now(),
        "zone": ZONE,
    })
    _flush_dns()
    applog("youtube_fix", f"enabled edge={selected}")
    return status(root)


def disable(root: Path) -> dict:
    _stop_server()
    try:
        _nrpt_remove()
    except YouTubeFixError:
        pass
    try:
        _state_path(root).unlink(missing_ok=True)
    except OSError:
        pass
    _flush_dns()
    applog("youtube_fix", "disabled")
    return status(root)


def rotate(root: Path) -> dict:
    st = _read_state(root)
    if not st.get("enabled"):
        raise YouTubeFixError("YouTube-режим не включён")
    old = str(st.get("selected_ip") or "")
    new = choose_edge(exclude=old)
    _start_server(new)
    st.update(selected_ip=new, updated=_now())
    _write_state(root, st)
    _flush_dns()
    applog("youtube_fix", f"rotated {old} -> {new}")
    return status(root)


def ensure_started(root: Path) -> None:
    st = _read_state(root)
    if not st.get("enabled"):
        return
    if not is_admin():
        return
    try:
        _nrpt_add()
        _start_server(str(st.get("selected_ip") or ""))
        _flush_dns()
    except Exception as e:
        applog("youtube_fix", f"ensure_started failed: {e!r}")


def _shutdown_cleanup() -> None:
    try:
        _stop_server()
        _nrpt_remove()
    except Exception:
        pass


atexit.register(_shutdown_cleanup)
