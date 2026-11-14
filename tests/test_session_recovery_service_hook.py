"""T19/T10-1: startup-recovery поднимает recovery service-операций.

Порядок: сначала незавершённая операция службы, потом recovery тест-сессии -
иначе восстановление защиты тестера пересекалось бы с откатом install/remove.
Поток подменяется синхронным запуском, SCM не трогается (service_manager
recover_service_operation замокан).
"""
from __future__ import annotations

import threading

from server import session_recovery as sr


def test_recover_service_operation_delegates(tmp_path, monkeypatch) -> None:
    from core import service_manager as sm
    seen: dict = {}
    monkeypatch.setattr(
        sm, "recover_service_operation",
        lambda root, log=None: seen.update(root=root, log=log) or (True, "ok"))
    log = lambda _m: None
    assert sr.recover_service_operation(tmp_path, log=log) == (True, "ok")
    assert seen["root"] == tmp_path
    assert seen["log"] is log


def _sync_startup(monkeypatch, tmp_path, stubs: dict) -> list[str]:
    from core import service_manager as sm
    from server import app_state
    order: list[str] = []
    monkeypatch.setattr(app_state.STATE, "root_dir", tmp_path)
    monkeypatch.setattr(app_state.STATE, "tester_lock", threading.Lock())
    monkeypatch.setattr(app_state, "ui_debug", lambda _m: None)
    monkeypatch.setattr(sm, "recover_service_operation", stubs["service"])
    monkeypatch.setattr(sr, "recover_unfinished_session", stubs["tester"])

    class _SyncThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target

        def start(self) -> None:
            self._target()

    monkeypatch.setattr(sr.threading, "Thread", _SyncThread)
    return order


def test_startup_runs_service_recovery_before_tester_recovery(
        monkeypatch, tmp_path) -> None:
    order: list[str] = []
    stubs = {
        "service": lambda root, log=None: order.append("service") or (True, "ok"),
        "tester": lambda *a, **k: order.append("tester") or None,
    }
    _sync_startup(monkeypatch, tmp_path, stubs)
    sr.start_startup_recovery()
    assert order == ["service", "tester"]


def test_service_recovery_error_does_not_block_tester_recovery(
        monkeypatch, tmp_path) -> None:
    order: list[str] = []

    def broken(root, log=None):
        raise RuntimeError("boom")

    stubs = {
        "service": broken,
        "tester": lambda *a, **k: order.append("tester") or None,
    }
    _sync_startup(monkeypatch, tmp_path, stubs)
    sr.start_startup_recovery()  # не бросает
    assert order == ["tester"]
