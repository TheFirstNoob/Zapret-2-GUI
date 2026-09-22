"""Игровые блокировки: домены (авторизация) + UDP-правила (сессия) по играм.

Данные — ``games.json`` в корне программы (USER-файл, обновления не трогают).
Домены включённых игр собираются в ``lists/list-games.txt`` (рефкаунт: домен
держится, пока нужен хотя бы одной включённой игре) и инжектятся лаунчером.
UDP-правила превращаются в профили winws2 (fake + payload=all — иначе lua не
трогает unknown-UDP — только старт соединения, 1 фейк).
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
        "domains": [
            {"domain": "live.wardogs.bulkhead.pragmaengine.com",
             "on": True, "note": ""},
            {"domain": "firstlook.gg", "on": True, "note": ""},
            {"domain": "api.epicgames.dev", "on": True,
             "note": "общий домен Epic (нужен всем их играм)"},
        ],
        "udp": [{
            "ports": "4192",
            "cidrs": ["54.115.0.0/16", "54.228.0.0/16",
                      "54.216.0.0/16", "3.218.0.0/16"],
            "on": True,
            "repeats": DEFAULT_REPEATS,
            "cutoff": DEFAULT_CUTOFF,
        }],
    }]}


def _games_path(root: Path) -> Path:
    return Path(root) / GAMES_FILE


def load_games(root: Path) -> dict:
    """Читает games.json; при отсутствии/поломке — дефолт (и создаёт файл)."""
    path = _games_path(root)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("games"), list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    data = default_games()
    save_games(root, data)
    return data


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
    """Домены включённых игр (on=true), без дублей — рефкаунт через union."""
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
    """lists/games/<id>.txt — CIDR-файл для --ipset одного UDP-правила."""
    root = Path(root)
    folder = root / "lists" / CIDR_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{rule.get('id') or 'game'}.txt"
    path.write_text("\n".join(rule["cidrs"]) + "\n", encoding="ascii")
    return path
