"""tester_probes.py - сетевые пробы тестера (аудит #5).

ping / curl / QUIC-H3 / TCP16-20 / TTL-проба и батарея по доменам. Функции
без состояния (timeout передаётся явно); внутренних пер-хостовых ретраев нет -
флак фиксируется как есть, спорные домены перепроверяет общий речек (§29).
"""
from __future__ import annotations

import gzip
import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from core import timeouts
from core.probe_h3 import probe_h3
_TCP1620_MIN_KB = 12  # порог dpi-detector: меньше 12 КБ - не DPI-сигнатура

from core.tester_defs import (BROWSER_HEADERS, H3_LIB_TIMEOUT,
                              H3_WALL_DEADLINE, HOST_TEST, QUIC_QUIRK_DOMAINS,
                              TCP1620_BODY, TCP1620_RATE_MARGIN,
                              TCP1620_RATE_PROBE_BODY, TCP1620_TIMEOUT_CAP,
                              TCP1620_TIMEOUT_FALLBACK, TCP1620_TIMEOUT_MIN,
                              TestResult)


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


# ── Локальный каталог проб (T20 / аудит B7) ──────────────────────
# probe-файлы НЕ пишем в живые lists/ и presets/ (уезжали в релиз,
# диагностический ZIP, backup апдейтера; ipset-probe.txt содержал IP
# пользователя) и НЕ пишем в temp (провоцирует AV, исторически ломалось).
# Каталог runtime/probe в корне приложения: build.py/build_portable/
# build_lite его не копируют, collector/updater читают только lists/presets.
PROBE_DIR_NAME = "runtime"


def probe_dir(root_dir: Path) -> Path:
    """Каталог проб в корне приложения (создаётся при первом обращении)."""
    d = Path(root_dir) / PROBE_DIR_NAME / "probe"
    d.mkdir(parents=True, exist_ok=True)
    return d


def probe_file(root_dir: Path, prefix: str, suffix: str = ".txt") -> Path:
    """Уникальный путь пробы: pid+случайный токен - два экземпляра GUI и
    параллельные сканы не перетирают/не удаляют файлы друг друга."""
    name = f"{prefix}-{os.getpid()}-{os.urandom(4).hex()}{suffix}"
    return probe_dir(root_dir) / name


# Legacy-имена прошлых версий: писались прямо в живые каталоги. Чистим при
# любом прогоне (мусор от kill/питания), это НЕ релизные файлы.
_LEGACY_PROBE_FILES = (
    ("lists", "list-probe.txt"),
    ("lists", "ipset-probe.txt"),
    ("presets", "_probe_cdn.txt"),
)


def cleanup_stale_probe_files(root_dir: Path, max_age: float = 1800.0) -> list[str]:
    """Удаляет старые probe-файлы (прошлых упавших прогонов) и legacy-мусор.

    max_age защищает файлы ЖИВОГО параллельного прогона: уникальные имена с
    pid/токеном не пересекаются, а молодые файлы не трогаем. Возвращает
    список удалённых имён (для лога/тестов)."""
    removed: list[str] = []
    root = Path(root_dir)
    stale = root / PROBE_DIR_NAME / "probe"
    try:
        now = time.time()
        if stale.is_dir():
            for p in list(stale.iterdir()):
                try:
                    if p.is_file() and now - p.stat().st_mtime > max_age:
                        p.unlink()
                        removed.append(p.name)
                except OSError:
                    continue
    except OSError:
        pass
    for sub, name in _LEGACY_PROBE_FILES:
        p = root / sub / name
        try:
            if p.is_file():
                p.unlink()
                removed.append(f"{sub}/{name}")
        except OSError:
            pass
    return removed


_RESOLVE_LOCK = threading.Lock()
_RESOLVE_CACHE: dict[str, tuple[float, list[str]]] = {}
_RESOLVE_INFLIGHT: dict[str, float] = {}
_RESOLVE_OK_TTL = 300.0
_RESOLVE_FAIL_TTL = 30.0
_RESOLVE_INFLIGHT_TTL = 60.0
_RESOLVE_MAX_INFLIGHT = 16


