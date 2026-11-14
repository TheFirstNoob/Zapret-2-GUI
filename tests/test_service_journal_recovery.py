"""T19/T10-1: durable-журнал mutating-операций службы и его recovery.

Никаких живых SCM-вызовов: Win32/SC-обвязка service_manager подменяется
фейковой моделью службы (installed/running/binpath). Так проверяется именно
логика журнала/отката, а не поведение конкретной машины.
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from core import service_manager as sm


@pytest.fixture(autouse=True)
def _fresh_globals(monkeypatch):
    monkeypatch.setattr(sm, "_journal_depth", 0)
    monkeypatch.setattr(sm, "_recovering", False)
    monkeypatch.setattr(sm, "_recovery_paused", False)
    monkeypatch.setattr(sm, "_recovery_saved", None)
    monkeypatch.setattr(sm, "_recovery_was_on", False)
    monkeypatch.setattr(sm, "_recovery_refs", 0)
    yield


def _prev(*, installed: bool = True, running: bool = True,
          native: str = "OLD_NATIVE", conf: bytes | None = b"old-conf",
          owner: str = "ok", failure=None) -> dict:
    return {
        "installed": installed,
        "running": running,
        "native": native,
        "owner": owner,
        "conf": (base64.b64encode(conf).decode("ascii")
                 if conf is not None else None),
        "failure": failure,
    }


def _seed(root: Path, action: str, prev: dict, *, step: str = "begin",
          state: str = "IN_PROGRESS") -> None:
    sm._service_journal_write(root, {
        "state": state, "action": action, "step": step,
        "started": "2026-11-14T00:00:00", "root": str(root), "prev": prev,
    })


def _conf_path(root: Path) -> Path:
    path = sm._service_conf_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class FakeService:
    """Фейковая служба: Win32/SCM-функции подменяются на состояние в памяти."""

    def __init__(self) -> None:
        self.installed = False
        self.running = False
        self.binpath = ""
        self.calls: list[tuple] = []

    def patch(self, monkeypatch) -> "FakeService":
        monkeypatch.setattr(sm, "_invalidate_service_cache", lambda: None)
        monkeypatch.setattr(sm, "_service_installed_safe",
                            lambda: self.installed)
        monkeypatch.setattr(sm, "_service_running_safe", lambda: self.running)
        monkeypatch.setattr(sm, "_read_stored_binpath", lambda: self.binpath)

        def sc(args):
            self.calls.append(("sc", tuple(args)))
            if args and args[0] == "start":
                self.running = True
            return 0, ""

        monkeypatch.setattr(sm, "_sc", sc)

        def create(native):
            self.calls.append(("create", native))
            self.installed, self.binpath = True, native
            return True, ""

        def change(native):
            self.calls.append(("change", native))
            self.binpath = native
            return True, ""

        def start(args=None):
            self.calls.append(("start", args))
            self.running = True
            return True, "ok"

        def stop():
            self.calls.append(("stop",))
            self.running = False
            return True, "ok"

        def remove():
            self.calls.append(("remove",))
            self.installed = self.running = False
            return True, ""

        def failure(reset, actions):
            self.calls.append(("failure", int(reset),
                               tuple(tuple(int(x) for x in a) for a in actions)))
            return True

        monkeypatch.setattr(sm, "_create_service_native", create)
        monkeypatch.setattr(sm, "_change_service_native", change)
        monkeypatch.setattr(sm, "start", start)
        monkeypatch.setattr(sm, "stop", stop)
        monkeypatch.setattr(sm, "remove", remove)
        monkeypatch.setattr(sm, "_apply_failure_actions", failure)
        return self


# ── журнал: запись/очистка/вложенность ─────────────────────────────

def test_journal_written_then_cleared(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sm, "_snapshot_prev_state",
                        lambda root: {"installed": False})
    with sm._service_journal(tmp_path, "install") as journal:
        data = sm.read_service_op_journal(tmp_path)
        assert data is not None
        assert data["state"] == "IN_PROGRESS"
        assert data["action"] == "install"
        assert data["step"] == "begin"
        assert data["prev"] == {"installed": False}
        journal.step("conf")
        assert sm.read_service_op_journal(tmp_path)["step"] == "conf"
    assert sm.read_service_op_journal(tmp_path) is None


def test_journal_kept_on_exception(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sm, "_snapshot_prev_state",
                        lambda root: {"installed": True})
    with pytest.raises(RuntimeError):
        with sm._service_journal(tmp_path, "remove"):
            raise RuntimeError("boom")
    data = sm.read_service_op_journal(tmp_path)
    assert data is not None
    assert data["state"] == "IN_PROGRESS"


def test_nested_operation_does_not_overwrite_journal(tmp_path,
                                                     monkeypatch) -> None:
    monkeypatch.setattr(sm, "_snapshot_prev_state",
                        lambda root: {"installed": False})
    with sm._service_journal(tmp_path, "install"):
        with sm._service_journal(tmp_path, "remove") as inner:
            assert isinstance(inner, sm._NullJournal)
            assert sm.read_service_op_journal(tmp_path)["action"] == "install"
        assert sm.read_service_op_journal(tmp_path)["action"] == "install"
    assert sm.read_service_op_journal(tmp_path) is None


def test_journal_suppressed_while_recovering(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sm, "_recovering", True)
    with sm._service_journal(tmp_path, "install") as journal:
        assert isinstance(journal, sm._NullJournal)
    assert sm.read_service_op_journal(tmp_path) is None


def test_corrupt_journal_ignored(tmp_path) -> None:
    path = sm.service_op_journal_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert sm.read_service_op_journal(tmp_path) is None
    assert sm.recover_service_operation(tmp_path,
                                        log=lambda _m: None) is None


def test_journal_write_leaves_no_tmp_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sm, "_snapshot_prev_state", lambda root: {})
    with sm._service_journal(tmp_path, "start") as journal:
        journal.step("starting")
    assert not (sm.service_op_journal_path(tmp_path).parent
                / (sm.SERVICE_JOURNAL_NAME + sm.JOURNAL_TMP_SUFFIX)).exists()


# ── recovery: откат/дозавершение прерванных операций ────────────────

def test_recover_install_restores_previous_service(tmp_path, monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed = False  # крах после remove старой, до create новой
    conf_path = _conf_path(tmp_path)
    conf_path.write_bytes(b"new-conf")  # установка успела записать новый conf
    _seed(tmp_path, "install", _prev(conf=b"old-conf"), step="old-removed")
    logs: list[str] = []
    result = sm.recover_service_operation(tmp_path, log=logs.append)
    assert result is not None and result[0] is True
    assert ("create", "OLD_NATIVE") in fake.calls
    assert fake.installed and fake.running
    assert conf_path.read_bytes() == b"old-conf"
    assert sm.read_service_op_journal(tmp_path) is None
    assert any("service-recovery" in line for line in logs)


def test_recover_legacy_service_without_conf(tmp_path, monkeypatch) -> None:
    """Pre-0.11 служба (аргументы в binPath, conf нет) - запуск через SCM."""
    fake = FakeService().patch(monkeypatch)
    fake.installed = False
    legacy = (chr(34) + "C:/App/winws2.exe" + chr(34)
              + " --wf-tcp=80 --wf-udp=443")
    _seed(tmp_path, "remove",
          _prev(installed=True, running=True, native=legacy, conf=None),
          step="stopped")
    result = sm.recover_service_operation(tmp_path, log=lambda _m: None)
    assert result is not None and result[0] is True
    assert ("create", legacy) in fake.calls
    assert ("sc", ("start", "zapret2")) in fake.calls
    assert fake.running is True
    assert sm.read_service_op_journal(tmp_path) is None


def test_recover_install_removes_new_service_when_prev_absent(tmp_path,
                                                             monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed = True
    fake.running = False
    _seed(tmp_path, "install", _prev(installed=False, running=False,
                                     native="", conf=None), step="created")
    result = sm.recover_service_operation(tmp_path, log=lambda _m: None)
    assert result is not None and result[0] is True
    assert ("remove",) in fake.calls
    assert not fake.installed


def test_recover_remove_restores_running_service(tmp_path, monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed = True
    fake.running = False
    fake.binpath = "OLD_NATIVE"
    _seed(tmp_path, "remove", _prev(running=True, conf=b"old-conf"),
          step="stopped")
    result = sm.recover_service_operation(tmp_path, log=lambda _m: None)
    assert result is not None and result[0] is True
    assert ("start", None) in fake.calls
    assert fake.running
    assert sm.read_service_op_journal(tmp_path) is None


def test_recover_terminal_step_does_not_rollback(tmp_path, monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed, fake.running, fake.binpath = True, True, "NEW_NATIVE"
    _seed(tmp_path, "install", _prev(conf=b"old-conf"), step="done")
    result = sm.recover_service_operation(tmp_path, log=lambda _m: None)
    assert result is not None and result[0] is True
    assert fake.calls == []
    assert sm.read_service_op_journal(tmp_path) is None


def test_recover_start_starts_stopped_service(tmp_path, monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed = True
    _seed(tmp_path, "start", _prev(running=True), step="stopped")
    result = sm.recover_service_operation(tmp_path, log=lambda _m: None)
    assert result is not None and result[0] is True
    assert fake.running
    assert sm.read_service_op_journal(tmp_path) is None


def test_recover_stop_stops_running_service(tmp_path, monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed, fake.running = True, True
    _seed(tmp_path, "stop", _prev(running=True), step="begin")
    result = sm.recover_service_operation(tmp_path, log=lambda _m: None)
    assert result is not None and result[0] is True
    assert not fake.running
    assert sm.read_service_op_journal(tmp_path) is None


def test_recover_remove_already_deleted_clears_journal(tmp_path,
                                                       monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed = False
    _seed(tmp_path, "remove", _prev(running=True), step="deleted")
    result = sm.recover_service_operation(tmp_path, log=lambda _m: None)
    assert result is not None and result[0] is True
    assert fake.calls == []
    assert sm.read_service_op_journal(tmp_path) is None


def test_recover_orphaned_prev_completes_removal(tmp_path, monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed = True
    _seed(tmp_path, "remove", _prev(conf=None, owner="orphaned"),
          step="deleting")
    result = sm.recover_service_operation(tmp_path, log=lambda _m: None)
    assert result is not None and result[0] is True
    assert ("remove",) in fake.calls
    assert sm.read_service_op_journal(tmp_path) is None


def test_failed_recovery_keeps_journal_with_attempts(tmp_path,
                                                     monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed = True
    fake.running = False
    fake.binpath = "OTHER"
    monkeypatch.setattr(sm, "_change_service_native",
                        lambda native: (False, "denied"))
    _seed(tmp_path, "reconfigure", _prev(native="PREV_NATIVE", conf=b"old"))
    result = sm.recover_service_operation(tmp_path, log=lambda _m: None)
    assert result is not None and result[0] is False
    data = sm.read_service_op_journal(tmp_path)
    assert data is not None
    assert data["state"] == "IN_PROGRESS"
    assert data["attempts"] == 1
    assert "denied" in data["last_error"]


def test_recovery_gives_up_after_three_attempts(tmp_path, monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed = True
    fake.binpath = "OTHER"
    monkeypatch.setattr(sm, "_change_service_native",
                        lambda native: (False, "denied"))
    _seed(tmp_path, "reconfigure", _prev(native="PREV_NATIVE", conf=b"old"))
    for _ in range(3):
        assert sm.recover_service_operation(
            tmp_path, log=lambda _m: None)[0] is False
    data = sm.read_service_op_journal(tmp_path)
    assert data["state"] == "RECOVERY_FAILED"
    assert data["attempts"] == 3
    assert sm.recover_service_operation(tmp_path,
                                        log=lambda _m: None) is None


def test_recovery_not_reentered(tmp_path, monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed = True
    _seed(tmp_path, "start", _prev(running=False), step="stopped")
    monkeypatch.setattr(sm, "_recovering", True)
    assert sm.recover_service_operation(tmp_path,
                                        log=lambda _m: None) is None
    assert sm.read_service_op_journal(tmp_path) is not None


def test_stop_without_service_skips_journal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sm, "app_root", lambda: tmp_path)
    monkeypatch.setattr(sm, "is_installed", lambda: False)
    monkeypatch.setattr(sm, "path_status", lambda: ("none", ""))
    monkeypatch.setattr(sm, "_wait_service_stopped",
                        lambda timeout=5.0: True)
    monkeypatch.setattr(sm, "_taskkill_winws2", lambda: [])
    monkeypatch.setattr(sm, "_sc", lambda args: (0, ""))
    result = sm.stop()
    assert result[0] is True
    assert sm.read_service_op_journal(tmp_path) is None


def test_recover_start_impossible_without_service(tmp_path, monkeypatch) -> None:
    fake = FakeService().patch(monkeypatch)
    fake.installed = False
    _seed(tmp_path, "start", _prev(running=True), step="begin")
    result = sm.recover_service_operation(tmp_path, log=lambda _m: None)
    assert result is not None and result[0] is False
    assert sm.read_service_op_journal(tmp_path)["attempts"] == 1
