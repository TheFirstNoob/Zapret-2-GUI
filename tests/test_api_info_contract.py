"""T19/T12: контракт /api/status не изменился при ускорении ProcessProbe/proc."""
from __future__ import annotations

from core.zapret_controller import ZapretStatus
from server import api_info


class _Controller:
    def status(self) -> ZapretStatus:
        return ZapretStatus(running=True, pid=4242, strategy="default")


def test_status_contract_fields(monkeypatch) -> None:
    monkeypatch.setattr(api_info, "get_controller", lambda: _Controller())
    monkeypatch.setattr(api_info, "scan_winws_exe",
                        lambda: {"running": False, "pid": 0})
    monkeypatch.setattr(api_info, "ui_presets", lambda: ["default", "auto"])
    monkeypatch.setattr(api_info, "zapret1_installed", lambda: False)
    out = api_info.status(None)
    assert out == {
        "status": "ok",
        "zapret": {"running": True, "pid": 4242, "strategy": "default"},
        "zapret1": {"running": False, "pid": 0, "installed": False},
        "profiles": ["default", "auto"],
    }


def test_status_offline_shape_preserved(monkeypatch) -> None:
    class _Idle:
        def status(self) -> ZapretStatus:
            return ZapretStatus()

    monkeypatch.setattr(api_info, "get_controller", lambda: _Idle())
    monkeypatch.setattr(api_info, "scan_winws_exe",
                        lambda: {"running": False, "pid": 0})
    monkeypatch.setattr(api_info, "ui_presets", lambda: [])
    monkeypatch.setattr(api_info, "zapret1_installed", lambda: True)
    out = api_info.status(None)
    assert out["zapret"] == {"running": False, "pid": None, "strategy": None}
    assert out["zapret1"] == {"running": False, "pid": 0, "installed": True}


def test_version_and_profiles(monkeypatch) -> None:
    from core.config import VERSION
    assert api_info.version(None) == {"status": "ok", "version": VERSION}
    monkeypatch.setattr(api_info, "ui_presets", lambda: ["a"])
    assert api_info.list_profiles(None)["profiles"] == [
        {"name": "a", "display_name": "a", "description": "",
         "is_valid": True, "parse_error": "", "warnings": []}]
