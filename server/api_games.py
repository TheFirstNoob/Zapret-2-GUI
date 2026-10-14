"""api_games.py - хендлеры домена «игровые блокировки» (аудит #1, Inc C).

Соглашение: (ctx: AppContext, ...) -> dict; исключения - только ApiError."""
from __future__ import annotations

import time

from core import games as games_store
from server.app_state import AppContext, get_root_dir


def games_get(ctx: AppContext) -> dict:
    return {"status": "ok", "games": games_store.load_games(get_root_dir())}


def games_save(ctx: AppContext, data: dict) -> dict:
    """Сохранение игровых блокировок: домены применяются сразу (hot-reload
    hostlist), UDP-профили - при следующем запуске/переустановке службы."""
    payload = data.get("games") if isinstance(data, dict) else None
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
        return {"status": "error", "message": "некорректные данные"}
    if not games_store.save_games(get_root_dir(), payload):
        return {"status": "error", "message": "не удалось сохранить"}
    games_store.sync_include_list(get_root_dir(), data=payload)
    return {
        "status": "ok",
        "message": "Сохранено. Домены применятся к новым подключениям; "
                   "UDP-фикс - после перезапуска обхода (службу - "
                   "переустановкой)"}


def games_custom(ctx: AppContext, data: dict) -> dict:
    """Своя игра: add/update/delete. Встроенные игры не редактируются."""
    action = str(data.get("action") or "save")
    cur = games_store.load_games(get_root_dir())
    if action == "delete":
        ok, msg, cur = games_store.delete_custom_game(
            cur, str(data.get("id") or ""))
    else:
        game = data.get("game") if isinstance(data.get("game"), dict) else {}
        ok, msg, cur = games_store.upsert_custom_game(cur, game)
    if not ok:
        return {"status": "error", "message": msg}
    if not games_store.save_games(get_root_dir(), cur):
        return {"status": "error", "message": "не удалось сохранить"}
    games_store.sync_include_list(get_root_dir(), data=cur)
    return {"status": "ok", "games": cur,
            "message": "Сохранено. Домены применятся к новым подключениям; "
                       "UDP-фикс - после перезапуска обхода"}


def games_check(ctx: AppContext, data: dict) -> dict:
    """Проба доменов игры: открываются ли они сейчас (сквозь работающий
    обход, если он запущен). Возвращает код по каждому включённому домену."""
    game_id = str(data.get("id") or "")
    game = next((g for g in (games_store.load_games(get_root_dir())
                             .get("games") or [])
                 if str(g.get("id")) == game_id), None)
    if game is None:
        return {"status": "error", "message": "Игра не найдена"}
    hosts = [str(d.get("domain") or "").strip()
             for d in (game.get("domains") or []) if d.get("on")]
    hosts = [h for h in hosts if h]

    def _probe(host: str) -> dict:
        t0 = time.time()
        from core.probe_http import curl_code
        n = curl_code(f"https://{host}/", timeout=8, wall_pad=4)
        code = str(n) if n else "000"
        return {"domain": host, "code": code,
                "ok": code not in ("000", "000000"),
                "elapsed": round(time.time() - t0, 2)}

    # Параллельно: последовательные curl'ы (до 12 с на домен) не укладывались
    # в клиентский таймаут 30 с уже на 4-5 доменах (аудит 2026-10)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(_probe, hosts))
    return {"status": "ok", "results": results}


def games_add_domain(ctx: AppContext, data: dict) -> dict:
    """Добавить найденный в анализе домен прямо в игру."""
    game_id = str(data.get("game_id") or data.get("id") or "")
    domain = str(data.get("domain") or "")
    ok, message, added = games_store.add_game_domain(
        get_root_dir(), game_id, domain)
    return {"status": "ok" if ok else "error",
            "message": message, "added": added}
