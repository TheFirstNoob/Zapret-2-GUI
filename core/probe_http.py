"""probe_http.py - единственная curl-обёртка product-кода (аудит #6).

Простые «получить HTTP-код / тело» сайты (diagnostics, server) сведены сюда.
Тестерные пробы (tester.py) сохраняют свои контракты (HEAD-фолбэк,
upload-классификация), но при дальнейшем распиле (аудит #5) низ можно брать
и отсюда.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CurlResult:
    code: Optional[int]      # HTTP-код (None при сбое/таймауте)
    body: str                # stdout: "NNN" в code-режиме, тело в body_mode
    rc: int                  # код возврата curl (-1 при таймауте/OSError)
    elapsed_ms: float
    stderr: str


def curl_result(url: str, *, timeout: float = 6.0, wall_pad: float = 3.0,
                headers: Optional[dict] = None, method: str = "GET",
                data_file: Optional[str] = None, extra_args: tuple = (),
                body_mode: bool = False, encoding: str = "oem",
                connect_timeout: Optional[float] = None) -> CurlResult:
    """curl.exe → CurlResult. Единые механические детали: -4 -s, -m, NUL/%code,
    локале-безопасная кодировка, wall-clock timeout = timeout + wall_pad."""
    args = ["curl.exe", "-4", "-s"]
    if method == "HEAD":
        args.append("-I")   # правильно только через -I (не -X HEAD)
    elif method != "GET":
        args += ["-X", method]
    if connect_timeout is not None:
        args += ["--connect-timeout", str(connect_timeout)]
    args += ["-m", str(timeout)]
    if not body_mode:
        args += ["-o", "NUL", "-w", "%{http_code}"]
    for k, v in (headers or {}).items():
        args += ["-H", f"{k}: {v}"]
    if data_file is not None:
        args += ["--data-binary", f"@{data_file}"]
    args += list(extra_args)
    args.append(url)
    t0 = time.time()
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding=encoding,
                           errors="replace", timeout=timeout + wall_pad,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    except (subprocess.TimeoutExpired, OSError) as e:
        return CurlResult(None, "", -1, (time.time() - t0) * 1000, str(e)[:200])
    out = (r.stdout or "").strip()
    code = int(out) if out.isdigit() else None
    return CurlResult(code, out, r.returncode, (time.time() - t0) * 1000,
                      (r.stderr or "").strip()[:200])


def curl_code(url: str, **kw) -> Optional[int]:
    """HTTP-код (None при сбое) - тонкая обёртка над curl_result."""
    return curl_result(url, **kw).code
