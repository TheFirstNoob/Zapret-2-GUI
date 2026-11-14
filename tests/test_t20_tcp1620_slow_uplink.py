"""T20: TCP16-20 на медленном аплинке - бюджет под скорость, без ложного DPI.

Сеть не трогается: subprocess.run/measure_upload_rate замоканы.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from core import tester_probes
from core.tester_defs import (TCP1620_BODY, TCP1620_TIMEOUT_CAP,
                              TCP1620_TIMEOUT_FALLBACK, TCP1620_TIMEOUT_MIN)


class _R:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def _run(monkeypatch, stdout: str, rc: int = 0, timeout: float = 6.0):
    monkeypatch.setattr(tester_probes.subprocess, "run",
                        lambda *a, **k: _R(stdout, rc))
    return tester_probes.tcp1620_test_curl("example.com", Path("body.bin"), timeout)


# ── формула бюджета ─────────────────────────────────────────────────

def test_timeout_covers_body_at_measured_rate():
    # 8 КБ/с: 64 КБ = 8 с; 8*1.5+2 = 14 с
    assert tester_probes.tcp1620_timeout(8 * 1024) == 14.0


def test_timeout_has_floor_for_fast_uplink():
    # 1 МБ/с: 0.0625*1.5+2 < 6 -> пол 6 с
    assert tester_probes.tcp1620_timeout(1024 * 1024) == TCP1620_TIMEOUT_MIN


def test_timeout_has_cap_for_very_slow_uplink():
    # 1 КБ/с: нужно 64*1.5+2=98 с -> потолок 30 с (мёртвый хост не минута)
    assert tester_probes.tcp1620_timeout(1024) == TCP1620_TIMEOUT_CAP
    assert TCP1620_TIMEOUT_CAP == 30.0


def test_timeout_fallback_when_rate_unknown():
    assert tester_probes.tcp1620_timeout(None) == TCP1620_TIMEOUT_FALLBACK
    assert tester_probes.tcp1620_timeout(0) == TCP1620_TIMEOUT_FALLBACK
    assert tester_probes.tcp1620_timeout("bad") == TCP1620_TIMEOUT_FALLBACK


# ── классификация ───────────────────────────────────────────────────

def test_timeout_with_partial_upload_is_not_stateful_dpi(monkeypatch):
    # 20 КБ ушло и curl -m истёк (rc=28): медленный канал/DPI-тормоз, НЕ DET
    r = _run(monkeypatch, "000 20480 5120.0", rc=28)
    assert r.status == "TIMEOUT"
    assert "медленный" in r.error and "20 КБ" in r.error
    assert "stateful" not in r.error


def test_timeout_just_below_full_body_is_not_dpi(monkeypatch):
    # 60 из 64 КБ и таймаут: тоже не DET (сигнатура обрыва - не таймаут)
    r = _run(monkeypatch, "000 61440 10240.0", rc=28)
    assert r.status == "TIMEOUT"


def test_partial_upload_without_timeout_is_stateful_dpi(monkeypatch):
    # rc != 28 и поток умер на 20 КБ - это и есть сигнатура обрыва
    r = _run(monkeypatch, "000 20480 4096.0", rc=56)
    assert r.status == "TCP16_20"


def test_full_upload_is_ok(monkeypatch):
    r = _run(monkeypatch, f"000 {TCP1620_BODY} 8000.0", rc=0)
    assert r.status == "OK"


def test_http_response_is_ok(monkeypatch):
    r = _run(monkeypatch, "200 5000 1000.0", rc=0)
    assert r.status == "OK"


# ── измерение аплинка ───────────────────────────────────────────────

def _completed(stdout: bytes):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout,
                                       stderr=b"")


def test_measure_upload_rate_parses_curl_and_caches(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _completed(b"405 16384 8192.0")

    monkeypatch.setattr(tester_probes.subprocess, "run", fake_run)
    monkeypatch.setattr(tester_probes, "_UPLOAD_RATE_CACHE", None)
    rate = tester_probes.measure_upload_rate()
    assert rate == 8192.0
    # повторный вызов (в пределах TTL) - из кэша, без curl
    assert tester_probes.measure_upload_rate() == 8192.0
    assert len(calls) == 1


def test_measure_upload_rate_rejects_early_response(monkeypatch):
    # сервер ответил до отправки тела: rate занижен - не доверяем
    monkeypatch.setattr(tester_probes.subprocess, "run",
                        lambda *a, **k: _completed(b"405 1024 200.0"))
    monkeypatch.setattr(tester_probes, "_UPLOAD_RATE_CACHE", None)
    assert tester_probes.measure_upload_rate() is None


def test_measure_upload_rate_handles_oserror_and_negative_cache(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise OSError("curl not found")

    monkeypatch.setattr(tester_probes.subprocess, "run", boom)
    monkeypatch.setattr(tester_probes, "_UPLOAD_RATE_CACHE", None)
    assert tester_probes.measure_upload_rate() is None
    # Неудачный замер кэшируется на короткий TTL: фазы скана не ждут
    # недоступный control-хост повторно.
    assert tester_probes.measure_upload_rate() is None
    assert len(calls) == 1


# ── батарея: бюджет и чистка тела ───────────────────────────────────

def test_run_tcp1620_uses_rate_budget_and_cleans_body(monkeypatch, tmp_path):
    captured = {}

    def fake_test(domain, body_file, timeout):
        captured["timeout"] = timeout
        assert body_file.exists(), "тело должно существовать на момент пробы"
        return tester_probes.TestResult(domain, "tcp1620", "OK", 0, 1.0)

    monkeypatch.setattr(tester_probes, "tcp1620_test_curl", fake_test)
    monkeypatch.setattr(tester_probes, "measure_upload_rate", lambda: 8 * 1024)
    res = tester_probes.run_tcp1620_tests(tmp_path, ["a.example"], concurrency=1)
    assert [r.status for r in res] == ["OK"]
    assert captured["timeout"] == 14.0
    probe_dir = tmp_path / tester_probes.PROBE_DIR_NAME / "probe"
    # тело пробы удалено, каталог проб пуст
    assert list(probe_dir.iterdir()) == []


def test_run_tcp1620_cancel_returns_partial_and_cleans_body(monkeypatch, tmp_path):
    import threading

    ev = threading.Event()

    def fake_test(domain, body_file, timeout):
        ev.set()   # отмена пришла во время первой пробы
        return tester_probes.TestResult(domain, "tcp1620", "OK", 0, 1.0)

    monkeypatch.setattr(tester_probes, "tcp1620_test_curl", fake_test)
    monkeypatch.setattr(tester_probes, "measure_upload_rate", lambda: None)
    res = tester_probes.run_tcp1620_tests(
        tmp_path, ["a.example", "b.example", "c.example"],
        concurrency=1, stop_event=ev)
    assert [r.domain for r in res] == ["a.example"]
    probe_dir = tmp_path / tester_probes.PROBE_DIR_NAME / "probe"
    assert list(probe_dir.iterdir()) == []
