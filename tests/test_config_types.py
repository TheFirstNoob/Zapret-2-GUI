"""T23: типы zapret2_config.json не валят загрузку/старт (аудит T9 №4).

Ручная правка/импорт конфига даёт неверные типы (fake_blob: 5,
discord_voice_mode: 5, game_filter_mode: "botth"); до фикса
build_args_from_preset падал AttributeError, а неизвестный режим GameFilter
тихо расширял окна захвата без профилей. ConfigManager.load теперь приводит
известные поля к типам AppConfig (fail-open на дефолт + запись в
операционный лог), а не падает и не карантинит весь файл.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.config import AppConfig, ConfigManager

ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, data: object) -> ConfigManager:
    (tmp_path / "zapret2_config.json").write_text(
        json.dumps(data), encoding="utf-8")
    return ConfigManager(tmp_path)


def _capture_log(monkeypatch) -> list[str]:
    lines: list[str] = []
    monkeypatch.setattr(
        "core.config._applog",
        lambda section, msg: lines.append(f"{section}: {msg}"))
    return lines


def test_fake_blob_int_falls_back_to_default_with_log(tmp_path, monkeypatch):
    used = _capture_log(monkeypatch)
    cfg = _write(tmp_path, {"fake_blob": 5}).load()
    assert cfg.fake_blob == ""
    assert any("fake_blob" in line for line in used)


def test_fake_blob_list_falls_back_to_default(tmp_path):
    assert _write(tmp_path, {"fake_blob": ["www_google_com"]}).load().fake_blob == ""


def test_fake_blob_null_falls_back_to_default(tmp_path):
    assert _write(tmp_path, {"fake_blob": None}).load().fake_blob == ""


def test_fake_blob_valid_string_kept(tmp_path, monkeypatch):
    used = _capture_log(monkeypatch)
    cfg = _write(tmp_path, {"fake_blob": " www_google_com "}).load()
    assert cfg.fake_blob == "www_google_com"
    assert used == []


def test_game_filter_mode_typo_falls_back_to_off(tmp_path, monkeypatch):
    used = _capture_log(monkeypatch)
    cfg = _write(tmp_path, {"game_filter_mode": "botth"}).load()
    assert cfg.game_filter_mode == "off"
    assert any("game_filter_mode" in line for line in used)


def test_game_filter_mode_int_falls_back_to_off(tmp_path):
    assert _write(tmp_path, {"game_filter_mode": 5}).load().game_filter_mode == "off"


def test_game_filter_mode_case_normalized(tmp_path, monkeypatch):
    used = _capture_log(monkeypatch)
    assert _write(tmp_path, {"game_filter_mode": "TCP"}).load().game_filter_mode == "tcp"
    assert (_write(tmp_path, {"game_filter_mode": " both "}).load().game_filter_mode
            == "both")
    assert used == []


def test_discord_voice_mode_invalid_falls_back_to_legacy(tmp_path, monkeypatch):
    used = _capture_log(monkeypatch)
    cfg = _write(tmp_path, {"discord_voice": True,
                            "discord_voice_mode": 5}).load()
    assert cfg.discord_voice is True
    assert cfg.discord_voice_mode == "fake"
    assert any("discord_voice_mode" in line for line in used)


def test_discord_voice_mode_invalid_without_legacy_bool_is_off(tmp_path):
    cfg = _write(tmp_path, {"discord_voice": False,
                            "discord_voice_mode": "udpln"}).load()
    assert cfg.discord_voice_mode == "off"


def test_discord_voice_mode_valid_kept(tmp_path):
    cfg = _write(tmp_path, {"discord_voice": True,
                            "discord_voice_mode": "udplen"}).load()
    assert cfg.discord_voice_mode == "udplen"


def test_legacy_bool_voice_migration_still_works(tmp_path):
    # Ключа discord_voice_mode нет (старый конфиг) - как и раньше "fake".
    cfg = _write(tmp_path, {"discord_voice": True}).load()
    assert cfg.discord_voice_mode == "fake"


def test_bool_fields_coerced(tmp_path, monkeypatch):
    used = _capture_log(monkeypatch)
    cfg = _write(tmp_path, {
        "discord_voice": "false",
        "winws2_debug": 1,
        "autohostlist": [],
        "ipset_catchall": "yes",
        "discord_alt": 0,
    }).load()
    assert cfg.discord_voice is False
    assert cfg.winws2_debug is True
    assert cfg.autohostlist is False
    assert cfg.ipset_catchall is True
    assert cfg.discord_alt is False
    assert any("autohostlist" in line for line in used)


def test_string_fields_wrong_type_fall_back(tmp_path, monkeypatch):
    used = _capture_log(monkeypatch)
    cfg = _write(tmp_path, {
        "last_profile": 7,
        "zapret1_dir": ["C:/zapret"],
        "dns_main_primary": None,
    }).load()
    assert cfg.last_profile == "default"
    assert cfg.zapret1_dir == ""
    assert cfg.dns_main_primary == "8.8.8.8"
    assert len([line for line in used if "last_profile" in line]) == 1


def test_empty_last_profile_falls_back_to_default(tmp_path):
    assert _write(tmp_path, {"last_profile": "  "}).load().last_profile == "default"


def test_unknown_keys_still_dropped(tmp_path):
    cfg = _write(tmp_path, {"last_profile": "auto",
                            "old_gui_option": "x"}).load()
    assert cfg.last_profile == "auto"
    assert not hasattr(cfg, "old_gui_option")


def test_valid_config_roundtrip_has_no_warnings(tmp_path, monkeypatch):
    used = _capture_log(monkeypatch)
    data = {
        "root_dir": str(tmp_path),
        "last_profile": "auto",
        "game_filter_mode": "both",
        "discord_voice": True,
        "discord_voice_mode": "udplen",
        "fake_blob": "www_google_com",
        "winws2_debug": False,
        "autohostlist": True,
        "ipset_catchall": False,
        "discord_alt": True,
        "tour_done": True,
        "notice_done": False,
        "dns_main_primary": "9.9.9.9",
        "dns_main_secondary": "149.112.112.112",
        "dns_reserve_primary": "1.1.1.1",
        "dns_reserve_secondary": "1.0.0.1",
    }
    cfg = _write(tmp_path, data).load()
    for key, value in data.items():
        assert getattr(cfg, key) == value, key
    assert used == []


def test_save_normalizes_and_writes_clean_json(tmp_path):
    cm = ConfigManager(tmp_path)
    bad = AppConfig(root_dir=str(tmp_path), fake_blob=5,
                    game_filter_mode="BOTH")  # type: ignore[arg-type]
    assert cm.save(bad) is True
    raw = json.loads((tmp_path / "zapret2_config.json").read_text(encoding="utf-8"))
    assert raw["fake_blob"] == ""
    assert raw["game_filter_mode"] == "both"
    # Кэш менеджера - уже нормализованный объект.
    assert cm.load().fake_blob == ""


def test_bad_json_root_still_quarantined(tmp_path):
    path = tmp_path / "zapret2_config.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    cfg = ConfigManager(tmp_path).load()
    assert isinstance(cfg, AppConfig)
    assert path.with_suffix(".json.bad").exists()


def test_build_args_survives_bad_config_types(tmp_path):
    """Реальный путь отказа из аудита: битый конфиг -> старт/диагностика."""
    from core.launcher import build_args_from_preset

    cm = _write(tmp_path, {"fake_blob": 5,
                           "discord_voice": True,
                           "discord_voice_mode": 5,
                           "game_filter_mode": 5})
    cfg = cm.load()
    root = tmp_path / "root"
    (root / "lists").mkdir(parents=True)
    (root / "games.json").write_text('{"games": []}', encoding="utf-8")
    args = build_args_from_preset(
        root, ROOT / "lua", ROOT / "blobs", ROOT / "presets" / "default.txt",
        lists_dir=root / "lists", windivert_dir=ROOT / "windivert",
        game_filter_mode=cfg.game_filter_mode,
        discord_voice=cfg.discord_voice,
        discord_voice_mode=cfg.discord_voice_mode,
        fake_blob=cfg.fake_blob)
    assert args and isinstance(args[0], str)
