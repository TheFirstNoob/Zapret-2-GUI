"""Preflight установки службы: WinDivert-файлы и подготовка окружения.

Кейс 2026-11-15: у пользователя установка падала с
«winws2 --intercept=0 rc=3: windivert: error opening filter: the system cannot
find the path specified». Причины - битая/старая служба WinDivert или
отсутствующий .sys (антивирус); установка должна лечить окружение до
preflight и давать понятную ошибку, а не сырой вывод движка.
"""
from pathlib import Path
from types import SimpleNamespace

import server.api_service as api


class _Cfg:
    last_profile = "default"
    game_filter_mode = "off"
    discord_voice_mode = ""
    discord_voice = False
    winws2_debug = False
    autohostlist = False
    ipset_catchall = False
    fake_blob = ""
    discord_alt = False


class _CM:
    def load(self):
        return _Cfg()


class _Ctr:
    def __init__(self, exe: Path):
        self.winws2_path = exe


def _setup(tmp_path, monkeypatch):
    exe_dir = tmp_path / "bin"
    exe_dir.mkdir()
    exe = exe_dir / "winws2.exe"
    exe.write_text("", encoding="utf-8")
    (exe_dir / "cygwin1.dll").write_text("", encoding="utf-8")
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "default.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr(api, "get_config_manager", lambda: _CM())
    monkeypatch.setattr(api, "get_controller", lambda: _Ctr(exe))
    monkeypatch.setattr(api, "get_root_dir", lambda: tmp_path)
    monkeypatch.setattr(api, "build_args_from_preset", lambda *a, **k: ["--x"])
    return exe


def test_missing_windivert_sys_is_actionable(tmp_path, monkeypatch):
    exe = _setup(tmp_path, monkeypatch)
    (exe.parent / "WinDivert.dll").write_text("", encoding="utf-8")
    called = []
    monkeypatch.setattr(api, "prepare_engine_environment", lambda root: called.append(root))
    monkeypatch.setattr(api, "validate_args", lambda *a, **k: (True, ""))
    args, err = api.prepare_service_args({})
    assert args is None
    assert "WinDivert64.sys" in err
    assert "антивирус" in err.lower()
    assert called == []


def test_engine_env_prepared_before_validate(tmp_path, monkeypatch):
    exe = _setup(tmp_path, monkeypatch)
    for name in ("WinDivert.dll", "WinDivert64.sys"):
        (exe.parent / name).write_text("", encoding="utf-8")
    called = []
    monkeypatch.setattr(api, "prepare_engine_environment", lambda root: called.append(root))
    seen = {}
    def _fake_validate(*a, **k):
        seen.update(k)
        return True, ""
    monkeypatch.setattr(api, "validate_args", _fake_validate)
    args, err = api.prepare_service_args({})
    assert err == ""
    assert args == ["--x"]
    assert called == [tmp_path]
    assert seen.get("check_lua") is not False
