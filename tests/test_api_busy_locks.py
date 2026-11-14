"""T21/T12: mutating-ручки списков/конфига/игр -> HTTP 409 во время проверки.

Unit-тесты без живого тестера/службы/сети: busy-мок (checkers_busy) и файлы
в tmp_path. Проверяем и обратное: вне проверки законные сохранения работают.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.config import ConfigManager
from server import api_config, api_games, api_lists, app_state
from server.api_common import ApiError

BUSY = "Тестер занят - завершите текущую проверку"


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(app_state.STATE, "root_dir", tmp_path)
    monkeypatch.setattr(app_state.STATE, "config_manager",
                        ConfigManager(tmp_path))
    return tmp_path


@pytest.fixture
def busy(monkeypatch) -> str:
    for module in (api_lists, api_config, api_games):
        monkeypatch.setattr(module, "checkers_busy", lambda: BUSY)
    return BUSY


@pytest.fixture
def free(monkeypatch) -> None:
    for module in (api_lists, api_config, api_games):
        monkeypatch.setattr(module, "checkers_busy", lambda: None)


def _assert_409(exc: ApiError) -> None:
    assert exc.status == 409
    assert exc.payload["status"] == "error"
    assert exc.payload["message"] == BUSY


# ── списки ────────────────────────────────────────────────────────────────

def test_list_save_blocked_while_checking(root: Path, busy: str) -> None:
    with pytest.raises(ApiError) as exc_info:
        api_lists.save_list(app_state.STATE, {"content": "example.com\n"},
                            "list-include-user.txt")
    _assert_409(exc_info.value)
    assert not (root / "lists" / "list-include-user.txt").exists()


def test_lists_dedupe_blocked_while_checking(root: Path, busy: str) -> None:
    with pytest.raises(ApiError):
        api_lists.lists_dedupe(app_state.STATE)


def test_list_add_domain_blocked_while_checking(root: Path, busy: str) -> None:
    with pytest.raises(ApiError):
        api_lists.lists_add_domain(app_state.STATE, {"domain": "x.example"})
    assert not (root / "lists" / "list-include-user.txt").exists()


def test_list_save_works_when_free(root: Path, free: None) -> None:
    result = api_lists.save_list(app_state.STATE, {"content": "example.com\n"},
                                 "list-include-user.txt")
    assert result["status"] == "ok"
    assert (root / "lists" / "list-include-user.txt").read_text(
        encoding="utf-8") == "example.com"


# ── конфиг ────────────────────────────────────────────────────────────────

def test_config_save_blocked_while_checking(root: Path, busy: str) -> None:
    with pytest.raises(ApiError) as exc_info:
        api_config.save_config(app_state.STATE, {"tour_done": True})
    _assert_409(exc_info.value)
    assert not (root / "zapret2_config.json").exists()


def test_settings_import_blocked_while_checking(root: Path, busy: str) -> None:
    with pytest.raises(ApiError):
        api_config.settings_import(app_state.STATE, {"data": ""})
    # Импорт не успел ничего распаковать.
    assert not (root / "zapret2_config.json").exists()


def test_config_save_works_when_free(root: Path, free: None) -> None:
    result = api_config.save_config(app_state.STATE, {"tour_done": True})
    assert result["status"] == "ok"
    assert (root / "zapret2_config.json").exists()


# ── игры ──────────────────────────────────────────────────────────────────

def _games_payload() -> dict:
    return {"games": {"games": [{
        "id": "custom-1", "name": "X", "custom": True, "enabled": True,
        "domains": [], "udp": []}]}}


def test_games_save_blocked_while_checking(root: Path, busy: str) -> None:
    with pytest.raises(ApiError) as exc_info:
        api_games.games_save(app_state.STATE, _games_payload())
    _assert_409(exc_info.value)
    assert not (root / "games.json").exists()


def test_games_custom_blocked_while_checking(root: Path, busy: str) -> None:
    with pytest.raises(ApiError):
        api_games.games_custom(app_state.STATE,
                               {"game": {"name": "My Game"}})
    assert not (root / "games.json").exists()


def test_games_add_domain_blocked_while_checking(root: Path, busy: str) -> None:
    with pytest.raises(ApiError):
        api_games.games_add_domain(
            app_state.STATE, {"game_id": "wardogs", "domain": "x.example"})
    assert not (root / "games.json").exists()


def test_games_custom_works_when_free(root: Path, free: None) -> None:
    result = api_games.games_custom(app_state.STATE, {"game": {
        "name": "My Game", "domains_text": "a.example",
        "ports": "7777", "cidrs_text": "10.0.0.0/24"}})
    assert result["status"] == "ok"
    assert (root / "games.json").exists()


def test_games_save_works_when_free(root: Path, free: None) -> None:
    result = api_games.games_save(app_state.STATE, _games_payload())
    assert result["status"] == "ok"
    import json
    data = json.loads((root / "games.json").read_text(encoding="utf-8"))
    assert any(g["id"] == "custom-1" for g in data["games"])
