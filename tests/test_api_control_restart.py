"""T12/T19: сериализация restart-цепочки stop->start и дедупликация start.

Фронтенд перезапускает обход двумя POST'ами (/api/stop -> 1.2 c -> /api/start).
Раньше, если stop занимал больше 1.2 c, start получал «Уже выполняется» и
обход оставался снятым; двойной клик давал второй stop/start. Тесты
проверяют поведение ручек api_control без живой службы.
"""
from __future__ import annotations

import threading
import time

import pytest

from core import service_manager as sm
from server import api_control as ac


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(ac, "_last_start_fp", "")
    monkeypatch.setattr(ac, "_last_start_at", 0.0)
    monkeypatch.setattr(ac, "_bypass_gate", threading.Lock())
    monkeypatch.setattr(ac, "_DEDUPE_WINDOW", 2.5)
    yield


def _patch_start(monkeypatch, calls: list, *, start_ok: bool = True):
    state = {"running": False}
    monkeypatch.setattr(ac, "checkers_busy", lambda: None)
    monkeypatch.setattr(ac, "scan_winws_exe",
                        lambda: {"running": False, "pid": 0})
    monkeypatch.setattr(ac, "svc_installed", lambda: True)
    monkeypatch.setattr(sm, "path_status", lambda: ("ok", ""))
    monkeypatch.setattr(ac.api_service, "prepare_service_args",
                        lambda data: (["--x"], ""))

    def svc_start(args):
        calls.append(("start", tuple(args)))
        state["running"] = start_ok
        return start_ok, "winws2 запущен" if start_ok else "сбой"

    def svc_stop():
        calls.append(("stop",))
        state["running"] = False
        return True, "winws2 остановлен"

    monkeypatch.setattr(ac, "svc_start", svc_start)
    monkeypatch.setattr(ac, "svc_stop", svc_stop)
    monkeypatch.setattr(ac, "svc_status",
                        lambda: "running" if state["running"] else "stopped")

    class _Controller:
        current_strategy = None

        def stop(self):
            calls.append(("ctl-stop",))
            state["running"] = False
            return True

        def is_running(self):
            return state["running"]

    monkeypatch.setattr(ac, "get_controller", lambda: _Controller())
    monkeypatch.setattr(ac, "kill_image_filtered", lambda *a, **k: [])
    monkeypatch.setattr(ac, "_my_winws2_paths", lambda: set())
    return state


def test_start_skips_duplicate_restart(monkeypatch) -> None:
    calls: list = []
    _patch_start(monkeypatch, calls)
    data = {"profile": "default", "debug": False, "autohostlist": True}
    first = ac.start_zapret(None, dict(data))
    second = ac.start_zapret(None, dict(data))
    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert [c[0] for c in calls].count("start") == 1


def test_start_runs_for_different_profile(monkeypatch) -> None:
    calls: list = []
    _patch_start(monkeypatch, calls)
    ac.start_zapret(None, {"profile": "default"})
    result = ac.start_zapret(None, {"profile": "auto"})
    assert result["status"] == "ok"
    assert [c[0] for c in calls].count("start") == 2


def test_start_after_explicit_stop_is_not_deduped(monkeypatch) -> None:
    calls: list = []
    _patch_start(monkeypatch, calls)
    data = {"profile": "default"}
    ac.start_zapret(None, dict(data))
    stopped = ac.stop_zapret(None)
    assert stopped["status"] == "ok"
    started = ac.start_zapret(None, dict(data))
    assert started["status"] == "ok"
    assert [c[0] for c in calls].count("start") == 2


def test_failed_start_is_not_remembered(monkeypatch) -> None:
    calls: list = []
    _patch_start(monkeypatch, calls, start_ok=False)
    data = {"profile": "default"}
    assert ac.start_zapret(None, dict(data))["status"] == "error"
    assert ac.start_zapret(None, dict(data))["status"] == "error"
    assert [c[0] for c in calls].count("start") == 2


def test_busy_checkers_block_start(monkeypatch) -> None:
    calls: list = []
    _patch_start(monkeypatch, calls)
    monkeypatch.setattr(ac, "checkers_busy", lambda: "Тестер занят")
    result = ac.start_zapret(None, {"profile": "default"})
    assert result["status"] == "error"
    assert "Тестер занят" in result["message"]
    assert calls == []


def test_gate_timeout_returns_busy_error(monkeypatch) -> None:
    calls: list = []
    _patch_start(monkeypatch, calls)
    monkeypatch.setattr(ac, "_GATE_WAIT", 0.05)
    assert ac._bypass_gate.acquire(timeout=0)
    try:
        result = ac.start_zapret(None, {"profile": "default"})
    finally:
        ac._bypass_gate.release()
    assert result["status"] == "error"
    assert "уже выполняется" in result["message"].lower()
    assert calls == []


def test_restart_start_waits_for_slow_stop(monkeypatch) -> None:
    """stop > 1.2 c: start ждёт завершения stop, а не падает «Уже выполняется»."""
    calls: list = []
    state = _patch_start(monkeypatch, calls)
    stop_entered = threading.Event()
    release_stop = threading.Event()

    def slow_stop():
        stop_entered.set()
        release_stop.wait(3.0)
        calls.append(("stop",))
        state["running"] = False
        return True, "winws2 остановлен"

    monkeypatch.setattr(ac, "svc_stop", slow_stop)
    stop_result: list = []
    stop_thread = threading.Thread(
        target=lambda: stop_result.append(ac.stop_zapret(None)))
    stop_thread.start()
    assert stop_entered.wait(1.0)

    start_result: list = []
    start_thread = threading.Thread(
        target=lambda: start_result.append(
            ac.start_zapret(None, {"profile": "default"})))
    start_thread.start()
    time.sleep(0.15)
    assert start_result == []          # ждёт gate, а не падает сразу
    release_stop.set()
    stop_thread.join(5.0)
    start_thread.join(5.0)
    assert stop_result and stop_result[0]["status"] == "ok"
    assert start_result and start_result[0]["status"] == "ok"
    assert [c[0] for c in calls].count("start") == 1
