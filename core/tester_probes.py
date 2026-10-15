"""tester_probes.py - сетевые пробы тестера (аудит #5).

ping / curl / QUIC-H3 / TCP16-20 / TTL-проба и батарея по доменам. Функции
без состояния (timeout передаётся явно); внутренних пер-хостовых ретраев нет -
флак фиксируется как есть, спорные домены перепроверяет общий речек (§29).
"""
from __future__ import annotations

import gzip
import ipaddress
import os
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from core.tester_defs import (BROWSER_HEADERS, H3_WALL_DEADLINE, HOST_TEST,
                              QUIC_QUIRK_DOMAINS, TCP1620_BODY, TestResult)


def ipset_networks(root_dir: Path) -> list:
    """CIDR-сети из ipset-all.txt.gz - для проверки «IP кандидата уже
    десинкается ipset-режимом» (нет наложений)."""
    nets: list = []
    try:
        with gzip.open(root_dir / "lists" / "ipset-all.txt.gz", "rt",
                       encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    nets.append(ipaddress.ip_network(line, strict=False))
                except ValueError:
                    continue
    except OSError:
        pass
    return nets


def resolve_ips(domain: str, timeout: float = 2.0) -> list[str]:
    """A-записи домена (для ipset-включений: winws2 --ipset принимает IP)."""
    try:
        return sorted({addr[4][0] for addr in
                       socket.getaddrinfo(domain, None, socket.AF_INET,
                                          socket.SOCK_STREAM)
                       if addr[4]})
    except OSError:
        return []


def safe_prefixes(ips: list[str], protection: set[str], max_prefix: int = 24) -> list[str]:
    """Для каждого IP - НАИБОЛЬШИЙ чистый префикс, не пересекающийся с
    защищёнными адресами: /max_prefix (натуральная аллокация, переживает
    ротацию) или /32 (Anycast - общие адреса тысяч доменов). «ip/prefix»."""
    out: list[str] = []
    prot_objs: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for p in protection:
        try:
            prot_objs.add(ipaddress.ip_address(p))
        except ValueError:
            continue
    for s in ips:
        try:
            ip = ipaddress.ip_address(s)
        except ValueError:
            continue
        # Только /max_prefix (натуральная аллокация CDN) или /32 (голый
        # IP): промежуточные /25-/31 дают границы, чуждые реальным
        # аллокациям провайдеров.
        for plen in (max_prefix, 32):
            net = ipaddress.ip_network(f"{ip}/{plen}", strict=False)
            if any(p in net for p in prot_objs):
                continue
            net_s = str(net)
            if net_s not in out:
                out.append(net_s)
            break
    return out


def ping_test(domain: str, timeout: float) -> TestResult:
    start = time.time()
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout * 1000), domain],
            capture_output=True, text=True, encoding="oem", errors="replace", timeout=timeout + 2,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        elapsed = (time.time() - start) * 1000
        if result.returncode == 0:
            return TestResult(domain, "ping", "OK", time_ms=elapsed)
        return TestResult(domain, "ping", "FAIL", time_ms=elapsed, error="Ping failed")
    except (subprocess.TimeoutExpired, OSError) as e:
        elapsed = (time.time() - start) * 1000
        return TestResult(domain, "ping", "ERROR", time_ms=elapsed, error=str(e))


# ── curl-тесты (как в zapret_test_final.py - проверено, работает) ──