def resolve_ips(domain: str, timeout: float = 2.0) -> list[str]:
    """A-записи домена (для ipset-включений: winws2 --ipset принимает IP).

    timeout реально ограничивает ожидание: socket.getaddrinfo блокирующий,
    поэтому резолв идёт в демон-потоке. Кэш и in-flight guard не дают серии
    одинаковых/зависших запросов плодить безлимитные daemon-потоки.
    """
    key = (domain or "").strip().lower().rstrip(".")
    if not key:
        return []
    now = time.monotonic()
    with _RESOLVE_LOCK:
        cached = _RESOLVE_CACHE.get(key)
        if cached:
            ttl = _RESOLVE_OK_TTL if cached[1] else _RESOLVE_FAIL_TTL
            if now - cached[0] < ttl:
                return list(cached[1])
        started = _RESOLVE_INFLIGHT.get(key)
        if started is not None and now - started < _RESOLVE_INFLIGHT_TTL:
            return []
        if len(_RESOLVE_INFLIGHT) >= _RESOLVE_MAX_INFLIGHT:
            return []
        _RESOLVE_INFLIGHT[key] = now
    box: dict = {}

    def _worker() -> None:
        try:
            box["ips"] = sorted({addr[4][0] for addr in
                                 socket.getaddrinfo(key, None,
                                                    socket.AF_INET,
                                                    socket.SOCK_STREAM)
                                 if addr[4]})
        except OSError:
            box["ips"] = []
        ips = list(box.get("ips") or [])
        with _RESOLVE_LOCK:
            _RESOLVE_CACHE[key] = (time.monotonic(), ips)
            _RESOLVE_INFLIGHT.pop(key, None)

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(max(0.1, float(timeout)))
    return list(box.get("ips", []))


def _is_dns_error(rc: int, stderr: str) -> bool:
    """curl-ошибка РЕЗОЛВА ХОСТА (rc=6 / «could not resolve host»): резолвер
    не отдал адрес (спуф/сбой), а не блокировка сети. Ошибки прокси
    (rc=5 / «could not resolve proxy») сюда НЕ попадают (ревью 18.10)."""
    return rc == 6 or "could not resolve host" in (stderr or "").lower()


def _doh_ipv4s(payload: str) -> list[str]:
    """IPv4 из JSON-ответа dns.google (Answer[].data, type==1)."""
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return []
    out = []
    for a in data.get("Answer") or []:
        if a.get("type") == 1:
            ip = str(a.get("data", "")).strip()
            if ip:
                out.append(ip)
    return sorted(set(out))


