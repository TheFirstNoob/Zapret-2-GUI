"""T20: H3-проба - дедлайн 6 с, отмена потока-сторожа, скип после дедлайна.

Только фейковый niquests/сокеты: реальная сеть/QUIC не трогаются.
"""
from __future__ import annotations

import sys
import threading
import time
import types

from core import probe_h3, tester_probes
from core.probe_h3 import H3Result
from core.tester_defs import H3_LIB_TIMEOUT, H3_WALL_DEADLINE


class _QuicCache:
    def __init__(self) -> None:
        self.domains: list[str] = []

    def add_domain(self, domain: str) -> None:
        self.domains.append(domain)


class _OkSession:
    def __init__(self) -> None:
        self.trust_env = True
        self.quic_cache_layer = _QuicCache()
        self.closed = 0

    def get(self, url, timeout=None, allow_redirects=False):
        return types.SimpleNamespace(http_version=30, status_code=204)

    def close(self) -> None:
        self.closed += 1


class _ErrSession(_OkSession):
    def get(self, *a, **k):
        raise ValueError("bad quic")


class _BlockingSession(_OkSession):
    """get блокируется до close() - эмулирует зависший QUIC."""

    def __init__(self) -> None:
        super().__init__()
        self._closed = threading.Event()
        self.close_calls = 0

    def get(self, *a, **k):
        self._closed.wait(5.0)
        raise RuntimeError("closed")

    def close(self) -> None:
        self.close_calls += 1
        self._closed.set()


