"""Direct-start должен готовить WinDivert до preflight --intercept=0.

P1 2026-11-15: на машине с битой/чужой службой WinDivert кнопка «Запустить»
(без службы) падала на validate_args до launch, хотя launch умеет чинить
драйвер. Порядок: prepare_engine_environment -> validate_args -> launch.
"""
from pathlib import Path

import core.zapret_controller as zc


def test_start_prepares_engine_before_validation(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "default.txt").write_text("", encoding="utf-8")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "winws2.exe").write_text("", encoding="utf-8")
    calls = []
    monkeypatch.setattr(zc, "prepare_engine_environment",
                        lambda root: calls.append("env"))
    monkeypatch.setattr(zc, "validate_args",
                        lambda *a, **k: (calls.append("validate"), (False, "stop"))[1])
    ctrl = zc.ZapretController(tmp_path)
    ok, err = ctrl.start("default")
    assert not ok and "stop" in err
    assert calls == ["env", "validate"]
