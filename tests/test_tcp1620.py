"""TCP16-20: порог 12 КБ и порядок OK-правил (аудит T16, P1)."""
import subprocess
from pathlib import Path

from core import tester_probes


class _R:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def _run(monkeypatch, stdout: str, rc: int = 0):
    monkeypatch.setattr(tester_probes.subprocess, "run",
                        lambda *a, **k: _R(stdout, rc))
    return tester_probes.tcp1620_test_curl("example.com", Path("body.bin"), 6.0)


def test_break_at_20kb_is_stateful_dpi(monkeypatch):
    r = _run(monkeypatch, "0 20480")
    assert r.status == "TCP16_20" and "20" in (r.error or "")


def test_small_upload_is_timeout_not_dpi(monkeypatch):
    r = _run(monkeypatch, "0 5000")
    assert r.status == "TIMEOUT"


def test_full_upload_ok_without_code(monkeypatch):
    r = _run(monkeypatch, "0 65536")
    assert r.status == "OK"


def test_early_http_response_is_ok(monkeypatch):
    r = _run(monkeypatch, "200 5000")
    assert r.status == "OK"
