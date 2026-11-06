from __future__ import annotations

from core import service_manager


def test_wait_service_running_accepts_pending_then_running(monkeypatch) -> None:
    states = iter((2, 2, 4))
    monkeypatch.setattr(service_manager, "_query_service_state",
                        lambda: next(states))
    assert service_manager._wait_service_running(timeout=1.0) == (True, 4)


def test_wait_service_running_rejects_stopped(monkeypatch) -> None:
    monkeypatch.setattr(service_manager, "_query_service_state", lambda: 1)
    assert service_manager._wait_service_running(timeout=1.0) == (False, 1)
