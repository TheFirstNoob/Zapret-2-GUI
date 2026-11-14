"""tools.sync_dpi_detector: дифф/запись данных без сети (monkeypatch)."""
from pathlib import Path

from tools import sync_dpi_detector as s


def _pin(tmp_path: Path, monkeypatch, data: dict):
    (tmp_path / "lists").mkdir()
    for rel, payload in data.items():
        (tmp_path / rel).write_bytes(payload)
    monkeypatch.setattr(s, "ROOT", tmp_path)
    by_upstream = {s.FILES[rel][0]: payload for rel, payload in data.items()}
    monkeypatch.setattr(s, "_fetch_all",
                        lambda name, timeout=20.0: [("jsdelivr", by_upstream[name])])


def test_identical_is_zero(tmp_path: Path, monkeypatch):
    probes = b'[{"id":"A","asn":"1","provider":"P","ip":"1.1.1.1","port":443}]'
    wl = b"example.com\n"
    _pin(tmp_path, monkeypatch, {"lists/cdn-asn-probes.json": probes,
                                  "lists/whitelist-sni.txt": wl})
    assert s.check(apply=False) == 0


def test_apply_updates_diff(tmp_path: Path, monkeypatch):
    old = b'[{"id":"A","asn":"1","provider":"P","ip":"1.1.1.1","port":443}]'
    new = b'[{"id":"A","asn":"1","provider":"P","ip":"1.1.1.1","port":443},{"id":"B","asn":"2","provider":"Q","ip":"2.2.2.2","port":80}]'
    _pin(tmp_path, monkeypatch, {"lists/cdn-asn-probes.json": old,
                                  "lists/whitelist-sni.txt": b"example.com\n"})
    # подменяем upstream после пиннинга
    monkeypatch.setattr(s, "_fetch_all", lambda name, timeout=20.0: [
        ("jsdelivr", new if name == "tcp16.json" else b"example.com\n")])
    assert s.check(apply=True) == 1
    assert (tmp_path / "lists/cdn-asn-probes.json").read_bytes() == new


def test_source_mismatch_warns(tmp_path: Path, monkeypatch, capsys):
    probes = b'[{"id":"A","asn":"1","provider":"P","ip":"1.1.1.1","port":443}]'
    _pin(tmp_path, monkeypatch, {"lists/cdn-asn-probes.json": probes,
                                  "lists/whitelist-sni.txt": b"example.com\n"})
    monkeypatch.setattr(s, "_fetch_all", lambda name, timeout=20.0: [
        ("jsdelivr", probes if name == "tcp16.json" else b"example.com\n"),
        ("raw", probes + b"\n" if name == "tcp16.json" else b"example.com\n")])
    s.check(apply=False)
    out = capsys.readouterr().out
    assert "WARN" in out
