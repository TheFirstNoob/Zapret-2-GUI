from __future__ import annotations

from types import SimpleNamespace

from core import proc


def test_kill_image_uses_taskkill_exit_code(monkeypatch) -> None:
    monkeypatch.setattr(proc.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1))
    assert proc.kill_image("winws2.exe") is False

    monkeypatch.setattr(proc.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0))
    assert proc.kill_image("winws2.exe") is True


def test_kill_pid_uses_taskkill_exit_code(monkeypatch) -> None:
    monkeypatch.setattr(proc.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=128))
    assert proc.kill_pid(42) is False
