"""ProcessProbe: пробелы/регистр/.exe в имени процесса."""
from core import process_probe as pp


def test_exe_suffix_is_stripped_for_processname_match(monkeypatch):
    calls = []
    monkeypatch.setattr(pp, "_ps_json", lambda script: calls.append(script) or [])
    assert pp.ProcessProbe()._find_pids("Rob run.exe") == []
    assert calls and "*Rob run*" in calls[0]
    assert "Rob run.exe*" not in calls[0]


def test_spaces_and_case_are_supported(monkeypatch):
    calls = []
    monkeypatch.setattr(pp, "_ps_json", lambda script: calls.append(script) or [])
    assert pp.ProcessProbe()._find_pids("rob RUN") == []
    assert calls and "*rob RUN*" in calls[0]


def test_rescan_script_also_strips_exe():
    script = pp._rescan_script([1], "Rob run.exe")
    assert script is not None
    assert "*Rob run*" in script
    assert "Rob run.exe*" not in script
