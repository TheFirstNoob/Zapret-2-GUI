"""ProcessProbe должен показывать РЕАЛЬНЫЙ exe, а не ввод пользователя."""
from core import process_probe as pp


def test_describe_pids_returns_real_image(monkeypatch):
    monkeypatch.setattr("core.proc.process_image_path",
                        lambda pid: r"C:\Games\Rob Run\RobRun.exe")
    out = pp._describe_pids([123, 123, 456])
    assert [x["pid"] for x in out] == [123, 456]
    assert out[0]["image"] == "RobRun.exe"
    assert out[0]["path"].endswith("RobRun.exe")


def test_report_includes_resolved_image(monkeypatch):
    monkeypatch.setattr("core.proc.process_image_path",
                        lambda pid: r"C:\Games\Rob Run\RobRun.exe")
    p = pp.ProcessProbe()
    p._state = {
        "process": "ROB RUN",
        "resolved": pp._describe_pids([123]),
        "phase": "наблюдение", "elapsed": 10, "ipv6": False,
        "history": {}, "pids_count": 1,
    }
    text = p.report_text()
    assert "Анализ процесса: ROB RUN" in text
    assert "RobRun.exe" in text
    assert "PID 123" in text