def curl_attempt(url: str, head: bool, timeout: float) -> tuple[Optional[int], int, float, str]:
    """Один curl к url: (http_code | None, returncode, elapsed_ms, stderr).

    head=True - HEAD (-I), иначе полный GET; timeout - curl -m, а
    --connect-timeout всегда 2с. TimeoutExpired/OSError - наружу (ловит curl_test)."""
    t0 = time.time()
    args = ["curl.exe", "-4", "-s", "-m", str(int(timeout)),
            "--connect-timeout", "2", "--show-error"]
    if head:
        args.insert(2, "-I")
    args += BROWSER_HEADERS + ["-o", "NUL", "-w", "%{http_code}", url]
    r = subprocess.run(
        args, capture_output=True, text=True, encoding="oem", errors="replace",
        timeout=timeout + 5, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    s = r.stdout.strip()
    code = int(s) if s.isdigit() else None
    return code, r.returncode, (time.time() - t0) * 1000, (r.stderr or "")[:80]


# Кэш наличия niquests+qh3 (опциональный бандл сборки): False - фолбэк на
# прежнюю эвристику QUIC (см. quic_h3_probe).
_HAS_NIQUESTS: Optional[bool] = None


def quic_h3_probe(domain: str) -> tuple[bool, str]:
    """Настоящая QUIC/HTTP3-проба (niquests+qh3) - контракт точности:
    forced-H3 (disable_http1/2 + preemptive quic_cache_layer, без TCP),
    свежая сессия (strategy-test), внешний wall-clock дедлайн (поток-сторож).
    Возвращает (ok, detail). Без niquests - (False, "нет niquests")."""
    global _HAS_NIQUESTS
    if _HAS_NIQUESTS is None:
        try:
            import niquests  # noqa: F401
            _HAS_NIQUESTS = True
        except ImportError:
            _HAS_NIQUESTS = False
    if not _HAS_NIQUESTS:
        return False, "нет niquests"
    import niquests

    box: dict = {}

    def worker() -> None:
        s = None
        try:
            s = niquests.Session(disable_http1=True, disable_http2=True)
            # Контракт: env/системные прокси не подхватываем (ревью 13.10,
            # P2-1) - иначе проба уходит через прокси и умирает (H3_NONE).
            s.trust_env = False
            s.quic_cache_layer.add_domain(domain)
            r = s.get(f"https://{domain}/", timeout=(4, 8),
                      allow_redirects=False)
            box["ver"] = getattr(r, "http_version", None)
            box["code"] = r.status_code
        except Exception as e:  # noqa: BLE001
            box["err"] = type(e).__name__
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:  # noqa: BLE001
                    pass

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(H3_WALL_DEADLINE)
    if th.is_alive():
        return False, "H3 висит (дедлайн)"
    if box.get("ver") == 30:
        return True, f"H3 {box.get('code')}"
    if "err" in box:
        return False, f"QUIC {box['err']}"
    return False, "H3 не подтверждён"


def curl_test(domain: str, test_type: str, timeout: float, path: str = "/") -> TestResult:
    start = time.time()
    url = f"https://{domain}{path}"
    timeout = float(min(int(timeout), 6))
    if domain in QUIC_QUIRK_DOMAINS:
        # QUIC-класс: 000 для стороннего TLS-клиента неизбежен, статус
        # всё равно QUIC - не ждём полные 6с
        timeout = 3.0
    try:
        # HEAD быстрый, но не все серверы отвечают (#14: ложные 403/418) -
        # при «000» GET-фолбэк. Пер-хостовых ретраев НЕТ: флак фиксируется
        # как есть, спорные домены перепроверяет ОДИН общий речек (§29).
        code, _, _, _ = curl_attempt(url, head=True, timeout=timeout)
        if code is not None and code >= 100:
            return TestResult(domain, test_type, "OK", code, (time.time() - start) * 1000)

        code, rc, _, stderr = curl_attempt(url, head=False, timeout=timeout)
        elapsed = (time.time() - start) * 1000
        if code is not None and code >= 100:
            return TestResult(domain, test_type, "OK", code, elapsed)
        if code is not None:
            # GET вернул «000» - нет HTTP-ответа.
            if domain in QUIC_QUIRK_DOMAINS:
                # QUIC-класс: TCP-проба под десинком не показательная
                # (браузер ходит через QUIC). 12.10: реальная H3-проба
                # вместо эвристики; без niquests - прежний нейтральный QUIC.
                h3_ok, detail = quic_h3_probe(domain)
                # Полное время с пробой (ревью 13.10, P3-1): раньше в чипе
                # висело время провального TCP-этапа.
                elapsed = (time.time() - start) * 1000
                if h3_ok:
                    return TestResult(domain, test_type, "QUIC", code,
                                      elapsed, f"H3 подтверждён ({detail})")
                if detail.startswith("нет niquests"):
                    return TestResult(domain, test_type, "QUIC", code,
                                      elapsed, detail)
                # Проба выполнена, но H3 не подтверждён: НЕ приравниваем к
                # BLOCKED (ошибка инструмента/таймаут != доказательство
                # блокировки; ревью 12.10). Статус нейтрален и не входит
                # в ok/fail-статистику (_build_result).
                return TestResult(domain, test_type, "H3_NONE", code,
                                  elapsed, f"H3 не подтверждён: {detail}")
            return TestResult(domain, test_type, "BLOCKED", code, elapsed)
        if test_type == "tls:443" and rc == 0:
            return TestResult(domain, test_type, "OK", time_ms=elapsed)
        err = stderr or f"rc={rc}"
        return TestResult(domain, test_type, "ERROR", 0, elapsed, err)
    except subprocess.TimeoutExpired:
        elapsed = (time.time() - start) * 1000
        return TestResult(domain, test_type, "TIMEOUT", 0, elapsed, "timeout")
    except OSError as e:
        elapsed = (time.time() - start) * 1000
        return TestResult(domain, test_type, "ERROR", 0, elapsed, f"curl not found: {e}")


def expand_with_www(domains: list[str]) -> list[str]:
    """Расширяет список www-вариантами (плоский, без дублей). Поддомены
    (redirector./gateway./cdn./cdnjs./i./updates.) и youtu.be - без www;
    указанные с www. тестируются только как www (non-www часто редиректит)."""
    CDN_PREFIXES = ("redirector.", "gateway.", "cdn.", "cdnjs.", "i.", "updates.")
    NO_WWW = {"youtu.be"}
    expanded: list[str] = []
    seen: set[str] = set()
    for d in domains:
        base = d[4:] if d.startswith("www.") else d
        # CDN-поддомены, NO_WWW и любые 3+ level-поддомены
        # (web.telegram.org, api.push.apple.com) www-варианта не имеют.
        if base in NO_WWW or base.startswith(CDN_PREFIXES) or base.count(".") >= 2:
            if base not in seen:
                expanded.append(base)
                seen.add(base)
            continue
        if d.startswith("www."):
            # домен указан с www - тестируем только www-вариант
            if d not in seen:
                expanded.append(d)
                seen.add(d)
            continue
        for variant in (base, f"www.{base}"):
            if variant not in seen:
                expanded.append(variant)
                seen.add(variant)
    return expanded


def host_test_type(domain: str) -> str:
    """Тип теста для домена; если www-варианта нет в HOST_TEST - по базовому."""
    t = HOST_TEST.get(domain)
    if t:
        return t
    base = domain[4:] if domain.startswith("www.") else domain
    return HOST_TEST.get(base, "http")


def run_domain_tests(domains: list[str], concurrency: int = 5, http_only: bool = False,
                     result_cb=None, expand_www: bool = False, progress_cb=None,
                     timeout: float = 8.0) -> list[TestResult]:
    if expand_www:
        test_items = expand_with_www(domains)
    else:
        test_items = list(domains)
    total = len(test_items)
    done = 0
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {}
        for d in test_items:
            if http_only:
                futures[pool.submit(curl_test, d, "http", timeout, path="/")] = d
            else:
                ttype = host_test_type(d)
                label = "tls:443" if ttype == "tls" else "https"
                futures[pool.submit(curl_test, d, label, timeout)] = d
        for fut in as_completed(futures):
            d = futures[fut]
            r = fut.result()
            results.append(r)
            done += 1
            if progress_cb:
                progress_cb(done, total)
            if result_cb:
                result_cb(r)
    return results


def tcp1620_test_curl(domain: str, body_file: Path, timeout: float) -> TestResult:
    """TCP 16-20 через curl: POST 64 КБ, детект обрыва stateful DPI.

    Классификация по size_upload, а не только по http-коду: сигнатура
    «обрыв на N КБ» (как в dpi-detector, окно 12-36 КБ)."""
    start = time.time()
    try:
        r = subprocess.run(
            ["curl.exe", "-4", "--no-sessionid", "--no-keepalive",
             "-s", "-m", str(min(int(timeout), 6)),
             "-w", "%{http_code} %{size_upload}", "-o", "NUL",
             "--data-binary", f"@{body_file}",
             f"https://{domain}/"],
            capture_output=True, text=True, encoding="oem", errors="replace", timeout=timeout + 5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        elapsed = (time.time() - start) * 1000
        parts = r.stdout.strip().split()
        code = int(parts[0]) if parts and parts[0].isdigit() else 0
        uploaded = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        if code >= 200 and code < 500:
            # Сервер ответил - загрузка 64 КБ пережила поток: обрыва нет.
            return TestResult(domain, "tcp1620", "OK", code, elapsed)
        if uploaded >= TCP1620_BODY:
            # Полный объём ушёл, ответа нет (сервер молчит/таймаут) -
            # поток НЕ резан: это не сигнатура stateful DPI.
            return TestResult(domain, "tcp1620", "OK", 0, elapsed,
                              "upload OK, ответа нет")
        if uploaded > 0:
            # Поток обрезан на N КБ - сигнатура stateful DPI (dpich Detected).
            return TestResult(domain, "tcp1620", "TCP16_20", 0, elapsed,
                              f"обрыв на {uploaded // 1024} КБ - stateful DPI")
        # uploaded == 0: соединение умерло до/в начале загрузки - фаза.
        err = (r.stderr or "").lower()
        if "reset by peer" in err or "recv failure" in err:
            return TestResult(domain, "tcp1620", "BLOCKED", 0, elapsed, "TCP RST")
        if "connection timed out" in err:
            return TestResult(domain, "tcp1620", "BLOCKED", 0, elapsed, "SYN DROP")
        if "ssl" in err and ("handshake" in err or "alert" in err):
            return TestResult(domain, "tcp1620", "BLOCKED", 0, elapsed, "TLS RST")
        if "timed out" in err:
            return TestResult(domain, "tcp1620", "BLOCKED", 0, elapsed, "TIMEOUT")
        return TestResult(domain, "tcp1620", "BLOCKED", 0, elapsed,
                          (err.strip()[:60] or f"код {r.returncode}"))
    except subprocess.TimeoutExpired:
        elapsed = (time.time() - start) * 1000
        return TestResult(domain, "tcp1620", "TIMEOUT", 0, elapsed, "POST timeout")
    except OSError as e:
        elapsed = (time.time() - start) * 1000
        return TestResult(domain, "tcp1620", "ERROR", 0, elapsed, f"curl: {e}")


def run_tcp1620_tests(root_dir: Path, domains: list[str], concurrency: int = 5,
                      timeout: float = 8.0) -> list[TestResult]:
    """TCP 16-20: curl POST с 64 КБ случайного тела."""
    results = []
    body_file = root_dir / "tcp1620_test_body.bin"
    try:
        body_file.write_bytes(os.urandom(TCP1620_BODY))
    except OSError:
        return [TestResult(d, "tcp1620", "ERROR", error="Cannot create test body") for d in domains]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {}
        for d in domains:
            futures[pool.submit(tcp1620_test_curl, d, body_file, timeout)] = d
        for fut in as_completed(futures):
            results.append(fut.result())
    try:
        body_file.unlink()
    except OSError:
        pass
    return results


# ── TTL-проба ──────────────────────────────────────────────────────
# Traceroute до первого хопа вне локальной сети - вероятный DPI-бокс
# провайдера; результат в ProfileTestResult для autottl-оптимизации.


def is_private_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def probe_provider_ttl() -> dict:
    """tracert до google.com: первый не-приватный хоп (hop, ip, target).
    hop=0 при неудаче; кэш - на стороне вызывающего (см. тестер)."""

    # 5 хопов / 900 мс на пробу - достаточно, чтобы увидеть DPI-бокс
    # провайдера (обычно хоп 1-4); худший случай ~14с вместо 25с+.
    tracert_targets = ["google.com", "discord.com", "github.com"]
    for target in tracert_targets:
        try:
            r = subprocess.run(
                ["tracert", "-d", "-h", "5", "-w", "900", target],
                capture_output=True, text=True, encoding="oem", errors="replace", timeout=14,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            output = r.stdout
            if not output:
                continue
            lines = output.splitlines()
            for line in lines:
                line = line.strip()
                # Формат: " 3    12 ms    15 ms    10 ms  213.180.36.1"
                m = re.match(r'\s*(\d+)\s+<\d+', line)
                if not m:
                    m = re.match(r'\s*(\d+)\s+\d+', line)
                if not m:
                    continue
                hop = int(m.group(1))
                # IP в конце строки
                ip_match = re.findall(r'(\d+\.\d+\.\d+\.\d+)', line)
                if not ip_match:
                    continue
                ip = ip_match[-1]
                if not is_private_ip(ip):
                    return {"hop": hop, "ip": ip, "target": target}
                # все хопы приватные - отдаём последний
                if hop >= 5:
                    return {"hop": hop, "ip": ip, "target": target}
        except (subprocess.TimeoutExpired, OSError):
            continue

    # Ни один target не дал результата - идём без TTL
    return {"hop": 0, "ip": "", "target": ""}
