"""T19/T10-2: remove() - SCM-recovery off, WaitForSingleObject, проверка
отсутствия службы и durable-журнал (без live-манипуляций службой)."""
from __future__ import annotations

import pytest

from core import service_manager as sm


def _common(monkeypatch, *, delete_ok: bool = True):
    calls: dict = {"sc": [], "pause": 0, "resume": 0, "reset": 0,
                   "wait": [], "killed": []}
    monkeypatch.setattr(sm, "path_status", lambda: ("ok", ""))
    monkeypatch.setattr(sm, "_invalidate_service_cache", lambda: None)

    def pause():
        calls["pause"] += 1
        return True

    monkeypatch.setattr(sm, "pause_recovery", pause)
    monkeypatch.setattr(sm, "resume_recovery",
                        lambda: calls.__setitem__("resume",
                                                  calls["resume"] + 1))
    monkeypatch.setattr(sm, "_reset_recovery_state",
                        lambda: calls.__setitem__("reset",
                                                  calls["reset"] + 1))
    monkeypatch.setattr(sm, "_failure_actions_disabled", lambda: True)
    monkeypatch.setattr(sm, "_query_service_state", lambda: None)

    def sc(args):
        calls["sc"].append(list(args))
        if args[0] == "query":
            return 1060, "The specified service does not exist"
        return 0, ""

    monkeypatch.setattr(sm, "_sc", sc)
    monkeypatch.setattr(sm, "_win32_delete_service",
                        lambda: (delete_ok, "" if delete_ok else "1072"))
    monkeypatch.setattr(sm, "_taskkill_winws2",
                        lambda: calls["killed"].append(42) or [42])

    def wait_winws2(pids, timeout=5.0):
        calls["wait"].append((list(pids), timeout))
        return True

    monkeypatch.setattr(sm, "_wait_winws2_exit", wait_winws2)
    monkeypatch.setattr(sm.time, "sleep", lambda _s: None)
    return calls


def test_remove_pauses_recovery_waits_by_pid_and_confirms_absence(monkeypatch) -> None:
    calls = _common(monkeypatch)
    result = sm._remove_impl(sm._NullJournal())
    assert result[0] is True
    assert calls["pause"] == 1
    assert calls["killed"] == [42]
    assert calls["wait"] == [([42], 5.0)]
    assert calls["reset"] == 1       # служба удалена - пауза сброшена
    assert calls["resume"] == 0
    # delete + подтверждающий query, не больше
    assert [c[0] for c in calls["sc"]] == ["stop", "delete", "query"]


def test_remove_restores_recovery_on_failure(monkeypatch) -> None:
    calls = _common(monkeypatch, delete_ok=False)
    # delete всегда «не удалилось», query показывает живую службу
    monkeypatch.setattr(sm, "_sc",
                        lambda args: (0, "STATE : 4 RUNNING")
                        if args[0] == "query" else (5, "Access denied"))
    result = sm._remove_impl(sm._NullJournal())
    assert result[0] is False
    assert calls["reset"] == 0
    assert calls["resume"] == 1


def test_remove_retries_until_absence_confirmed(monkeypatch) -> None:
    calls = _common(monkeypatch)
    checks = iter((False, True))
    monkeypatch.setattr(sm, "_service_absent",
                        lambda timeout=2.0: next(checks))
    result = sm._remove_impl(sm._NullJournal())
    assert result[0] is True
    deletes = [c for c in calls["sc"] if c[0] == "delete"]
    assert len(deletes) == 2


def test_remove_refuses_foreign_service(monkeypatch) -> None:
    calls = _common(monkeypatch)
    monkeypatch.setattr(sm, "path_status",
                        lambda: ("mismatch", "другая папка"))
    result = sm._remove_impl(sm._NullJournal())
    assert result[0] is False
    assert "другая папка" in result[1]
    assert calls["pause"] == 0
    assert calls["sc"] == []


def test_remove_crash_keeps_durable_journal(tmp_path, monkeypatch) -> None:
    _common(monkeypatch)
    monkeypatch.setattr(sm, "app_root", lambda: tmp_path)
    monkeypatch.setattr(sm, "_snapshot_prev_state", lambda root: {
        "installed": True, "running": True, "native": "NATIVE",
        "owner": "ok", "conf": None, "failure": None})

    def crash():
        raise RuntimeError("процесс убит посреди удаления")

    monkeypatch.setattr(sm, "_win32_delete_service", crash)
    with pytest.raises(RuntimeError):
        sm.remove()
    data = sm.read_service_op_journal(tmp_path)
    assert data is not None
    assert data["state"] == "IN_PROGRESS"
    assert data["action"] == "remove"


