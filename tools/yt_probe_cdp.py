"""yt_probe_cdp.py - измерение реальной доставки медиа YouTube через CDP.

Запускает Chromium (Chrome/Edge) с remote-debugging, открывает ролик,
собирает сетевые события videoplayback и состояние <video>, выдаёт метрики:
goodput, TTFB медиа, фризы, buffer health, фактическое разрешение.

Это диагностика, не обход: ничего не меняет в системе и не обещает фикс.

Пример:
  python tools/yt_probe_cdp.py --seconds 60 "https://www.youtube.com/watch?v=ID"
  python tools/yt_probe_cdp.py --json out.json URL1 URL2
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

MEDIA_HOST_SUFFIX = "googlevideo.com"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def devtools_ws(port: int, wait_s: float = 25.0) -> str:
    deadline = time.monotonic() + wait_s
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            ws = data.get("webSocketDebuggerUrl") or ""
            if ws:
                return ws
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(0.4)
    raise RuntimeError(f"devtools endpoint not available on port {port}: {last}")


def find_browser(explicit: str = "") -> str:
    if explicit:
        if not Path(explicit).is_file():
            raise SystemExit(f"browser not found: {explicit}")
        return explicit
    for p in CHROME_CANDIDATES:
        if p and Path(p).is_file():
            return p
    raise SystemExit("Chromium browser (Chrome/Edge) not found; pass --browser")


class WebSocket:
    """Минимальный клиент RFC6455 для CDP (без внешних зависимостей)."""

    def __init__(self, url: str, timeout: float = 10.0) -> None:
        rest = url[5:] if url.startswith("ws://") else url
        hostport, _, path = rest.partition("/")
        path = "/" + path
        host, _, port_s = hostport.partition(":")
        port = int(port_s or 80)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(0.2)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\nHost: {hostport}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("ws handshake closed")
            buf += chunk
        head, _, self._buf = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError("ws handshake failed: " + head[:200].decode("latin1"))
        self._frag = b""

    def _read_exact(self, n: int, deadline: float) -> bytes:
        while len(self._buf) < n:
            if time.monotonic() > deadline:
                raise TimeoutError("ws read timeout")
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise RuntimeError("ws closed")
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
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def send_text(self, text: str) -> None:
        self._send_frame(1, text.encode())

    def _pong(self, payload: bytes) -> None:
        try:
            self._send_frame(10, payload)
        except OSError:
            pass

    def recv_message(self, deadline: float) -> Optional[str]:
        frag = b""
        while True:
            b0 = self._read_exact(1, deadline)[0]
            b1 = self._read_exact(1, deadline)[0]
            fin = bool(b0 & 0x80)
            opcode = b0 & 0x0F
            masked = b1 & 0x80
            ln = b1 & 0x7F
            if ln == 126:
                ln = struct.unpack("!H", self._read_exact(2, deadline))[0]
            elif ln == 127:
                ln = struct.unpack("!Q", self._read_exact(8, deadline))[0]
            mask_key = self._read_exact(4, deadline) if masked else None
            payload = self._read_exact(ln, deadline)
            if mask_key:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            if opcode == 8:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 0
                reason = payload[2:].decode("utf-8", "replace")[:100]
                raise RuntimeError(f"ws closed code={code} reason={reason}")
            if opcode == 9:
                self._pong(payload)
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

    def eval_js(self, session: str, expression: str, user_gesture: bool = False,
               deadline_s: float = 5.0) -> Any:
        try:
            res = self.wait(self.send("Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": False,
                "userGesture": user_gesture,
            }, session), time.monotonic() + deadline_s)
            return (res.get("result") or {}).get("value")
        except Exception:  # noqa: BLE001
            return None

    def _handle(self, raw: Optional[str]) -> None:
        if not raw:
            return
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if "method" in msg:
            self.events.append(msg)

    def wait(self, msg_id: int, deadline: float) -> dict:
        while True:
            msg = self.ws.recv_message(deadline)
            if msg is None:
                continue
            try:
                parsed = json.loads(msg)
            except ValueError:
                continue
            if "id" in parsed:
                if parsed["id"] == msg_id:
                    if "error" in parsed:
                        raise RuntimeError(f"CDP error: {parsed['error']}")
                    return parsed.get("result", {})
            elif "method" in parsed:
                self.events.append(parsed)

    def pump(self, until: float) -> None:
        while time.monotonic() < until:
            try:
                self._handle(self.ws.recv_message(min(until, time.monotonic() + 0.2)))
            except TimeoutError:
                continue

    def drain(self) -> list[dict]:
        out = self.events[self._drained:]
        self._drained = len(self.events)
        return out

    def close(self) -> None:
        self.ws.close()


@dataclass
class MediaRun:
    url: str
    seconds: float
    media_bytes: int = 0
    first_byte_delta: Optional[float] = None
    request_ts: dict[str, float] = field(default_factory=dict)
    requests: dict[str, dict] = field(default_factory=dict)
    samples: list[dict] = field(default_factory=list)
    page_title: str = ""
    error: str = ""
    finished: set[str] = field(default_factory=set)
    failed: dict[str, str] = field(default_factory=dict)
    first_media_bytes_at: int = 0
    requested_quality: str = ""

    def as_dict(self) -> dict:
        duration = max(1.0, float(self.seconds))
        goodput = self.media_bytes * 8 / duration / 1e6 if self.media_bytes else 0.0
        return {
            "url": self.url,
            "title": self.page_title,
            "seconds": self.seconds,
            "media_bytes": self.media_bytes,
            "goodput_mbps": round(goodput, 3),
            "first_media_byte_ms": (round(self.first_byte_delta * 1000, 1)
                                    if self.first_byte_delta else None),
            "media_requests": sum(1 for r in self.requests.values() if r.get("media")),
            "media_finished": sum(1 for r in self.requests.values()
                                  if r.get("media") and r.get("id") in self.finished),
            "media_failed": {k: v for k, v in self.failed.items() if k in self.requests},
            "traffic_mb": round(self.media_bytes / 1e6, 2),
            "requested_quality": self.requested_quality,
            "samples": self.samples,
            "stalls": compute_stalls(self.samples),
            "max_resolution": max_resolution(self.samples),
            "buffer_min_s": min_buffer(self.samples),
            "error": self.error,
        }


def media_host(url: str) -> str:
    try:
        return url.split("//", 1)[1].split("/", 1)[0].split(":")[0]
    except IndexError:
        return ""


def is_media_url(url: str) -> bool:
    return media_host(url).endswith(MEDIA_HOST_SUFFIX)


def compute_stalls(samples: list[dict], min_advance_s: float = 1.0,
                   window_s: float = 3.0) -> int:
    """Фризы по продвижению currentTime в скользящем окне.

    При ~1 Гц выборке сравнение соседних значений шумное, поэтому считаем
    суммарное продвижение за окно: если за window_s воспроизведение не ушло
    вперёд даже на min_advance_s, это фриз. Трейлинг-фриз тоже учитывается.
    """
    pts = [(float(s["t"]), s.get("paused")) for s in samples
           if isinstance(s.get("t"), (int, float))]
    if len(pts) < 3:
        return 0
    stalls = 0
    in_stall = False
    for i in range(len(pts)):
        t_i = pts[i][0]
        j = i
        while j + 1 < len(pts) and pts[j][0] - t_i < window_s:
            j += 1
        if j == i:
            continue
        advanced = pts[j][0] - t_i
        if advanced < min_advance_s and not pts[i][1]:
            in_stall = True
        elif in_stall:
            stalls += 1
            in_stall = False
    if in_stall:
        stalls += 1
    return stalls


def max_resolution(samples: list[dict]) -> str:
    best = 0
    for s in samples:
        h = s.get("h") or 0
        if isinstance(h, (int, float)) and h > best:
            best = int(h)
    return f"{best}p" if best else "-"


def min_buffer(samples: list[dict]) -> Optional[float]:
    """Минимальный buffer-ahead (buf - t), включая настоящий ноль."""
    vals = [s.get("ahead") for s in samples if isinstance(s.get("ahead"), (int, float))]
    return round(min(vals), 2) if vals else None


SET_QUALITY_JS = """(() => {
  const p = document.getElementById('movie_player');
  if (!p) return 'no-player';
  try {
    if (p.setPlaybackQualityRange) p.setPlaybackQualityRange('%Q%', '%Q%');
    else if (p.setPlaybackQuality) p.setPlaybackQuality('%Q%');
    return 'quality-set';
  } catch (e) { return 'quality-err'; }
})()"""


ENSURE_PLAY_JS = """(() => {
  const v = document.querySelector('video');
  if (!v) return 'no-video';
  v.muted = true;
  if (v.paused) { v.play().catch(() => {}); return 'play'; }
  return 'playing';
})()"""


VIDEO_JS = """(() => {
  const v = document.querySelector('video');
  if (!v) return null;
  const q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : null;
  let buf = 0;
  try { if (v.buffered.length) buf = v.buffered.end(v.buffered.length - 1); } catch (e) {}
  return {
    t: v.currentTime, buf: buf, ahead: Math.max(0, buf - v.currentTime), ready: v.readyState,
    w: v.videoWidth, h: v.videoHeight,
    paused: v.paused, ended: v.ended,
    dropped: q ? q.droppedVideoFrames : 0,
    total: q ? q.totalVideoFrames : 0,
    err: v.error ? v.error.code : 0
  };
})()"""


def harvest(run: MediaRun, events: list[dict]) -> None:
    for msg in events:
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "Network.requestWillBeSent":
            rid = params.get("requestId")
            url = (params.get("request") or {}).get("url") or ""
            if rid and is_media_url(url):
                run.requests.setdefault(rid, {"media": True, "host": media_host(url)})
                run.request_ts.setdefault(rid, float(params.get("timestamp") or 0.0))
        elif method == "Network.responseReceived":
            rid = params.get("requestId")
            resp = params.get("response") or {}
            if not rid:
                continue
            url = resp.get("url") or ""
            rec = run.requests.setdefault(rid, {"media": is_media_url(url)})
            rec.update({
                "status": resp.get("status"),
                "remote": resp.get("remoteIPAddress") or "",
                "proto": resp.get("protocol") or "",
                "media": is_media_url(url),
                "host": media_host(url),
            })
        elif method == "Network.dataReceived":
            rid = params.get("requestId")
            rec = run.requests.get(rid) or {}
            if not rec.get("media"):
                continue
            ts = float(params.get("timestamp") or 0.0)
            run.media_bytes += int(params.get("encodedDataLength")
                                   or params.get("dataLength") or 0)
            if run.first_byte_delta is None:
                sent = run.request_ts.get(rid)
                if sent:
                    run.first_byte_delta = max(0.0, ts - sent)
        elif method == "Network.loadingFinished":
            rid = params.get("requestId")
            if rid:
                run.finished.add(rid)
        elif method == "Network.loadingFailed":
            rid = params.get("requestId")
            if rid:
                run.failed[rid] = str(params.get("errorText") or params.get("blockedReason") or "failed")


def probe(url: str, seconds: float, browser: str, profile: str,
          extra_seconds: float = 5.0, attach_port: int = 0,
          max_bytes: int = 0, quality: str = "") -> MediaRun:
    run = MediaRun(url=url, seconds=seconds)
    proc = None
    cdp = None
    try:
        args = [
            browser,
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check",
            "--autoplay-policy=no-user-gesture-required",
            "--mute-audio",
            "--window-position=-32000,-32000", "--window-size=1280,720",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--disable-features=CalculateNativeWinOcclusion",
            "about:blank",
        ]
        if attach_port:
            ws_url = devtools_ws(attach_port, wait_s=10.0)
        else:
            port = free_port()
            args[1] = f"--remote-debugging-port={port}"
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ws_url = devtools_ws(port)
        cdp = CDP(ws_url)
        cdp.wait(cdp.send("Browser.getVersion"), time.monotonic() + 10)
        tid = cdp.wait(cdp.send("Target.createTarget", {"url": "about:blank"}),
                       time.monotonic() + 10)["targetId"]
        sid = cdp.wait(cdp.send("Target.attachToTarget",
                                {"targetId": tid, "flatten": True}),
                       time.monotonic() + 10)["sessionId"]
        for method in ("Network.enable", "Page.enable", "Runtime.enable"):
            cdp.wait(cdp.send(method, {}, sid), time.monotonic() + 10)

        start = time.monotonic()
        try:
            cdp.wait(cdp.send("Page.bringToFront", {}, sid), time.monotonic() + 5)
        except Exception:
            pass
        cdp.wait(cdp.send("Page.navigate", {"url": url}, sid), time.monotonic() + 20)
        end = start + seconds + extra_seconds
        next_sample = start + 1.0
        while time.monotonic() < end:
            cdp.pump(min(end, time.monotonic() + 0.4))
            harvest(run, cdp.drain())
            if max_bytes and run.media_bytes >= max_bytes:
                break
            if time.monotonic() >= next_sample:
                next_sample += 1.0
                if not run.samples:
                    cdp.eval_js(sid, ENSURE_PLAY_JS, user_gesture=True)
                if quality:
                    cdp.eval_js(sid, SET_QUALITY_JS.replace("%Q%", quality), user_gesture=True)
                val = cdp.eval_js(sid, VIDEO_JS)
                if isinstance(val, dict):
                    run.samples.append(val)
                    if not run.first_media_bytes_at and run.media_bytes:
                        run.first_media_bytes_at = run.media_bytes
        cdp.pump(time.monotonic() + 0.5)
        harvest(run, cdp.drain())
        try:
            t = cdp.wait(cdp.send("Runtime.evaluate", {
                "expression": "document.title", "returnByValue": True}, sid),
                time.monotonic() + 5)
            run.page_title = str((t.get("result") or {}).get("value") or "")[:120]
        except Exception:
            pass
    except Exception as e:  # noqa: BLE001
        run.error = f"{type(e).__name__}: {e}"
    finally:
        if cdp is not None:
            if proc is not None:
                try:
                    cdp.wait(cdp.send("Browser.close", {}), time.monotonic() + 5)
                except Exception:
                    pass
            cdp.close()
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    return run


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="YouTube media delivery probe (CDP)")
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--seconds", type=float, default=20.0,
                    help="длительность замера, сек (по умолчанию 20; максимум 60)")
    ap.add_argument("--browser", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--keep-profile", action="store_true")
    ap.add_argument("--attach-port", type=int, default=0,
                    help="attach to an already running browser (debug build/test)")
    ap.add_argument("--max-mb", type=float, default=12.0,
                    help="лимит трафика на один ролик, МБ (0 = без лимита)")
    ap.add_argument("--quality", default="480",
                    help="потолок качества для замера (480/720/1080/max)")
    args = ap.parse_args(argv)

    browser = find_browser(args.browser)
    results = []
    for url in args.urls:
        profile = tempfile.mkdtemp(prefix="yt-probe-")
        try:
            seconds = min(60.0, max(5.0, args.seconds))
            quality = "" if args.quality.lower() == "max" else args.quality
            run = probe(url, seconds, browser, profile,
                        attach_port=args.attach_port,
                        max_bytes=int(args.max_mb * 1e6) if args.max_mb else 0,
                        quality=quality)
            run.requested_quality = args.quality
            data = run.as_dict()
            results.append(data)
            print(f"\n=== {url}")
            print(json.dumps({k: v for k, v in data.items() if k != "samples"},
                             ensure_ascii=False, indent=2))
        finally:
            if not args.keep_profile:
                shutil.rmtree(profile, ignore_errors=True)
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