class _StuckSession(_BlockingSession):
    """close() НЕ будит get: проверяем учёт потока-сироты."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def get(self, *a, **k):
        self.release.wait(5.0)
        raise RuntimeError("released")

    def close(self) -> None:
        self.close_calls += 1


def _fake_niquests(monkeypatch, session_factory):
    mod = types.ModuleType("niquests")

    def _session(**_kw):
        return session_factory()

    mod.Session = _session
    monkeypatch.setitem(sys.modules, "niquests", mod)
    monkeypatch.setattr(probe_h3, "_HAS_NIQUESTS", None)
    return mod


def test_no_niquests_is_neutral_detail(monkeypatch):
    monkeypatch.setattr(probe_h3, "_HAS_NIQUESTS", False)
    r = probe_h3.probe_h3("example.com", 0.5)
    assert r.ok is False and r.detail == "нет niquests"


def test_h3_success_and_lib_timeout(monkeypatch):
    calls = {}

    def factory():
        s = _OkSession()
        calls["session"] = s
        return s

    _fake_niquests(monkeypatch, factory)
    r = probe_h3.probe_h3("example.com", 0.5)
    assert r.ok is True and r.http_version == 30
    assert r.detail == "H3 204"
    assert calls["session"].quic_cache_layer.domains == ["example.com"]
    assert calls["session"].trust_env is False
    assert calls["session"].closed >= 1


def test_h3_exception_detail(monkeypatch):
    _fake_niquests(monkeypatch, _ErrSession)
    r = probe_h3.probe_h3("example.com", 0.5)
    assert r.ok is False and r.detail == "QUIC ValueError"


def test_deadline_closes_session_and_leaves_no_orphan(monkeypatch):
    sessions = []

    def factory():
        s = _BlockingSession()
        sessions.append(s)
        return s

    _fake_niquests(monkeypatch, factory)
    probe_h3.clear_orphans()
    t0 = time.time()
    r = probe_h3.probe_h3("slow.example", 0.05)
    spent = time.time() - t0
    assert r.error == "deadline" and r.detail == "H3 висит (дедлайн)"
    # дедлайн + короткий grace, а не внутренние (4,8)
    assert spent < 2.0
    assert sessions and sessions[0].close_calls >= 1
    # поток завершился после close() - сирот нет
    assert probe_h3.orphan_threads() == []


def test_stuck_thread_is_counted_as_orphan(monkeypatch):
    sessions = []

    def factory():
        s = _StuckSession()
        sessions.append(s)
        return s

    _fake_niquests(monkeypatch, factory)
    probe_h3.clear_orphans()
    r = probe_h3.probe_h3("stuck.example", 0.05)
    assert r.detail == "H3 висит (дедлайн)"
    assert sessions[0].close_calls >= 1
    assert probe_h3.orphan_threads() == ["stuck.example"]
    # отпускаем поток и чистим состояние, чтобы он не жил после теста
    sessions[0].release.set()
    for _ in range(50):
        if not probe_h3.orphan_threads():
            break
        time.sleep(0.01)
    probe_h3.clear_orphans()


def test_cancelled_before_start_does_not_touch_niquests(monkeypatch):
    constructed = []
    mod = types.ModuleType("niquests")

    def _session(**_kw):
        constructed.append(1)
        return _OkSession()

    mod.Session = _session
    monkeypatch.setitem(sys.modules, "niquests", mod)
    monkeypatch.setattr(probe_h3, "_HAS_NIQUESTS", True)
    ev = threading.Event()
    ev.set()
    r = probe_h3.probe_h3("example.com", 1.0, cancel_event=ev)
    assert r.detail == "H3 отменён" and not constructed


# ── контракт тестера (tester_probes) ────────────────────────────────

def test_h3_budget_skips_after_first_deadline(monkeypatch):
    calls = []

    def fake_probe(domain, wall_deadline, lib_timeout=(4, 8), cancel_event=None):
        calls.append((domain, wall_deadline, lib_timeout))
        return H3Result(ok=False, error="deadline", detail="H3 висит (дедлайн)")

    monkeypatch.setattr(tester_probes, "probe_h3", fake_probe)
    state = tester_probes.H3ProbeState()
    ok, detail = tester_probes.quic_h3_probe("a.example", state)
    assert ok is False and detail == "H3 висит (дедлайн)"
    assert state.deadline_hit is True
    assert calls[0][1] == 6.0 and calls[0][2] == (2.0, 4.0)
    ok2, detail2 = tester_probes.quic_h3_probe("b.example", state)
    assert ok2 is False and detail2 == tester_probes._H3_SKIP_DETAIL
    assert len(calls) == 1, "после дедлайна H3 больше не пробуется в этой батарее"


def test_quic_curl_test_skips_tcp_roundtrips(monkeypatch):
    """QUIC-класс: сразу H3, HEAD/GET (лишние round-trip) не делаются."""
    http_calls = []

    def fake_curl_attempt(*a, **k):
        http_calls.append(1)
        raise AssertionError("TCP-проба не должна вызываться для QUIC-класса")

    monkeypatch.setattr(tester_probes, "curl_attempt", fake_curl_attempt)

    def fake_probe(domain, wall_deadline, lib_timeout=(4, 8), cancel_event=None):
        return H3Result(ok=True, http_version=30, status_code=200,
                        detail="H3 200")

    monkeypatch.setattr(tester_probes, "probe_h3", fake_probe)
    r = tester_probes.curl_test("www.youtube.com", "https", 6.0)
    assert r.status == "QUIC" and "H3 подтверждён" in r.error
    assert not http_calls
    assert r.status_code is None


def test_quic_curl_test_skip_detail_is_neutral_h3_none(monkeypatch):
    state = tester_probes.H3ProbeState()
    state.note(H3Result(ok=False, error="deadline"))

    def fake_probe(*a, **k):
        raise AssertionError("H3 не должен пробоваться после дедлайна")

    monkeypatch.setattr(tester_probes, "probe_h3", fake_probe)
    r = tester_probes.curl_test("youtu.be", "http", 6.0, h3_state=state)
    assert r.status == "H3_NONE"
    assert r.error == tester_probes._H3_SKIP_DETAIL


def test_h3_constants_are_reduced():
    assert H3_WALL_DEADLINE == 6.0
    assert H3_LIB_TIMEOUT == (2.0, 4.0)
