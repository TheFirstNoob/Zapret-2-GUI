"""Tests for core.launcher.validate_args fail-closed behaviour."""
from pathlib import Path

from core import launcher


class _R:
    def __init__(self, rc, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _patch(monkeypatch, tmp_path, res):
    exe = tmp_path / "winws2.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: res)
    monkeypatch.setattr(launcher, "validate_lua", lambda *a, **k: (True, ""))
    return exe


def test_fails_on_nonzero_rc(monkeypatch, tmp_path):
    exe = _patch(monkeypatch, tmp_path, _R(1, "", "failed to register hostlist"))
    ok, err = launcher.validate_args(exe, ["--wf-tcp-out", "80"])
    assert not ok
    assert "rc=1" in err or "failed to register hostlist" in err.lower()


def test_accepts_zero_rc(monkeypatch, tmp_path):
    exe = _patch(monkeypatch, tmp_path, _R(0, "github version v1.0.7" + chr(10), ""))
    ok, err = launcher.validate_args(exe, ["--wf-tcp-out", "80"])
    assert ok and err == ""


def test_allows_already_running(monkeypatch, tmp_path):
    exe = _patch(monkeypatch, tmp_path, _R(1, "already running with the same filter", ""))
    ok, _ = launcher.validate_args(exe, ["--wf-tcp-out", "80"])
    assert ok


def test_windivert_environment_rc_is_not_lua_failure(monkeypatch, tmp_path):
    # 0.10 tolerated rc from --intercept=0; 0.11 fail-closed made it fatal,
    # though the error is WinDivert environment, not bad Lua (incident 2026-11-15).
    res = _R(3, "", "windivert: error opening filter: "
                        "The system cannot find the path specified.")
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: res)
    exe = tmp_path / "winws2.exe"
    exe.write_text("", encoding="utf-8")
    ok, err = launcher.validate_lua(exe, ["--lua-init=@lua/x.lua"])
    assert ok and err == ""


def test_validate_args_can_skip_lua_preflight(monkeypatch, tmp_path):
    res = _R(0, "github version v1.0.7" + chr(10), "")
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: res)
    called = []
    monkeypatch.setattr(launcher, "validate_lua", lambda *a, **k: called.append(1))
    exe = tmp_path / "winws2.exe"
    exe.write_text("", encoding="utf-8")
    ok, err = launcher.validate_args(exe, ["--wf-tcp-out", "80"], check_lua=False)
    assert ok and err == ""
    assert called == []
