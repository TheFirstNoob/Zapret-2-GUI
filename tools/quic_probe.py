r"""quic_probe.py — настоящая QUIC/HTTP3-проба (niquests+qh3) по контракту точности.

Контракт (12.10, платформа + ревью):
  - принудительный H3: Session(disable_http1=True, disable_http2=True) +
    quic_cache_layer.add_domain(host) — без TCP-разогрева (Alt-Svc не нужен);
  - УСПЕХ только при фактическом http_version == 30 (иначе NOT-H3/ошибка);
  - свежее соединение на каждую пробу (правило strategy-test);
  - внешний wall-clock дедлайн (поток-сторож), не доверяем таймаутам либы;
  - воркер-пины (193.233.112.68/.67) пропускаем: QUIC у воркера нет (SSLError);
  - DNS-спуф (NameResolutionError) -> фолбэк через cloudflare DoH + patch.

Запуск (нужен venv с niquests[h3], напр. %TEMP%\opencode\h3env):
    <venv>\Scripts\python.exe tools/quic_probe.py [host|url ...]
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time

try:
    import niquests
except ImportError:
    print("нет niquests — venv: python -m venv v; "
          "v\\Scripts\\pip install \"niquests[h3]\"")
    sys.exit(1)

DEFAULT = [
    "https://i.ytimg.com/generate_204",
    "https://www.youtube.com/",
    "https://redirector.googlevideo.com/generate_204",
    "https://storage.googleapis.com/",
    "https://www.cloudflare.com/",
]
VER = {11: "HTTP/1.1", 20: "HTTP/2", 30: "HTTP/3"}
WORKER_IPS = {"193.233.112.68", "193.233.112.67"}
WALL_DEADLINE = 15.0
FLAGS = subprocess.CREATE_NO_WINDOW


def urlspec(arg: str) -> str:
    if "://" in arg:
        return arg
    return f"https://{arg}" if "/" in arg else f"https://{arg}/"


def resolved_ips(host: str) -> set[str]:
    try:
        return {ai[4][0] for ai in socket.getaddrinfo(
            host, 443, socket.AF_INET, socket.SOCK_STREAM)}
    except Exception:  # noqa: BLE001
        return set()


def doh_ip(host: str) -> str | None:
    r = subprocess.run(
        ["curl.exe", "-4", "-sS", "-m", "10", "-H",
         "accept: application/dns-json",
         f"https://1.1.1.1/dns-query?name={host}&type=A"],
        capture_output=True, text=True, creationflags=FLAGS)
    try:
        j = json.loads(r.stdout)
        for a in j.get("Answer", []):
            if a.get("type") == 1:
                return a["data"]
    except Exception:  # noqa: BLE001
        pass
    return None


def install_doh_patch(host: str) -> bool:
    ip = doh_ip(host)
    if not ip:
        return False
    real = socket.getaddrinfo

    def patched(h, port, *a, **kw):
        if h == host:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
        return real(h, port, *a, **kw)

    socket.getaddrinfo = patched
    print(f"  [DoH] {host} -> {ip}")
    return True


def probe(url: str) -> None:
    host = url.split("//", 1)[1].split("/", 1)[0]
    print(f"\n{url}")
    ips = resolved_ips(host)
    if ips & WORKER_IPS:
        print("  SKIP: воркер-пин — QUIC у воркера нет")
        return

    box: dict = {}

    def worker() -> None:
        s = None
        try:
            s = niquests.Session(disable_http1=True, disable_http2=True)
            s.quic_cache_layer.add_domain(host)
            t0 = time.perf_counter()
            r = s.get(url, timeout=(4, 10), allow_redirects=False)
            box["r"] = (r.status_code, getattr(r, "http_version", None),
                        (time.perf_counter() - t0) * 1000)
        except Exception as e:  # noqa: BLE001
            box["e"] = f"{type(e).__name__}: {str(e)[:90]}"
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:  # noqa: BLE001
                    pass

    th = threading.Thread(target=worker, daemon=True)
    t0 = time.perf_counter()
    th.start()
    th.join(WALL_DEADLINE)
    wall = (time.perf_counter() - t0) * 1000
    if th.is_alive():
        print(f"  TIMEOUT: висит > {WALL_DEADLINE:.0f}с (внешний дедлайн)")
        return
    if "r" in box:
        code, raw, dur = box["r"]
        ver = VER.get(raw, raw)
        if raw == 30:
            print(f"  OK  H3: {code} {ver}  {dur:.0f}мс")
        else:
            print(f"  NOT-H3: {code} {ver} ({dur:.0f}мс) — QUIC не подтверждён")
    elif "e" in box:
        e = box["e"]
        if "NameResolution" in e:
            print(f"  ERR DNS: {e}")
            if install_doh_patch(host):
                print("  (DoH-патч поставлен — повтори запуск)")
        else:
            print(f"  FAIL: {e}")
    print(f"  wall {wall:.0f}мс")


def main() -> int:
    for arg in (sys.argv[1:] or DEFAULT):
        probe(urlspec(arg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
