"""T19/T12: быстрый status() службы через QueryServiceStatusEx + fallback."""
from __future__ import annotations

from core import service_manager as sm


def _reset_cache(monkeypatch) -> None:
    monkeypatch.setattr(sm, "_status_cache_at", 0.0)
    monkeypatch.setattr(sm, "_status_cache_value", None)
    monkeypatch.setattr(sm, "_installed_cache_at", 0.0)
    monkeypatch.setattr(sm, "_installed_cache_value", None)


def test_status_uses_win32_without_sc_exe(monkeypatch) -> None:
    _reset_cache(monkeypatch)
    sc_calls: list = []
    monkeypatch.setattr(sm, "_query_service_state", lambda: 4)
    monkeypatch.setattr(sm, "_sc", lambda args: sc_calls.append(args) or (0, ""))
    assert sm.status() == "running"
    assert sc_calls == []  # sc.exe не запускался


def test_status_maps_states(monkeypatch) -> None:
    _reset_cache(monkeypatch)
    for state, expected in ((1, "stopped"), (2, "stopped"), (3, "stopped")):
        monkeypatch.setattr(sm, "_query_service_state", lambda s=state: s)
        _reset_cache(monkeypatch)
        assert sm.status() == expected


def test_status_falls_back_to_sc_on_none(monkeypatch) -> None:
    _reset_cache(monkeypatch)
    monkeypatch.setattr(sm, "_query_service_state", lambda: None)
    monkeypatch.setattr(sm, "_sc",
                        lambda args: (0, "STATE : 4  RUNNING"))
    assert sm.status() == "running"
    _reset_cache(monkeypatch)
    monkeypatch.setattr(sm, "_query_service_state", lambda: None)
    monkeypatch.setattr(sm, "_sc", lambda args: (1060, "does not exist"))
    assert sm.status() == "not_installed"


def test_status_cached(monkeypatch) -> None:
    _reset_cache(monkeypatch)
    calls = []
    monkeypatch.setattr(sm, "_query_service_state",
                        lambda: calls.append(1) or 4)
    assert sm.status() == "running"
    assert sm.status() == "running"
    assert len(calls) == 1


def test_is_installed_uses_status(monkeypatch) -> None:
    _reset_cache(monkeypatch)
    monkeypatch.setattr(sm, "status", lambda: "stopped")
    assert sm.is_installed() is True
    _reset_cache(monkeypatch)
    monkeypatch.setattr(sm, "status", lambda: "not_installed")
    assert sm.is_installed() is False
