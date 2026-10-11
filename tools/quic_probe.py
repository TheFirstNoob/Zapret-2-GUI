"""QUIC-проба (dev): HTTP/2 -> HTTP/3 (QUIC) до хостов под живым обходом.

Зачем: curl не умеет QUIC, поэтому квирк-хосты (YouTube-класс) в тестере
получают нейтральный «≈ QUIC». Этот инструмент ходит настоящим H3-клиентом
(niquests + qh3) и показывает: (а) работает ли QUIC-путь под нашим обходом,
(б) не ломает ли его QUIC-фейк; (в) на спуфленом DNS - резолвит через DoH.

Запуск: python tools/quic_probe.py [host ...]
Требуется: niquests[h3] (venv: python -m venv X; X\\Scripts\\pip install "niquests[h3]")
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time

try:
    import niquests
except ImportError:
    print("нет niquests — поставь: pip install \"niquests[h3]\"")
    sys.exit(1)

DEFAULT = [
    "https://www.youtube.com/",
    "https://i.ytimg.com/generate_204",
    "https://redirector.googlevideo.com/generate_204",
    "https://storage.googleapis.com/",
    "https://www.google.com/generate_204",
    "https://www.cloudflare.com/",
]
VER = {11: "HTTP/1.1", 20: "HTTP/2", 30: "HTTP/3",
       "11": "HTTP/1.1", "20": "HTTP/2", "30": "HTTP/3"}


def doh_ip(host: str) -> str | None:
    r = subprocess.run(
        ["curl.exe", "-4", "-sS", "-m", "10", "-H",
         "accept: application/dns-json",
         f"https://1.1.1.1/dns-query?name={host}&type=A"],
        capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
        for a in j.get("Answer", []):
            if a.get("type") == 1:
                return a["data"]
    except Exception:
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
    for attempt in (1, 2):
        t0 = time.time()
        try:
            r = niquests.get(url, timeout=12, allow_redirects=False)
            raw = getattr(r, "http_version", None)
            print(f"  try{attempt}: {r.status_code}  {VER.get(raw, raw)}  "
                  f"{time.time() - t0:.2f}s")
        except Exception as e:  # noqa: BLE001
            if "NameResolution" in type(e).__name__ or \
                    "NameResolution" in str(e) or \
                    "NameResolution" in repr(e.__cause__ or ""):
                print(f"  try{attempt}: DNS спуфлен (NameResolutionError)")
                if install_doh_patch(host):
                    continue
            print(f"  try{attempt}: ERR {type(e).__name__}: "
                  f"{str(e)[:100]}")
            return


def main() -> int:
    urls = sys.argv[1:] or DEFAULT
    for url in urls:
        print(url)
        probe(url if "://" in url else f"https://{url}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
