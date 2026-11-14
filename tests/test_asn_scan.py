"""ASN-скан: HTTP-пробы (port=80) должны идти по http, не по https (P1)."""
import json, threading, time
from pathlib import Path

from core import tester


class _R:
    def __init__(self, out="200 32768 0.1", err="", rc=0):
        self.stdout = out
        self.stderr = err
        self.returncode = rc


def test_asn_http_probe_uses_port_and_scheme(tmp_path: Path, monkeypatch):
    root = tmp_path
    (root / "lists").mkdir()
    (root / "lists" / "cdn-asn-probes.json").write_text(json.dumps([
        {"id": "H-01", "asn": "1", "provider": "Test HTTP",
         "ip": "1.2.3.4", "port": 80},
    ]), encoding="utf-8")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _R()

    import core.tester as tmod
    monkeypatch.setattr(tmod.subprocess, "run", fake_run)
    t = tester.Zapret2Tester.__new__(tester.Zapret2Tester)
    t.root_dir = root
    t.shutdown_event = threading.Event()
    out = t.asn_scan(lambda p, m: None)
    cmd = captured["cmd"]
    assert "--resolve" in cmd
    assert "example.com:80:1.2.3.4" in cmd
    assert "http://example.com/" in cmd
    assert out and out[0]["status"] == "OK"
