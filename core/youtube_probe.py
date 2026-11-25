"""Наблюдатель доставки YouTube через CDP (Windows, Chrome/Edge).

Модуль запускает отдельный браузер с временным профилем, открывает ролик и
собирает наблюдаемые данные: состояние <video>, сетевые байты медиа, ошибки
запросов. Ничего не чинит и не меняет в системе.

Два прохода:
  1) discover — короткий прогон, собираем реальные медиа-хосты сессии;
  2) measure  — перезапуск с --origin-to-force-quic-on для этих хостов,
     иначе свежий профиль уходит в TCP и на GGC-сетях получает RST.

DoH в профиле (Cloudflare) нужен, чтобы браузер видел HTTPS-RR alpn=h3 так
же, как в браузере пользователя с включённым Secure DNS.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from core import youtube_delivery as yd

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

MEDIA_SUFFIX = "googlevideo.com"
DOH_TEMPLATE = "https://chrome.cloudflare-dns.com/dns-query"
SKIP_ERRORS = {"net::ERR_ABORTED", "net::ERR_BLOCKED_BY_CLIENT"}


def find_browser(explicit: str = "") -> str:
    if explicit and Path(explicit).is_file():
        return explicit
    for p in CHROME_CANDIDATES:
        if p and Path(p).is_file():
            return p
    raise RuntimeError("Не найден Chrome/Edge для проверки")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _devtools_ws(port: int, wait_s: float = 25.0) -> str:
    import urllib.request
    deadline = time.monotonic() + wait_s
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            ws = data.get("webSocketDebuggerUrl") or ""
            if ws:
                return ws
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(0.3)
    raise RuntimeError(f"DevTools не поднялся: {last}")


class WebSocket:
    """Минимальный клиент RFC6455 (CDP); без внешних зависимостей."""

    def __init__(self, url: str, timeout: float = 10.0) -> None:
        rest = url[5:] if url.startswith("ws://") else url
        hostport, _, path = rest.partition("/")
        host, _, port_s = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port_s or 80)), timeout=timeout)
        self.sock.settimeout(0.2)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket: соединение закрыто на handshake")
            buf += chunk
        head, _, self._buf = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError("WebSocket: handshake отклонён")

    def _read_exact(self, n: int, deadline: float) -> bytes:
        while len(self._buf) < n:
            if time.monotonic() > deadline:
                raise TimeoutError("WebSocket: таймаут чтения")
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise RuntimeError("WebSocket: закрыт")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode: int, data: bytes) -> None:
        header = bytearray([0x80 | opcode])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack("!H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def send_text(self, text: str) -> None:
        self._send_frame(1, text.encode())

    def recv_message(self, deadline: float) -> Optional[str]:
        frag = b""
        while True:
            b0 = self._read_exact(1, deadline)[0]
            b1 = self._read_exact(1, deadline)[0]
            fin, opcode = bool(b0 & 0x80), b0 & 0x0F
            masked, ln = b1 & 0x80, b1 & 0x7F
            if ln == 126:
                ln = struct.unpack("!H", self._read_exact(2, deadline))[0]
            elif ln == 127:
                ln = struct.unpack("!Q", self._read_exact(8, deadline))[0]
            mask = self._read_exact(4, deadline) if masked else None
            payload = self._read_exact(ln, deadline)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 8:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 0
                raise RuntimeError(f"WebSocket закрыт (code={code})")
            if opcode == 9:
                try:
                    self._send_frame(10, payload)
                except OSError:
                    pass
                continue
            if opcode == 10:
                continue
            if opcode in (1, 2):
                frag = payload
            elif opcode == 0:
                frag += payload
            else:
                continue
            if fin:
                return frag.decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class CDP:
    def __init__(self, ws_url: str) -> None:
        self.ws = WebSocket(ws_url)
        self._id = 0
        self.events: list[dict] = []
        self._drained = 0

    def send(self, method: str, params: Optional[dict] = None, session: str = "") -> int:
        self._id += 1
        msg: dict[str, Any] = {"id": self._id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.ws.send_text(json.dumps(msg))
        return self._id

    def wait(self, msg_id: int, deadline: float) -> dict:
        while True:
            raw = self.ws.recv_message(deadline)
            if raw is None:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "id" in msg:
                if msg["id"] == msg_id:
                    if "error" in msg:
                        raise RuntimeError(f"CDP: {msg['error']}")
                    return msg.get("result", {})
            elif "method" in msg:
                self.events.append(msg)

    def pump(self, until: float) -> None:
        while time.monotonic() < until:
            try:
                raw = self.ws.recv_message(min(until, time.monotonic() + 0.2))
            except TimeoutError:
                continue
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "method" in msg:
                self.events.append(msg)

    def drain(self) -> list[dict]:
        out = self.events[self._drained:]
        self._drained = len(self.events)
        return out

    def eval_js(self, session: str, expression: str, *, user_gesture: bool = False,
                await_promise: bool = False, deadline_s: float = 5.0) -> Any:
        try:
            res = self.wait(self.send("Runtime.evaluate", {
                "expression": expression, "returnByValue": True,
                "awaitPromise": await_promise, "userGesture": user_gesture,
            }, session), time.monotonic() + deadline_s)
            return (res.get("result") or {}).get("value")
        except Exception:  # noqa: BLE001
            return None

    def close(self) -> None:
        self.ws.close()


VIDEO_JS = """(() => {
  const v = document.querySelector('video');
  if (!v) return {video: false};
  const q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : null;
  let end = 0;
  try {
    for (let i = 0; i < v.buffered.length; i++) {
      if (v.currentTime >= v.buffered.start(i) && v.currentTime <= v.buffered.end(i)) {
        end = v.buffered.end(i); break;
      }
    }
    if (!end && v.buffered.length) end = v.buffered.end(v.buffered.length - 1);
  } catch (e) {}
  return {
    video: true, t: v.currentTime, ahead: Math.max(0, end - v.currentTime),
    ready: v.readyState, w: v.videoWidth, h: v.videoHeight,
    paused: v.paused, ended: v.ended,
    dropped: q ? q.droppedVideoFrames : 0, total: q ? q.totalVideoFrames : 0,
    err: v.error ? v.error.code : 0
  };
})()"""

ENSURE_PLAY_JS = """(() => {
  const v = document.querySelector('video');
  if (!v) return 'no-video';
  v.muted = true;
  if (v.paused) {
    const p = v.play();
    if (p && p.catch) p.catch(e => { window.__ytProbePlayError = String(e && e.name || e); });
    return 'play';
  }
  return 'playing';
})()"""

STATE_JS = """(() => {
  const p = document.getElementById('movie_player');
  const v = document.querySelector('video');
  const err = document.querySelector('.ytp-error');
  let s = {};
  try { s = (p && p.getStatsForNerds) ? p.getStatsForNerds() : {}; } catch (e) {}
  return {
    present: !!p, state: (p && p.getPlayerState) ? p.getPlayerState() : null,
    error: err ? String(err.innerText || '').slice(0, 300) : '',
    width: v ? v.videoWidth : 0, height: v ? v.videoHeight : 0,
    play_error: window.__ytProbePlayError || ''
  };
})()"""

QUALITY_JS = """(() => {
  const p = document.getElementById('movie_player');
  if (!p) return 'no-player';
  try {
    if (p.setPlaybackQualityRange) p.setPlaybackQualityRange('%Q%', '%Q%');
    else if (p.setPlaybackQuality) p.setPlaybackQuality('%Q%');
    return 'ok';
  } catch (e) { return 'err'; }
})()"""


def _write_profile_prefs(profile: Path) -> None:
    default = profile / "Default"
    default.mkdir(parents=True, exist_ok=True)
    prefs = {"dns_over_https": {"mode": "secure", "templates": DOH_TEMPLATE}}
    (default / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")


def _launch(browser: str, profile: Path, force_hosts: list[str]) -> tuple[subprocess.Popen, int]:
    port = _free_port()
    args = [
        browser,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check", "--disable-sync",
        "--disable-extensions", "--mute-audio",
        "--autoplay-policy=no-user-gesture-required",
        "--window-size=1024,640", "--window-position=40,40",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
        "--enable-quic",
    ]
    for host in force_hosts:
        args.append(f"--origin-to-force-quic-on={host}:443")
    args.append("about:blank")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc, port


def _kill_tree(proc: Optional[subprocess.Popen], profile: Path) -> None:
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
    # дети после terminate: только по владельцу профиля, не по имени вслепую
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' or Name='msedge.exe'\" | "
             "Where-Object { $_.CommandLine -like '*" + str(profile) + "*' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:  # noqa: BLE001
        pass
    for _ in range(10):
        try:
            shutil.rmtree(profile, ignore_errors=False)
            break
        except OSError:
            time.sleep(0.3)


@dataclass
class RunResult:
    label: str
    video_id: str
    url: str
    metrics: yd.RunMetrics
    verdict: dict
    error: str = ""
    samples: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "video_id": self.video_id,
            "url": self.url,
            "metrics": self.metrics.as_dict(),
            "verdict": self.verdict,
            "error": self.error,
        }


def _media_host(url: str) -> str:
    try:
        return url.split("//", 1)[1].split("/", 1)[0].split(":")[0]
    except IndexError:
        return ""


def _run_pass(browser: str, url: str, *, window_s: float, quality: str,
              max_bytes: int, force_hosts: list[str], discover_s: float = 0.0,
              progress: Optional[Callable[[str], None]] = None) -> dict:
    """Один прогон. discover_s>0 — только сбор медиа-хостов, без метрик."""
    profile = Path(tempfile.mkdtemp(prefix="z2yt-"))
    _write_profile_prefs(profile)
    proc: Optional[subprocess.Popen] = None
    cdp: Optional[CDP] = None
    out: dict = {"media_hosts": [], "samples": [], "byte_events": [],
                 "request_errors": {}, "error": "",
                 "player": {}, "media_bytes": 0, "discovered": []}
    try:
        proc, port = _launch(browser, profile, force_hosts)
        cdp = CDP(_devtools_ws(port))
        cdp.wait(cdp.send("Browser.getVersion"), time.monotonic() + 10)
        tid = cdp.wait(cdp.send("Target.createTarget", {"url": "about:blank"}),
                       time.monotonic() + 10)["targetId"]
        sid = cdp.wait(cdp.send("Target.attachToTarget",
                                {"targetId": tid, "flatten": True}),
                       time.monotonic() + 10)["sessionId"]
        for method in ("Network.enable", "Page.enable", "Runtime.enable"):
            cdp.wait(cdp.send(method, {}, sid), time.monotonic() + 10)
        try:
            cdp.wait(cdp.send("Page.bringToFront", {}, sid), time.monotonic() + 5)
        except Exception:  # noqa: BLE001
            pass

        media_ids: set[str] = set()
        nav_at = time.monotonic()
        cdp.wait(cdp.send("Page.navigate", {"url": url}, sid), time.monotonic() + 20)
        deadline = nav_at + (discover_s or window_s) + 8
        next_sample = nav_at + 1.0
        last_bytes = 0
        started = False
        while time.monotonic() < deadline:
            cdp.pump(min(deadline, time.monotonic() + 0.4))
            events = cdp.drain()
            for msg in events:
                method = msg.get("method")
                params = msg.get("params") or {}
                if method == "Network.requestWillBeSent":
                    url_i = (params.get("request") or {}).get("url") or ""
                    if _media_host(url_i).endswith(MEDIA_SUFFIX):
                        media_ids.add(params.get("requestId"))
                        host = _media_host(url_i)
                        if host and host not in out["media_hosts"]:
                            out["media_hosts"].append(host)
                elif method == "Network.dataReceived":
                    if params.get("requestId") in media_ids:
                        out["media_bytes"] += int(params.get("encodedDataLength")
                                                   or params.get("dataLength") or 0)
                elif method == "Network.responseReceived":
                    if params.get("requestId") in media_ids:
                        status = (params.get("response") or {}).get("status") or 0
                        if status >= 400:
                            out["request_errors"][f"HTTP {status}"] = (
                                out["request_errors"].get(f"HTTP {status}", 0) + 1)
                elif method == "Network.loadingFailed":
                    if params.get("requestId") in media_ids:
                        err = str(params.get("errorText") or "")
                        if err and err not in SKIP_ERRORS:
                            out["request_errors"][err] = (
                                out["request_errors"].get(err, 0) + 1)
            if discover_s:
                if out["media_hosts"]:
                    break
                continue
            if max_bytes and out["media_bytes"] >= max_bytes:
                break
            if time.monotonic() >= next_sample:
                next_sample += 1.0
                now = time.monotonic() - nav_at
                if not started:
                    cdp.eval_js(sid, ENSURE_PLAY_JS, user_gesture=True)
                if quality:
                    cdp.eval_js(sid, QUALITY_JS.replace("%Q%", quality),
                                user_gesture=True)
                val = cdp.eval_js(sid, VIDEO_JS)
                if isinstance(val, dict):
                    val["ts"] = now
                    out["samples"].append(val)
                    if val.get("t", 0) > 0:
                        started = True
                delta = out["media_bytes"] - last_bytes
                out["byte_events"].append({"dt": 1.0, "delta": delta})
                last_bytes = out["media_bytes"]
                if progress:
                    progress(f"наблюдение {int(now)} с")
        if not discover_s:
            out["player"] = cdp.eval_js(sid, STATE_JS) or {}
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        if cdp is not None and not discover_s:
            try:
                cdp.wait(cdp.send("Browser.close"), time.monotonic() + 5)
            except Exception:  # noqa: BLE001
                pass
        if cdp is not None:
            cdp.close()
        _kill_tree(proc, profile)
    return out


def discover_media_hosts(video_id: str, *, browser: str = "", seconds: float = 12.0,
                        progress: Optional[Callable[[str], None]] = None) -> list[str]:
    """Короткий прогон: узнать реальные медиа-хосты сессии (для force-QUIC)."""
    browser = browser or find_browser()
    if progress:
        progress("поиск медиа-хостов")
    data = _run_pass(browser, yd.canonical_watch_url(video_id),
                     window_s=seconds, quality="", max_bytes=0,
                     force_hosts=[], discover_s=seconds, progress=progress)
    return list(data.get("media_hosts") or [])


def open_quic_session(video_id: str, profile_dir: Path, *, hosts: list[str],
                      browser: str = "",
                      progress: Optional[Callable[[str], None]] = None) -> dict:
    """Открыть ролик в отдельном Edge/Chrome с принудительным QUIC.

    Окно остаётся открытым для просмотра; профиль постоянный (в logs/), чтобы
    Alt-Svc/настройки переживали запуск. Возвращает {pid, port, url, hosts}.
    """
    browser = browser or find_browser()
    profile = Path(profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("запуск браузера")
    proc, port = _launch(browser, profile, hosts[:8])
    try:
        _devtools_ws(port, wait_s=30.0)
    except Exception:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        raise
    url = yd.canonical_watch_url(video_id)
    try:
        import urllib.request as _ur
        _ur.urlopen(f"http://127.0.0.1:{port}/json/new?{url}".replace(" ", "%20"),
                    timeout=10, data=b"")
    except Exception:
        pass
    return {"pid": int(getattr(proc, "pid", 0) or 0), "port": port,
            "url": url, "hosts": list(hosts), "profile": str(profile)}


def close_quic_session(profile_dir: Path) -> None:
    """Закрыть сессию: погасить процессы нашего профиля и удалить профиль."""
    profile = Path(profile_dir)
    _kill_tree(None, profile)


def probe_video(video_id: str, *, label: str = "", window_s: float = yd.DEFAULT_WINDOW_S,
                quality: str = "480", max_bytes: int = 12_000_000,
                browser: str = "", progress: Optional[Callable[[str], None]] = None) -> RunResult:
    """Полный цикл: discover медиа-хостов → замер с force-QUIC."""
    browser = browser or find_browser()
    url = yd.canonical_watch_url(video_id)
    window_s = max(yd.MIN_WINDOW_S, min(yd.MAX_WINDOW_S, float(window_s)))

    if progress:
        progress("поиск медиа-хостов")
    first = _run_pass(browser, url, window_s=window_s, quality=quality,
                      max_bytes=max_bytes, force_hosts=[], discover_s=12.0,
                      progress=progress)
    hosts = first.get("media_hosts") or []
    if progress:
        progress(f"замер ({len(hosts)} хостов)")
    data = _run_pass(browser, url, window_s=window_s, quality=quality,
                     max_bytes=max_bytes, force_hosts=hosts[:8], progress=progress)
    new_hosts = [h for h in (data.get("media_hosts") or []) if h not in hosts]
    if new_hosts and not data.get("samples") and not data.get("error"):
        if progress:
            progress("повтор с новыми хостами")
        hosts = (hosts + new_hosts)[:8]
        data = _run_pass(browser, url, window_s=window_s, quality=quality,
                         max_bytes=max_bytes, force_hosts=hosts, progress=progress)

    samples = data.get("samples") or []
    player = data.get("player") or {}
    metrics = yd.compute_metrics(
        samples, window_s=window_s, byte_events=data.get("byte_events"),
        request_errors=data.get("request_errors"))
    if data.get("media_bytes") and not metrics.media_bytes:
        metrics.media_bytes = int(data["media_bytes"])
        metrics.traffic_mb = metrics.media_bytes / 1e6
    content_unavailable = ""
    if player.get("error") and ("недоступ" in str(player.get("error")).lower()
                                or "unavailable" in str(player.get("error")).lower()):
        content_unavailable = str(player.get("error"))[:300]
    verdict = yd.verdict(metrics,
                         player_error=str(player.get("play_error") or ""),
                         content_unavailable=content_unavailable)
    return RunResult(label=label or video_id, video_id=video_id, url=url,
                     metrics=metrics, verdict=verdict,
                     error=str(data.get("error") or ""), samples=samples)
