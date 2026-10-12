r"""tls_ver_probe.py — пробы с прибитыми версиями TLS (идея из теста Flowseal).

Для каждого хоста — три варианта curl HEAD: default / TLS1.2-only / TLS1.3-only
(`--tlsv1.2 --tls-max 1.2`, `--tlsv1.3 --tls-max 1.3`).
Диагностика: если конкретная версия TLS «валится» (DPI или стек) — видно
раздельно. Вердикты: OK(code) / UNSUP / FAIL / TIMEOUT.

Запуск: python tools/tls_ver_probe.py <host|url> ...
"""
from __future__ import annotations

import subprocess
import sys
import time

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
FLAGS = subprocess.CREATE_NO_WINDOW
VARIANTS = [
    ("default", []),
    ("TLS1.2", ["--tlsv1.2", "--tls-max", "1.2"]),
    ("TLS1.3", ["--tlsv1.3", "--tls-max", "1.3"]),
]


def run(url: str, args: list[str], timeout: float = 8.0):
    cmd = ["curl.exe", "-4", "-sS", "-I", "-m", str(int(timeout)),
           "--connect-timeout", "3", "-o", "NUL",
           "-w", "%{http_code} %{time_total}",
           "-H", f"User-Agent: {UA}"] + args + [url]
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout + 4, creationflags=FLAGS)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", time.perf_counter() - t0, ""
    wall = time.perf_counter() - t0
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    parts = out.split()
    code = parts[0] if parts and parts[0].isdigit() else "NA"
    low = err.lower()
    if r.returncode == 35 or "not supported" in low or \
            "unsupported" in low or ("schannel" in low and not parts):
        return "UNSUP", wall, err[:70]
    if code == "000" or not parts:
        return ("TIMEOUT" if r.returncode == 28 else "FAIL"), wall, err[:70]
    return f"OK({code})", wall, err[:70]


def urlspec(arg: str) -> str:
    if "://" in arg:
        return arg
    return f"https://{arg}" if "/" in arg else f"https://{arg}/"


def main() -> int:
    urls = [urlspec(a) for a in sys.argv[1:]]
    if not urls:
        print("укажи хост: python tools/tls_ver_probe.py ya.ru ...")
        return 1
    for url in urls:
        print(f"\n{url}")
        res: dict[str, str] = {}
        for label, args in VARIANTS:
            verdict, wall, err = run(url, args)
            res[label] = verdict
            note = f"  [{err}]" if err and verdict.startswith(("FAIL", "UNSUP",
                                                               "TIMEOUT")) else ""
            print(f"  {label:8s} {verdict:10s} {wall * 1000:.0f}мс{note}")
        good = lambda v: v.startswith("OK")
        if good(res.get("TLS1.2", "")) and \
                res.get("TLS1.3", "").startswith(("FAIL", "TIMEOUT")):
            print("  -> подозрение: TLS1.3 валится (возможен DPI по версии TLS)")
        if good(res.get("TLS1.3", "")) and \
                res.get("TLS1.2", "").startswith(("FAIL", "TIMEOUT")):
            print("  -> подозрение: TLS1.2 валится (возможен DPI по версии TLS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
