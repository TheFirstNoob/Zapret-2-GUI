"""Tests for global mutating operation lock ownership (server.app_state)."""
import threading

import pytest

from server import app_state


@pytest.fixture
def fresh_state(monkeypatch):
    monkeypatch.setattr(app_state.STATE, "operation_lock", threading.Lock())
    monkeypatch.setattr(app_state.STATE, "operation_meta_lock", threading.Lock())
    monkeypatch.setattr(app_state.STATE, "operation_name", "")
    yield app_state.STATE


def test_foreign_end_does_not_release(fresh_state):
    assert app_state.begin_operation("service") is None
    busy = app_state.begin_operation("update")
    assert busy and "service" in busy
    app_state.end_operation("update")  # чужая операция не владелец
    assert app_state.begin_operation("update") is not None  # slot всё ещё занят
    app_state.end_operation("service")
    assert app_state.begin_operation("update") is None  # теперь свободно
    app_state.end_operation("update")


def test_double_end_is_safe(fresh_state):
    assert app_state.begin_operation("tester") is None
    app_state.end_operation("tester")
    app_state.end_operation("tester")  # повторный end не должен падать
    assert app_state.begin_operation("tester") is None
    app_state.end_operation("tester")


def test_empty_name_ignored(fresh_state):
    assert app_state.begin_operation("diag") is None
    app_state.end_operation("")
    assert app_state.begin_operation("service") is not None  # всё ещё занято
    app_state.end_operation("diag")
