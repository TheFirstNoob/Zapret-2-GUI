r"""tls_ver_probe.py — пробы с прибитыми версиями TLS (идея из теста Flowseal).

Для каждого хоста — три варианта curl HEAD: default / TLS1.2-only / TLS1.3-only
(`--tlsv1.2 --tls-max 1.2`, `--tlsv1.3 --tls-max 1.3`).
Диагностика: если конкретная версия TLS «валится» (DPI или стек) — видно
раздельно. Вердикты: OK(code) / UNSUP / FAIL / TIMEOUT.

Запуск: python tools/tls_ver_probe.py [--repeat N] <host|url> ...
  --repeat N — повторы (пауза 0.5с): детект флапа блокировки по версии TLS.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections import Counter

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
FLAGS = subprocess.CREATE_NO_WINDOW
VARIANTS = [
    ("default", []),
    ("TLS1.2", ["--tlsv1.2", "--tls-max", "1.2"]),
    ("TLS1.3", ["--tlsv1.3", "--tls-max", "1.3"]),
]


def urlspec(arg: str) -> str:
    if "://" in arg:
        return arg
    return f"https://{arg}" if "/" in arg else f"https://{arg}/"


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
    # UNSUP - только явная «неподдерживаемость» (SEC_E_UNSUPPORTED_*,
    # «not supported»); обычный RST/обрыв рукопожатия тоже даёт rc=35 и НЕ
    # должен маскироваться под UNSUP (внешнее ревью 13.10, P2-4).
    unsup = ("sec_e_unsupported_function" in low
             or "sec_e_algorithm_mismatch" in low
             or "not supported" in low
             or "unsupported" in low
             or "unrecognized option" in low)
    if r.returncode == 35 and not unsup:
        return "FAIL", wall, err[:70]
    if unsup:
        return "UNSUP", wall, err[:70]
    if code == "000" or not parts:
        return ("TIMEOUT" if r.returncode == 28 else "FAIL"), wall, err[:70]
    return f"OK({code})", wall, err[:70]


def all_bad(vs: list[str]) -> bool:
    return all(v.startswith(("FAIL", "TIMEOUT")) for v in vs)


def any_ok(vs: list[str]) -> bool:
    return any(v.startswith("OK") for v in vs)


def main() -> int:
    ap = argparse.ArgumentParser(description="pinned-TLS пробы (1.2 / 1.3)")
    ap.add_argument("--repeat", type=int, default=1,
                    help="число повторов (пауза 0.5с) — детект флапа")
    ap.add_argument("targets", nargs="*")
    a = ap.parse_args()
    urls = [urlspec(t) for t in a.targets]
    if not urls:
        print("укажи хост: python tools/tls_ver_probe.py [--repeat N] ya.ru ...")
        return 1
    for url in urls:
        print(f"\n{url}")
        res: dict[str, list[str]] = {}
        for label, args in VARIANTS:
            verdicts: list[str] = []
            for i in range(max(1, a.repeat)):
                if i:
                    time.sleep(0.5)
                verdict, wall, err = run(url, args)
                verdicts.append(verdict)
                if a.repeat == 1:
                    note = f"  [{err}]" if err and verdict.startswith(
                        ("FAIL", "UNSUP", "TIMEOUT")) else ""
                    print(f"  {label:8s} {verdict:10s} {wall * 1000:.0f}мс{note}")
            if a.repeat > 1:
                cnt = Counter(v.split("(")[0] for v in verdicts)
                summ = ", ".join(f"{k} x{v}" for k, v in cnt.items())
                print(f"  {label:8s} {summ}")
            res[label] = verdicts
        if any_ok(res["TLS1.2"]) and all_bad(res["TLS1.3"]):
            print("  -> подозрение: TLS1.3 валится (возможен DPI по версии TLS)")
        if any_ok(res["TLS1.3"]) and all_bad(res["TLS1.2"]):
            print("  -> подозрение: TLS1.2 валится (возможен DPI по версии TLS)")
        if all_bad(res["TLS1.2"]) and all_bad(res["TLS1.3"]):
            print("  (все версии TLS недоступны: TCP-блок, не-TLS сервер или FAIL)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
