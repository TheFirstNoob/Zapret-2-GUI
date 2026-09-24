"""Игровые блокировки: домены (авторизация) + UDP-правила (сессия) по играм.

Данные - ``games.json`` в корне программы (USER-файл, обновления не трогают).
Домены включённых игр собираются в ``lists/list-games.txt`` (рефкаунт: домен
держится, пока нужен хотя бы одной включённой игре) и инжектятся лаунчером.
UDP-правила превращаются в профили winws2 (fake + payload=all - иначе lua не
трогает unknown-UDP - только старт соединения, 1 фейк).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

GAMES_FILE = "games.json"
DOMAIN_LIST = "list-games.txt"      # внутри lists/
CIDR_DIR = "games"                   # внутри lists/games/<id>.txt
DEFAULT_REPEATS = 1
DEFAULT_CUTOFF = 4


def default_games() -> dict:
    """Предзаполненный набор (Wardogs проверен на SkyNet, 2026-09-22)."""
    return {"games": [{
        "id": "wardogs",
        "name": "Wardogs",
        "enabled": True,
        "process": "WardogsClient.exe",
        "domains": [
            {"domain": "live.wardogs.bulkhead.pragmaengine.com",
             "on": True, "warn": False, "tag": "Основной бэкенд",
             "note": "сервер лобби и поиска матча (без него нет сессии)"},
            {"domain": "firstlook.gg", "on": True, "warn": False,
             "tag": "Авторизация",
             "note": "вход в профиль и токен сессии"},
            {"domain": "api.epicgames.dev", "on": True, "warn": True,
             "tag": "Общий сервис",
             "note": "Epic Online Services - нужен всем играм Epic, "
                     "не только этой"},
        ],
        "udp": [{
            "ports": "4192",
            "cidrs": ["54.115.0.0/16", "54.228.0.0/16",
                      "54.216.0.0/16", "3.218.0.0/16"],
            "on": True,
            "repeats": DEFAULT_REPEATS,
            "cutoff": DEFAULT_CUTOFF,
            "tag": "Сетевой бой",
            "note": "fake на старте коннекта, без флуда",
        }],
    }, {
        "id": "valorant",
        "name": "Valorant",
        "enabled": True,
        "process": "VALORANT.exe",
        "domains": [
            {"domain": "valorant.com", "on": True, "warn": False,
             "tag": "Игра и лончер",
             "note": "в реестре РКН - домену нужен обход"},
            {"domain": "playvalorant.com", "on": True, "warn": False,
             "tag": "Лончер", "note": "клиент и обновления"},
            {"domain": "riotgames.com", "on": True, "warn": False,
             "tag": "Аккаунт", "note": "вход в аккаунт Riot"},
            {"domain": "riotcdn.net", "on": True, "warn": False,
             "tag": "CDN", "note": "файлы игры и патчи"},
        ],
        # UDP-фикс пока не подобран (Riot использует UDP 5000-5500) - как с
        # Wardogs: сначала проба через «Анализ приложения», потом правило.
        "udp": [],
    }, {
        "id": "fortnite",
        "name": "Fortnite",
        "enabled": True,
        "process": "FortniteClient-Win64-Shipping.exe",
        "domains": [
            {"domain": "fortnite.com", "on": True, "warn": False,
             "tag": "Игра", "note": "сервисы игры"},
            {"domain": "epicgames.com", "on": True, "warn": False,
             "tag": "Аккаунт", "note": "Epic Games: вход и лончер"},
            {"domain": "epicgames.dev", "on": True, "warn": True,
             "tag": "Общий сервис",
             "note": "Epic Online Services - нужен всем играм Epic"},
            {"domain": "epicgamescdn.com", "on": True, "warn": False,
             "tag": "CDN", "note": "загрузки и патчи"},
        ],
        "udp": [],
    }]}


def _games_path(root: Path) -> Path:
    return Path(root) / GAMES_FILE


def load_games(root: Path) -> dict:
    """Читает games.json; при отсутствии/поломке - дефолт (и создаёт файл)."""
    path = _games_path(root)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("games"), list):
                _backfill_process(data)
                return data
        except (OSError, json.JSONDecodeError):
            pass
    data = default_games()
    save_games(root, data)
    return data


def _backfill_process(data: dict) -> None:
    """Дополняет записи старых games.json полем process из дефолтов."""
    try:
        defaults = {g.get("id"): g for g in default_games().get("games", [])}
        for g in data.get("games", []):
            if not isinstance(g, dict) or "process" in g:
                continue
            src = defaults.get(g.get("id")) or {}
            if src.get("process"):
                g["process"] = src["process"]
    except Exception:
        pass


def save_games(root: Path, data: dict) -> bool:
    """Атомарная запись games.json."""
    path = _games_path(root)
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def enabled_domains(data: dict) -> list[str]:
    """Домены включённых игр (on=true), без дублей - рефкаунт через union."""
    out: list[str] = []
    for game in data.get("games", []):
        if not game.get("enabled"):
            continue
        for item in game.get("domains", []):
            dom = str(item.get("domain") or "").strip().lower()
            if dom and item.get("on") and dom not in out:
                out.append(dom)
    return out


def enabled_udp_rules(data: dict) -> list[dict]:
    """Активные UDP-правила включённых игр (с валидацией портов/CIDR)."""
    out: list[dict] = []
    for game in data.get("games", []):
        if not game.get("enabled"):
            continue
        for rule in game.get("udp", []):
            if not rule.get("on"):
                continue
            ports = str(rule.get("ports") or "").strip()
            cidrs = [str(c).strip() for c in rule.get("cidrs", [])
                     if str(c).strip()]
            if not ports or not cidrs:
                continue
            out.append({
                "id": str(game.get("id") or "game"),
                "game": str(game.get("name") or game.get("id") or ""),
                "ports": ports,
                "cidrs": cidrs,
                "repeats": int(rule.get("repeats") or DEFAULT_REPEATS),
                "cutoff": int(rule.get("cutoff") or DEFAULT_CUTOFF),
            })
    return out


def sync_domain_list(root: Path, data: dict | None = None) -> Path:
    """lists/list-games.txt = домены включённых игр (пустой файл, если нет)."""
    root = Path(root)
    if data is None:
        data = load_games(root)
    path = root / "lists" / DOMAIN_LIST
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(enabled_domains(data))
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")
    return path


def write_cidr_file(root: Path, rule: dict) -> Path:
    """lists/games/<id>.txt - CIDR-файл для --ipset одного UDP-правила."""
    root = Path(root)
    folder = root / "lists" / CIDR_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{rule.get('id') or 'game'}.txt"
    path.write_text("\n".join(rule["cidrs"]) + "\n", encoding="ascii")
    return path


def add_game_domain(root: Path, game_id: str, domain: str) -> tuple[bool, str, bool]:
    """Добавить домен в игру (включённым) - например, из анализа приложения.

    Дубли не добавляются. Возвращает (ok, сообщение, реально добавлено).
    """
    data = load_games(root)
    game = next((g for g in (data.get("games") or [])
                 if str(g.get("id")) == str(game_id)), None)
    if game is None:
        return False, "Игра не найдена", False
    dom = (domain or "").strip().lower().rstrip(".")
    if not dom:
        return False, "Пустой домен", False
    for d in (game.get("domains") or []):
        if str(d.get("domain", "")).strip().lower() == dom:
            return True, "Домен уже в списке игры", False
    game.setdefault("domains", []).append({
        "domain": dom, "on": True, "warn": False, "tag": "",
        "note": "добавлен из анализа приложения"})
    if not save_games(root, data):
        return False, "Не удалось сохранить games.json", False
    try:
        sync_domain_list(root, data)
    except Exception:
        pass
    return True, "Домен добавлен в игру - применяется к новым подключениям", True
