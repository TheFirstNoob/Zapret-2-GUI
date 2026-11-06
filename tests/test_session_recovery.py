from __future__ import annotations

from pathlib import Path

from server import session_recovery


def _write(path: Path, started: str = "2026-10-27T12:00:00") -> None:
    session_recovery._write(path, {
        "state": "TESTING",
        "action": "test_profiles",
        "started": started,
        "protection": {"z2": True, "z1": False, "svc": True},
        "recovery": None,
    })


def test_failed_recovery_keeps_testing_journal(tmp_path: Path) -> None:
    _write(tmp_path)
    ok, summary = session_recovery.recover_unfinished_session(
        tmp_path,
        restore_recovery=lambda _snapshot: True,
        restore_protection=lambda _z2, _z1, _svc: (False, "не удалось"),
        log=lambda _line: None,
    )
    assert ok is False
    assert "не удалось" in summary
    journal = session_recovery.read_session_journal(tmp_path)
    assert journal is not None
    assert journal["state"] == "TESTING"


def test_successful_recovery_marks_recovered(tmp_path: Path) -> None:
    _write(tmp_path)
    ok, _summary = session_recovery.recover_unfinished_session(
        tmp_path,
        restore_recovery=lambda _snapshot: True,
        restore_protection=lambda _z2, _z1, _svc: (True, "восстановлено"),
        log=lambda _line: None,
    )
    assert ok is True
    journal = session_recovery.read_session_journal(tmp_path)
    assert journal is not None
    assert journal["state"] == "RECOVERED"


def test_no_journal_returns_none(tmp_path: Path) -> None:
    called = False

    def _restore(_snapshot):
        nonlocal called
        called = True
        return True

    assert session_recovery.recover_unfinished_session(
        tmp_path,
        restore_recovery=_restore,
        restore_protection=lambda _z2, _z1, _svc: (True, ""),
        log=lambda _line: None,
    ) is None
    assert called is False


def test_changed_journal_is_not_marked_recovered(tmp_path: Path) -> None:
    _write(tmp_path, started="first")

    def _protection(_z2, _z1, _svc):
        _write(tmp_path, started="second")
        return True, "восстановлено"

    ok, _summary = session_recovery.recover_unfinished_session(
        tmp_path,
        restore_recovery=lambda _snapshot: True,
        restore_protection=_protection,
        log=lambda _line: None,
    )
    assert ok is False
    journal = session_recovery.read_session_journal(tmp_path)
    assert journal is not None
    assert journal["state"] == "TESTING"
    assert journal["started"] == "second"
