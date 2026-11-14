"""T19: refcounted pause/resume SCM-recovery (вложенные операции службы)."""
from __future__ import annotations

import pytest

from core import service_manager as sm


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(sm, "_recovery_paused", False)
    monkeypatch.setattr(sm, "_recovery_was_on", False)
    monkeypatch.setattr(sm, "_recovery_saved", None)
    monkeypatch.setattr(sm, "_recovery_refs", 0)
    yield


def _setup(monkeypatch, *, owned: bool = True, saved=None,
           apply_ok: bool = True):
    state = {"applied": [], "apply_ok": apply_ok}
    monkeypatch.setattr(sm, "_recovery_owned",
                        lambda: (owned, "" if owned else "не наша служба"))
    monkeypatch.setattr(sm, "_read_failure_actions_win32", lambda: saved)
    monkeypatch.setattr(sm, "_apply_failure_actions",
                        lambda reset, actions: state["applied"].append(
                            (int(reset), tuple(tuple(int(x) for x in a)
                                               for a in actions))) or apply_ok)
    return state


def test_nested_pause_resume_restores_only_on_last(monkeypatch) -> None:
    state = _setup(monkeypatch,
                   saved={"reset": 86400, "actions": [(1, 60000)]})
    assert sm.pause_recovery() is True
    assert sm._recovery_refs == 1
    assert state["applied"] == [(0, ())]
    assert sm.pause_recovery() is True
    assert sm._recovery_refs == 2
    assert len(state["applied"]) == 1          # повторно SCM не трогали
    sm.resume_recovery()
    assert sm._recovery_refs == 1
    assert sm._recovery_paused is True
    assert len(state["applied"]) == 1          # внешняя пауза ещё активна
    sm.resume_recovery()
    assert sm._recovery_refs == 0
    assert sm._recovery_paused is False
    assert state["applied"][-1] == (86400, ((1, 60000),))
    sm.resume_recovery()                       # непарный resume - no-op
    assert sm._recovery_refs == 0


def test_pause_fail_closed_without_exact_read(monkeypatch) -> None:
    state = _setup(monkeypatch, saved=None)
    assert sm.pause_recovery() is False
    assert sm._recovery_refs == 0
    assert sm._recovery_paused is False
    assert state["applied"] == []
    sm.resume_recovery()
    assert sm._recovery_paused is False


def test_pause_fail_closed_when_apply_fails(monkeypatch) -> None:
    _setup(monkeypatch, saved={"reset": 0, "actions": [(1, 60000)]},
           apply_ok=False)
    assert sm.pause_recovery() is False
    assert sm._recovery_refs == 0
    assert sm._recovery_saved is None


def test_pause_skipped_for_foreign_service(monkeypatch) -> None:
    _setup(monkeypatch, owned=False,
           saved={"reset": 0, "actions": [(1, 60000)]})
    assert sm.pause_recovery() is False
    assert sm._recovery_refs == 0


def test_reset_recovery_state_clears_pause(monkeypatch) -> None:
    _setup(monkeypatch, saved={"reset": 0, "actions": [(1, 60000)]})
    assert sm.pause_recovery() is True
    assert sm._recovery_refs == 1
    sm._reset_recovery_state()
    assert (sm._recovery_paused, sm._recovery_saved,
            sm._recovery_refs) == (False, None, 0)
    sm.resume_recovery()
    assert sm._recovery_paused is False


def test_failure_actions_disabled_detection(monkeypatch) -> None:
    monkeypatch.setattr(sm, "_read_failure_actions_win32",
                        lambda: {"reset": 0, "actions": []})
    assert sm._failure_actions_disabled() is True
    monkeypatch.setattr(sm, "_read_failure_actions_win32",
                        lambda: {"reset": 0, "actions": [(1, 60000)]})
    assert sm._failure_actions_disabled() is False
    monkeypatch.setattr(sm, "_read_failure_actions_win32", lambda: None)
    assert sm._failure_actions_disabled() is False


def test_recovery_snapshot_only_when_paused(monkeypatch) -> None:
    _setup(monkeypatch, saved={"reset": 86400, "actions": [(1, 60000)]})
    assert sm.recovery_snapshot() is None
    sm.pause_recovery()
    snap = sm.recovery_snapshot()
    assert snap is not None
    assert snap["was_on"] is True
    assert snap["saved"] == {"reset": 86400, "actions": [[1, 60000]]}


def test_restore_recovery_from_snapshot(monkeypatch) -> None:
    state = _setup(monkeypatch, owned=True)
    monkeypatch.setattr(sm, "_sc", lambda args: (0, ""))
    assert sm.restore_recovery_from_snapshot(
        {"was_on": False, "saved": {"reset": 0, "actions": []}}) is True
    assert state["applied"] == [(0, ())]
    assert sm.restore_recovery_from_snapshot(None) is True
    assert sm.restore_recovery_from_snapshot(
        {"was_on": True, "saved": None}) is True