def doh_resolve_ips(domain: str, timeout: float | None = None) -> list[str]:
    """A-записи домена через DoH (dns.google). ТОЛЬКО фолбэк, когда штатный
    резолвер не отдал адрес (кейс 12.10: www.youtube.com «мёртв» у всех
    клиентов из-за спуфа системного DNS, под DoH - жив). Пусто при любой
    ошибке - вызывающий продолжает штатным путём."""
    t = timeouts.DOH if timeout is None else float(timeout)
    url = "https://dns.google/resolve?name=%s&type=A" % quote(domain)
    try:
        r = subprocess.run(
            ["curl.exe", "-4", "-s", "-m", str(int(t)),
             "--connect-timeout", str(timeouts.CONNECT),
             "--noproxy", "*", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=t + timeouts.WALL_PAD, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return _doh_ipv4s(r.stdout or "")
    except (subprocess.TimeoutExpired, OSError):
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


def curl_attempt(url: str, head: bool, timeout: float,
                 resolve: Optional[str] = None) -> tuple[Optional[int], int, float, str]:
    """Один curl к url: (http_code | None, returncode, elapsed_ms, stderr).

    head=True - HEAD (-I), иначе полный GET; timeout - curl -m, а
    --connect-timeout всегда 2с. resolve ("host:443:ip") принудительно
    задаёт адрес в обход системного DNS (DoH-фолбэк при спуфе).
    TimeoutExpired/OSError - наружу (ловит curl_test)."""
    t0 = time.time()
    args = ["curl.exe", "-4", "-s", "-m", str(int(timeout)),
            "--connect-timeout", str(timeouts.CONNECT), "--show-error",
            "--noproxy", "*"]
    if head:
        args.insert(2, "-I")
    if resolve:
        args += ["--resolve", resolve]
    args += BROWSER_HEADERS + ["-o", "NUL", "-w", "%{http_code}", url]
    r = subprocess.run(
        args, capture_output=True, text=True, encoding="oem", errors="replace",
        timeout=timeout + timeouts.WALL_PAD, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    s = r.stdout.strip()
    code = int(s) if s.isdigit() else None
    return code, r.returncode, (time.time() - t0) * 1000, (r.stderr or "")[:80]


_H3_SKIP_DETAIL = "H3 не проверялся (бюджет батареи)"


class H3ProbeState:
    """Бюджет H3 на ОДНУ батарею доменов (T20 / аудит B9).

    После первого дедлайна остальные QUIC-хосты батареи не пробуем: на чёрной
    QUIC-сети 5 хостов × 6 с = до +30 с к профилю. Статус при этом -
    нейтральный H3_NONE («H3 не проверялся»), не красный и не OK; в финальном
    отчёте есть счётчик h3_skipped. Состояние живёт одну батарею: следующий
    профиль / одиночная проверка снова получают полноценную H3-пробу.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._deadline_hit = False

    @property
    def deadline_hit(self) -> bool:
        with self._lock:
            return self._deadline_hit

    def should_probe(self) -> bool:
        return not self.deadline_hit

    def note(self, result) -> None:
        if getattr(result, "error", "") == "deadline":
            with self._lock:
                self._deadline_hit = True


def quic_h3_probe(domain: str,
                  state: Optional[H3ProbeState] = None) -> tuple[bool, str]:
    """(ok, detail) тестерного контракта; ядро пробы вынесено в
    core/probe_h3.probe_h3 (аудит #9), deadline тестера - свой (6 с, T20)."""
    if state is not None and not state.should_probe():
        return False, _H3_SKIP_DETAIL
    r = probe_h3(domain, H3_WALL_DEADLINE, lib_timeout=H3_LIB_TIMEOUT)
    if state is not None:
        state.note(r)
    return r.ok, r.detail


def curl_test(domain: str, test_type: str, timeout: float, path: str = "/",
              h3_state: Optional[H3ProbeState] = None) -> TestResult:
    start = time.time()
    if domain in QUIC_QUIRK_DOMAINS:
        # QUIC-класс: TCP-путь заведомо не показателен (браузер ходит через
        # QUIC; fake+multisplit рвёт чужой ClientHello) - HEAD+GET давали
        # только 000 и лишние round-trip (аудит O2). Сразу H3-проба; без
        # niquests - прежний нейтральный QUIC (контракт статусов тот же).
        h3_ok, detail = quic_h3_probe(domain, h3_state)
        elapsed = (time.time() - start) * 1000
        if h3_ok:
            return TestResult(domain, test_type, "QUIC", None, elapsed,
                              f"H3 подтверждён ({detail})")
        if detail.startswith("нет niquests"):
            return TestResult(domain, test_type, "QUIC", None, elapsed, detail)
        if detail == _H3_SKIP_DETAIL:
            # Нейтральный статус (не BLOCKED, не OK): H3 не проверялся в
            # этой батарее после первого дедлайна.
            return TestResult(domain, test_type, "H3_NONE", None, elapsed,
                              detail)
        # Проба выполнена, но H3 не подтверждён: НЕ приравниваем к BLOCKED
        # (ошибка инструмента/таймаут != доказательство блокировки; ревью
        # 12.10). Статус нейтрален и не входит в ok/fail-статистику.
        return TestResult(domain, test_type, "H3_NONE", None, elapsed,
                          f"H3 не подтверждён: {detail}")
    url = f"https://{domain}{path}"
    timeout = float(min(int(timeout), timeouts.HTTP))
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
        if _is_dns_error(rc, stderr):
            # code is None при rc=6: старый код проверял code is not None
            # и поэтому DoH-фолбэк не запускался. Это давало ERROR/BLOCKED
            # для www.youtube.com при рабочем браузере с DoH.
            for doh_ip in doh_resolve_ips(domain)[:2]:
                code2, rc2, _, stderr2 = curl_attempt(
                    url, head=False, timeout=timeout,
                    resolve=f"{domain}:443:{doh_ip}")
                elapsed = (time.time() - start) * 1000
                if code2 is not None and code2 >= 100:
                    return TestResult(
                        domain, test_type, "OK", code2, elapsed,
                        "системный DNS подменён; путь жив (DoH-резолв)")
                code, rc, stderr = code2, rc2, stderr2
        if code is not None:
            # GET вернул «000» - нет HTTP-ответа (QUIC-класс сюда не
            # попадает: он обработан выше отдельной H3-пробой).
            return TestResult(domain, test_type, "BLOCKED", code, elapsed)
        # code=None: curl не дал HTTP-ответа вовсе (DNS/таймаут/TLS).
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
                     timeout: float = 8.0,
                     stop_event: Optional[threading.Event] = None) -> list[TestResult]:
    """Батарея curl/H3-проб.

    stop_event (T20, аудит B10): отмена проверяется МЕЖДУ пробами и между
    завершившимися futures - уже собранные результаты возвращаются частично,
    ожидание остальных не блокирует остановку (running-пробы ограничены
    своими -m и не пересоздаются). H3-бюджет (H3ProbeState) живёт одну
    батарею: после первого дедлайна остальные QUIC-хосты не пробуем.
    """
    if expand_www:
        test_items = expand_with_www(domains)
    else:
        test_items = list(domains)
    total = len(test_items)
    done = 0
    results: list[TestResult] = []
    h3_state = H3ProbeState()
    pool = ThreadPoolExecutor(max_workers=concurrency)
    futures = {}
    try:
        for d in test_items:
            if stop_event is not None and stop_event.is_set():
                break
            if http_only:
                fut = pool.submit(curl_test, d, "http", timeout, h3_state=h3_state)
            else:
                ttype = host_test_type(d)
                label = "tls:443" if ttype == "tls" else "https"
                fut = pool.submit(curl_test, d, label, timeout,
                                  h3_state=h3_state)
            futures[fut] = d
        for fut in as_completed(futures):
            d = futures[fut]
            r = fut.result()
            results.append(r)
            done += 1
            if progress_cb:
                progress_cb(done, total)
            if result_cb:
                result_cb(r)
            if stop_event is not None and stop_event.is_set():
                # Отмена: завершившуюся пробу сохранили, остальные не ждём.
                break
    finally:
        cancelled = stop_event is not None and stop_event.is_set()
        # cancel_futures - только при отмене: в обычном прогоне не теряем
        # поставленные в очередь пробы; при отмене - не начинаем новые.
        pool.shutdown(wait=not cancelled, cancel_futures=cancelled)
    return results


# ── TCP 16-20: бюджет под скорость аплинка (T20 / аудит B5) ──────────
# Скорость аплинка меряется один раз на процесс (TTL): маленький POST на
# control-хост, %{speed_upload}. Иначе на медленном канале -m 6 обрывал поток
# на 12+ КБ и это ложно трактовалось как stateful DPI.
_UPLOAD_RATE_LOCK = threading.Lock()
# (time, bytes/s | None): None - замер не удался (не повторяем его в цикле
# фаз скана; иначе каждая фаза ждала бы недоступный control-хост).
_UPLOAD_RATE_CACHE: Optional[tuple[float, Optional[float]]] = None
_UPLOAD_RATE_TTL = 300.0
_UPLOAD_RATE_NEG_TTL = 60.0
_UPLOAD_RATE_HOST = "www.gstatic.com"


def tcp1620_timeout(upload_rate: Optional[float]) -> float:
    """-m для TCP16-20: покрывает ОТПРАВКУ всего тела (64 КБ).

    rate - измеренная скорость аплинка в байт/с; None/<=0 - консервативный
    fallback (TCP1620_TIMEOUT_FALLBACK). Потолок - TCP1620_TIMEOUT_CAP, чтобы
    мёртвый хост не стоил минуту."""
    try:
        rate = float(upload_rate or 0.0)
    except (TypeError, ValueError):
        rate = 0.0
    if rate <= 0:
        return float(TCP1620_TIMEOUT_FALLBACK)
    need = TCP1620_BODY / rate
    return max(float(TCP1620_TIMEOUT_MIN),
               min(float(TCP1620_TIMEOUT_CAP),
                   need * float(TCP1620_RATE_MARGIN) + 2.0))


def _parse_speed_upload(stdout: str) -> tuple[int, int, float]:
    """(http_code, size_upload, speed_upload) из curl -w. Терпим к старым
    2-полевым форматам (speed=0.0) - совместимость тестов/формата."""
    parts = (stdout or "").strip().split()
    code = int(parts[0]) if parts and parts[0].isdigit() else 0
    uploaded = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    speed = 0.0
    if len(parts) > 2:
        try:
            speed = float(parts[2].replace(",", "."))
        except ValueError:
            speed = 0.0
    return code, uploaded, speed


def measure_upload_rate(timeout: float = 6.0) -> Optional[float]:
    """Измеренная скорость аплинка (байт/с) или None, если измерить не удалось.

    Мелкий POST (TCP1620_RATE_PROBE_BODY) на control-хост с %{speed_upload};
    кэш на _UPLOAD_RATE_TTL (свип/скан переиспользуют замер). Ошибки/DNS-спуф
    -> None: вызывающий берёт консервативный fallback-бюджет."""
    global _UPLOAD_RATE_CACHE
    now = time.monotonic()
    with _UPLOAD_RATE_LOCK:
        cached = _UPLOAD_RATE_CACHE
        if cached is not None:
            ttl = _UPLOAD_RATE_TTL if cached[1] is not None else _UPLOAD_RATE_NEG_TTL
            if now - cached[0] < ttl:
                return cached[1]

    def _store(rate: Optional[float]) -> Optional[float]:
        global _UPLOAD_RATE_CACHE
        with _UPLOAD_RATE_LOCK:
            _UPLOAD_RATE_CACHE = (time.monotonic(), rate)
        return rate

    body = os.urandom(TCP1620_RATE_PROBE_BODY)
    t = max(1.0, float(timeout))
    try:
        # --data-binary @- читает тело из stdin: без временных файлов.
        r = subprocess.run(
            ["curl.exe", "-4", "-sS", "-m", str(int(t)),
             "--connect-timeout", str(timeouts.CONNECT), "--noproxy", "*",
             "-H", "Expect:", "-w", "%{http_code} %{size_upload} %{speed_upload}",
             "-o", "NUL", "--data-binary", "@-",
             f"https://{_UPLOAD_RATE_HOST}/"],
            input=body, capture_output=True, timeout=t + timeouts.WALL_PAD,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        return _store(None)
    out = (r.stdout or b"").decode("oem", "replace")
    _, uploaded, speed = _parse_speed_upload(out)
    # Скорость считаем валидной, только если ушла почти вся проба: при
    # раннем ответе сервера size_upload занижен, и rate был бы заниженным
    # (слишком щедрый таймаут - не ошибка, но и пользы нет).
    if uploaded < TCP1620_RATE_PROBE_BODY * 3 // 4 or speed <= 0:
        return _store(None)
    return _store(speed)


def tcp1620_test_curl(domain: str, body_file: Path, timeout: float) -> TestResult:
    """TCP 16-20 через curl: POST 64 КБ, детект обрыва stateful DPI.

    Классификация по size_upload, а не только по http-коду: сигнатура
    «обрыв на N КБ» (как в dpi-detector, окно 12-36 КБ). timeout - готовый
    бюджет из tcp1620_timeout() (покрывает отправку тела, T20); curl -m
    таймаут с НЕПОЛНОЙ загрузкой - это медленный канал/DPI-тормоз, а не
    «обрыв на N КБ»: помечаем TIMEOUT, а не TCP16_20 (аудит B5)."""
    start = time.time()
    budget = max(float(TCP1620_TIMEOUT_MIN),
                 min(float(TCP1620_TIMEOUT_CAP), float(timeout)))

    def _curl(extra: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["curl.exe", "-4", "--no-sessionid", "--no-keepalive",
             "-sS", "-m", str(int(round(budget))),
             "--connect-timeout", str(timeouts.CONNECT),
             "--noproxy", "*",
             "-w", "%{http_code} %{size_upload} %{speed_upload}", "-o", "NUL",
             *extra,
             "--data-binary", f"@{body_file}",
             f"https://{domain}/"],
            capture_output=True, text=True, encoding="oem", errors="replace",
            timeout=budget + timeouts.WALL_PAD,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def _parse(r: subprocess.CompletedProcess) -> tuple[int, int, float]:
        return _parse_speed_upload(r.stdout or "")

    try:
        r = _curl([])
        code, uploaded, speed = _parse(r)
        if uploaded == 0 and _is_dns_error(r.returncode, r.stderr or ""):
            # спуф/сбой системного DNS - повтор по DoH-IP (см. curl_test)
            doh_ips = doh_resolve_ips(domain)
            if doh_ips:
                r = _curl(["--resolve", f"{domain}:443:{doh_ips[0]}"])
                code, uploaded, speed = _parse(r)
        elapsed = (time.time() - start) * 1000
        if uploaded >= TCP1620_BODY:
            # Полный объём ушёл, ответа нет (сервер молчит/таймаут) -
            # поток НЕ резан: это не сигнатура stateful DPI.
            return TestResult(domain, "tcp1620", "OK", 0, elapsed,
                              "upload OK, ответа нет")
        if code >= 200 and code < 500:
            # Сервер ответил - поток не резался (загрузка пережила ответ).
            return TestResult(domain, "tcp1620", "OK", code, elapsed)
        if r.returncode == 28 and uploaded > 0:
            # curl -m истёк, НЕ успев отправить тело: медленный аплинк или
            # DPI-тормоз. Сигнатура «обрыв на N КБ» - это сброс/закрытие
            # посреди потока, а не таймаут; иначе медленный канал получал
            # ложный TCP16_20 -> DET -> «hard» в CDN-скане (аудит B5).
            sp = f", {speed / 1024:.0f} КБ/с" if speed > 0 else ""
            return TestResult(domain, "tcp1620", "TIMEOUT", 0, elapsed,
                              f"таймаут {budget:.0f} с: загружено "
                              f"{uploaded // 1024} КБ из "
                              f"{TCP1620_BODY // 1024} КБ{sp} - медленный "
                              "канал/DPI-тормоз")
        if uploaded >= _TCP1620_MIN_KB * 1024:
            # Обрыв в окне 12..64 КБ - сигнатура stateful DPI (как в
            # dpi-detector: TCP_BLOCK_MIN_KB=12; меньше 12 КБ = медленный
            # канал/ранний обрыв, не признак DPI).
            return TestResult(domain, "tcp1620", "TCP16_20", 0, elapsed,
                              f"обрыв на {uploaded // 1024} КБ - stateful DPI")
        if uploaded > 0:
            return TestResult(domain, "tcp1620", "TIMEOUT", 0, elapsed,
                              f"upload {uploaded // 1024} КБ < 12 КБ - "
                              "медленный канал/ранний обрыв")
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
                      timeout: float = 8.0,
                      stop_event: Optional[threading.Event] = None,
                      upload_rate: Optional[float] = None) -> list[TestResult]:
    """TCP 16-20: curl POST с 64 КБ случайного тела.

    timeout - БАЗОВЫЙ бюджет; фактический = tcp1620_timeout(upload_rate)
    (покрывает отправку тела на медленном аплинке, T20). upload_rate=None -
    измеряем сами (measure_upload_rate) с консервативным fallback.
    stop_event - отмена батареи с частичным результатом."""
    if stop_event is not None and stop_event.is_set():
        return []
    results: list[TestResult] = []
    rate = upload_rate if upload_rate is not None else measure_upload_rate()
    budget = tcp1620_timeout(rate)
    # Тело - в локальном каталоге проб (не корень/temp): аварийный kill не
    # оставляет мусор в релизных каталогах, clean-up чистит старые файлы.
    try:
        body_file = probe_file(root_dir, "tcp1620-body", ".bin")
        body_file.write_bytes(os.urandom(TCP1620_BODY))
    except OSError:
        return [TestResult(d, "tcp1620", "ERROR", error="Cannot create test body")
                for d in domains]
    pool = ThreadPoolExecutor(max_workers=concurrency)
    futures = {}
    try:
        for d in domains:
            if stop_event is not None and stop_event.is_set():
                break
            futures[pool.submit(tcp1620_test_curl, d, body_file, budget)] = d
        for fut in as_completed(futures):
            results.append(fut.result())
            if stop_event is not None and stop_event.is_set():
                break
    finally:
        cancelled = stop_event is not None and stop_event.is_set()
        pool.shutdown(wait=not cancelled, cancel_futures=cancelled)
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
