"""Task Scheduler helper: XML/пути без установки реальной задачи."""
from pathlib import Path

from core import discord_fix_task as t


def test_action_uses_current_interpreter_and_helper_arg(tmp_path):
    exe, args = t.action(tmp_path)
    assert exe
    assert "--discord-fix-helper" in args
    assert "main.py" in args


def test_xml_has_system_boot_trigger_and_escaped_paths(tmp_path):
    xml = t._xml(tmp_path)
    assert "S-1-5-18" in xml
    assert "BootTrigger" in xml
    assert "--discord-fix-helper" in xml
    assert "\x00" not in xml  # обычная строка, не UTF-16 внутри


def test_install_remove_via_schtasks(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(t, "_run", lambda args, timeout=25.0: (calls.append(args) or (0, "")))
    ok, msg = t.install(tmp_path)
    assert ok, msg
    assert calls and "/Create" in calls[0] and "/XML" in calls[0]
    monkeypatch.setattr(t, "installed", lambda: True)
    ok, msg = t.remove()
    assert ok, msg
    assert any("/Delete" in c for c in calls)


def test_installed_false_on_query_error(monkeypatch):
    monkeypatch.setattr(t, "_run", lambda args, timeout=25.0: (1, ""))
    assert t.installed() is False
