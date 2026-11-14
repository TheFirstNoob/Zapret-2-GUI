"""T21: сериализация load->save games.json (аудит 2026-11-14).

Без живого HTTP: проверяем модульный games_lock/mutate_games напрямую.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from core import games


def _games_on_disk(root: Path) -> dict:
    return json.loads((root / "games.json").read_text(encoding="utf-8"))


def _new_game(name: str) -> dict:
    return {"id": f"custom-{name}", "name": name, "custom": True,
            "enabled": True, "domains": [], "udp": []}


def test_games_lock_is_reentrant() -> None:
    with games.games_lock():
        with games.games_lock():
            pass  # вложенный вход не должен блокироваться (RLock)


def test_concurrent_mutations_keep_both_edits(tmp_path: Path,
                                              monkeypatch) -> None:
    orig_load = games.load_games

    def slow_load(root):
        data = orig_load(root)
        # «Медленное чтение»: без лока оба потока успевают прочитать один и
        # тот же снимок и последний save затирает чужую правку.
        time.sleep(0.03)
        return data

    monkeypatch.setattr(games, "load_games", slow_load)
    results: list[tuple[bool, str, dict]] = []

    def add(name: str) -> None:
        def mutate(data: dict):
            data.setdefault("games", []).append(_new_game(name))
            return True, "", data
        results.append(games.mutate_games(tmp_path, mutate))

    threads = [threading.Thread(target=add, args=(name,))
               for name in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert all(ok for ok, _msg, _data in results)
    ids = {g["id"] for g in _games_on_disk(tmp_path)["games"]}
    assert {"custom-A", "custom-B"} <= ids


def test_mutator_rejection_does_not_write(tmp_path: Path) -> None:
    games.save_games(tmp_path, games.default_games())
    before = (tmp_path / "games.json").read_text(encoding="utf-8")
    ok, message, _data = games.mutate_games(
        tmp_path, lambda data: (False, "нельзя", data))
    assert ok is False
    assert message == "нельзя"
    assert (tmp_path / "games.json").read_text(encoding="utf-8") == before


def test_mutate_games_validates_payload(tmp_path: Path) -> None:
    games.save_games(tmp_path, games.default_games())
    before = (tmp_path / "games.json").read_text(encoding="utf-8")

    def mutate(data: dict):
        data["games"] = [{"id": "custom-x", "udp": [
            {"ports": "443\n--new", "on": True}]}]
        return True, "", data

    ok, message, _data = games.mutate_games(tmp_path, mutate)
    assert ok is False
    assert "порт" in message.lower() or "UDP" in message
    # Невалидные данные не должны попасть в user-файл.
    assert (tmp_path / "games.json").read_text(encoding="utf-8") == before


def test_add_game_domain_uses_lock_and_syncs(tmp_path: Path) -> None:
    assert games.save_games(tmp_path, games.default_games())
    ok, message, added = games.add_game_domain(
        tmp_path, "wardogs", "NEW.Example.COM")
    assert ok is True and added is True
    assert "Домен добавлен" in message
    data = _games_on_disk(tmp_path)
    wardogs = next(g for g in data["games"] if g["id"] == "wardogs")
    assert any(d["domain"] == "new.example.com" for d in wardogs["domains"])
    # combined-файл обновился
    include_all = (tmp_path / "lists" / "list-include-all.txt").read_text(
        encoding="utf-8")
    assert "new.example.com" in include_all

    # Повторное добавление - без дублей и без записи.
    ok, message, added = games.add_game_domain(
        tmp_path, "wardogs", "new.example.com")
    assert ok is True and added is False
    assert "уже" in message


def test_add_game_domain_unknown_game(tmp_path: Path) -> None:
    ok, message, added = games.add_game_domain(tmp_path, "no-such", "x.example")
    assert (ok, added) == (False, False)
    assert "не найдена" in message


def test_games_store_in_path_with_spaces_and_cyrillic(tmp_path: Path) -> None:
    # Совместимость: путь с пробелами и кириллицей (кириллица в пути
    # установки - штатный кейс пользователя).
    root = tmp_path / "Zapret 2 копия" / "программы"
    root.mkdir(parents=True)
    assert games.save_games(root, games.default_games())
    ok, _message, added = games.add_game_domain(
        root, "wardogs", "x.example.org")
    assert ok is True and added is True
    assert games.load_games(root)["games"]
    include_all = root / "lists" / "list-include-all.txt"
    assert include_all.exists()
    assert "x.example.org" in include_all.read_text(encoding="utf-8")