def test_remove_success_clears_journal(tmp_path, monkeypatch) -> None:
    calls = _common(monkeypatch)
    monkeypatch.setattr(sm, "app_root", lambda: tmp_path)
    monkeypatch.setattr(sm, "_snapshot_prev_state", lambda root: {
        "installed": True, "running": True, "native": "NATIVE",
        "owner": "ok", "conf": None, "failure": None})
    result = sm.remove()
    assert result[0] is True
    assert sm.read_service_op_journal(tmp_path) is None
    assert calls["pause"] == 1


def test_start_impl_journal_steps(tmp_path, monkeypatch) -> None:
    """start() пишет журнал и очищает его при штатном завершении."""
    monkeypatch.setattr(sm, "app_root", lambda: tmp_path)
    monkeypatch.setattr(sm, "_snapshot_prev_state", lambda root: {
        "installed": True, "running": False, "native": "NATIVE",
        "owner": "ok", "conf": None, "failure": None})
    monkeypatch.setattr(sm, "is_installed", lambda: True)
    monkeypatch.setattr(sm, "_zapret1_conflict", lambda: None)
    monkeypatch.setattr(sm, "_invalidate_service_cache", lambda: None)
    monkeypatch.setattr(sm, "path_status", lambda: ("ok", ""))
    # enable_for_engine трогает tcp timestamps системы - в тесте только заглушка
    from core import tcp_timestamps
    monkeypatch.setattr(tcp_timestamps, "enable_for_engine",
                        lambda *a, **k: (True, ""))
    monkeypatch.setattr(sm, "stop", lambda: (True, "ok"))
    monkeypatch.setattr(sm, "migrate_if_needed", lambda: (True, "уже новый"))
    monkeypatch.setattr(sm.time, "sleep", lambda _s: None)
    monkeypatch.setattr(sm, "_sc", lambda args: (0, ""))
    monkeypatch.setattr(sm, "_wait_service_running", lambda timeout=10.0: (True, 4))
    # conf-предпроверка: файл должен существовать и проходить validate_args
    conf = sm._service_conf_path(tmp_path)
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text("--wf-tcp=80", encoding="utf-8")
    monkeypatch.setattr("core.launcher.validate_args",
                        lambda *a, **k: (True, ""))
    # внутренний fix_stale_windivert_services не должен трогать систему
    import core.utils as cutils
    monkeypatch.setattr(cutils, "fix_stale_windivert_services",
                        lambda *a, **k: [], raising=False)
    result = sm.start(None)
    assert result[0] is True
    assert sm.read_service_op_journal(tmp_path) is None


def test_service_absent_requires_scm_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(sm, "_query_service_state", lambda: None)
    monkeypatch.setattr(sm, "_sc",
                        lambda args: (0, "STATE : 4 RUNNING"))
    monkeypatch.setattr(sm.time, "sleep", lambda _s: None)
    assert sm._service_absent(timeout=0.0) is False
    monkeypatch.setattr(sm, "_sc", lambda args: (1060, ""))
    assert sm._service_absent(timeout=0.0) is True
    # 1072 отмечена для удаления - НЕ отсутствие службы
    monkeypatch.setattr(sm, "_sc",
                        lambda args: (1072, "The service is marked for deletion"))
    assert sm._service_absent(timeout=0.0) is False


def test_remove_reports_marked_for_deletion(monkeypatch) -> None:
    _common(monkeypatch, delete_ok=False)
    monkeypatch.setattr(sm, "_sc",
                        lambda args: (1072, "The service is marked for deletion"))
    result = sm._remove_impl(sm._NullJournal())
    assert result[0] is False
    assert "отмечена для удаления" in result[1]


def test_recreate_old_service_restores_failure_actions(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(sm, "_win32_create_service",
                        lambda native: (True, ""))
    monkeypatch.setattr(sm, "_sc",
                        lambda args: calls.append(list(args)) or (0, ""))
    monkeypatch.setattr(sm, "_apply_failure_actions",
                        lambda reset, actions: calls.append(
                            ["failure", int(reset), list(actions)]) or True)
    ok, msg = sm._recreate_old_service(
        chr(34) + "C:/App/bin/winws2.exe" + chr(34) + " @" + chr(34)
        + "C:/App/logs/service_run.conf" + chr(34),
        False, {"reset": 86400, "actions": [(1, 60000)]})
    assert ok, msg
    assert ["failure", 86400, [(1, 60000)]] in calls


def test_recreate_old_service_without_failure_keeps_config(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(sm, "_win32_create_service",
                        lambda native: (True, ""))
    monkeypatch.setattr(sm, "_sc",
                        lambda args: calls.append(list(args)) or (0, ""))
    monkeypatch.setattr(sm, "_apply_failure_actions",
                        lambda reset, actions: calls.append(["failure"]) or True)
    ok, _msg = sm._recreate_old_service("C:/x/winws2.exe", False, None)
    assert ok
    assert ["failure"] not in calls  # исходной конфигурации нет - не мутируем
    assert any(c[0] == "description" for c in calls)
