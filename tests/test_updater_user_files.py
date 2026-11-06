from __future__ import annotations

from core.updater import is_user_file


def test_generated_game_lists_are_user_files() -> None:
    assert is_user_file("lists/list-games.txt")
    assert is_user_file("lists/list-include-all.txt")


def test_user_lists_and_config_are_protected() -> None:
    assert is_user_file("lists/list-include-user.txt")
    assert is_user_file("lists/list-exclude-user.txt")
    assert is_user_file("lists/ipset-include-user.txt")
    assert is_user_file("zapret2_config.json")
    assert is_user_file("games.json")


def test_release_preset_is_not_user_file() -> None:
    assert not is_user_file("presets/default.txt")
    assert is_user_file("presets/custom.txt")
