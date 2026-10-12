r"""upload_probe.py — upload-проба с байтовым учётом (детект «ТСПУ-ямы»).

POST N байт случайных данных; смотрим
%{http_code} %{size_upload} %{size_download} %{time_total}.
Вердикты:
  OK (HTTP xxx)  — HTTP-ответ получен;
  LIKELY_BLOCKED — загрузка ушла (>0), ответа ноль (=0), время на пределе
                   таймаута: классическая «яма» ТСПУ (тот же класс, что голосовой
                   OUT-идёт/IN=0);
  UNSUPPORTED    — стек/curl не поддерживает (exit 35 и пр.);
  FAIL/TIMEOUT   — ошибка соединения/DNS, нет ответа без признаков «ямы».

Идея — из теста Flowseal (`utils/test zapret.ps1`: POST 64КБ + счётчики байтов).

Запуск: python tools/upload_probe.py [--size N] [--timeout S] <url> ...
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
FLAGS = subprocess.CREATE_NO_WINDOW


def probe(url: str, size: int, timeout: float) -> None:
    fd, path = tempfile.mkstemp(prefix="upl_", suffix=".bin")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(os.urandom(size))
        cmd = ["curl.exe", "-4", "-sS", "-m", str(int(timeout)),
               "--connect-timeout", "3", "-X", "POST",
               "--data-binary", f"@{path}", "-o", "NUL",
               "-w", "%{http_code} %{size_upload} %{size_download} "
                     "%{time_total}",
               "-H", f"User-Agent: {UA}", url]
        t0 = time.perf_counter()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout + 6, creationflags=FLAGS)
        except subprocess.TimeoutExpired:
            print(f"{url}\n  FAIL: curl завис (wall>{timeout + 6:.0f}с)")
            return
        wall = (time.perf_counter() - t0) * 1000
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        parts = out.split()
        code, up, down, total = "NA", 0, 0, -1.0
        if len(parts) >= 4:
            code = parts[0]
            up, down = int(parts[1]), int(parts[2])
            try:
                total = float(parts[3])
            except ValueError:
                pass
        low = err.lower()
        if not parts:
            verdict = "UNSUPPORTED" if (r.returncode == 35 or
                                        "not supported" in low or
                                        "unsupported" in low) \
                else f"FAIL ({err[:60] or 'rc=' + str(r.returncode)})"
        elif code == "000":
            if up > 0 and down == 0 and total >= timeout * 0.85:
                verdict = "LIKELY_BLOCKED (ушло, ответа 0, время на пределе)"
            else:
                verdict = (f"FAIL/TIMEOUT (rc={r.returncode}, "
                           f"up={up}, down={down})")
        elif code.isdigit():
            verdict = f"OK (HTTP {code})"
        else:
            verdict = f"FAIL ({err[:60]})"
        print(f"{url}\n  {verdict}  | up={up / 1024:.1f}КБ "
              f"down={down / 1024:.1f}КБ t={total:.2f}s "
              f"rc={r.returncode} wall={wall:.0f}мс")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def urlspec(arg: str) -> str:
    if "://" in arg:
        return arg
    return f"https://{arg}" if "/" in arg else f"https://{arg}/"


def main() -> int:
    ap = argparse.ArgumentParser(description="upload-проба (LIKELY_BLOCKED)")
    ap.add_argument("--size", type=int, default=65536)
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("urls", nargs="+")
    a = ap.parse_args()
    for u in a.urls:
        probe(urlspec(u), a.size, a.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
