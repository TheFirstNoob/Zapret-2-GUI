"""api_games.py - хендлеры домена «игровые блокировки» (аудит #1, Inc C).

Соглашение: (ctx: AppContext, ...) -> dict; исключения - только ApiError."""
from __future__ import annotations

import time

from core import games as games_store
from server.api_common import ApiError
from server.app_state import AppContext, checkers_busy, get_root_dir


def _busy_or_409() -> None:
    """Правки игр во время проверки запрещены - 409, как у service-ручек.

    Тестер/диагностика/обновление держат живой прогон: правка games.json и
    комбинированного list-include-all.txt под ним меняет условия теста
    (аудит 2026-11-14, T12/T21)."""
    busy = checkers_busy()
    if busy:
        raise ApiError(409, {"status": "error", "message": busy})


def games_get(ctx: AppContext) -> dict:
    return {"status": "ok", "games": games_store.load_games(get_root_dir())}


def games_save(ctx: AppContext, data: dict) -> dict:
    """Сохранение игровых блокировок: домены применяются сразу (hot-reload
    hostlist), UDP-профили - при следующем запуске/переустановке службы."""
    _busy_or_409()
    payload = data.get("games") if isinstance(data, dict) else None
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
        return {"status": "error", "message": "некорректные данные"}
    valid, err = games_store.validate_games(payload)
    if not valid:
        return {"status": "error", "message": err}
    # Lock на save+sync: параллельный custom/add-domain запрос не оставит
    # stale combined-список (аудит 2026-11-14, T21).
    with games_store.games_lock():
        if not games_store.save_games(get_root_dir(), payload):
            return {"status": "error", "message": "не удалось сохранить"}
        try:
            games_store.sync_include_list(get_root_dir(), data=payload)
        except OSError as e:
            return {"status": "error",
                    "message": f"Игры сохранены, но combined-список не обновился: {e}"}
    return {
        "status": "ok",
        "message": "Сохранено. Домены применятся к новым подключениям; "
                   "UDP-фикс - после перезапуска обхода (службу - "
                   "переустановкой)"}


def games_custom(ctx: AppContext, data: dict) -> dict:
    """Своя игра: add/update/delete. Встроенные игры не редактируются."""
    _busy_or_409()
    action = str(data.get("action") or "save")
    game = data.get("game") if isinstance(data.get("game"), dict) else {}

    def _mutate(cur: dict) -> tuple[bool, str, dict]:
        if action == "delete":
            return games_store.delete_custom_game(
                cur, str(data.get("id") or ""))
        return games_store.upsert_custom_game(cur, game)

    # Одна транзакция под games_lock: load->mutate->validate->save->sync
    # (аудит 2026-11-14: два конкурентных запроса теряли чужую правку).
    with games_store.games_lock():
        ok, msg, cur = games_store.mutate_games(get_root_dir(), _mutate)
        if not ok:
            return {"status": "error", "message": msg}
        try:
            games_store.sync_include_list(get_root_dir(), data=cur)
        except OSError as e:
            return {"status": "error",
                    "message": f"Игры сохранены, но combined-список не обновился: {e}"}
    return {"status": "ok", "games": cur,
            "message": "Сохранено. Домены применятся к новым подключениям; "
                       "UDP-фикс - после перезапуска обхода"}


def games_check(ctx: AppContext, data: dict) -> dict:
    """Проба доменов игры: открываются ли они сейчас (сквозь работающий
    обход, если он запущен). Возвращает код по каждому включённому домену.

    Read-only (сетевые пробы, файлы не меняются) - busy-чек не нужен:
    проверка не мешает живому прогону."""
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
        n = curl_code(f"https://{host}/", timeout=4, wall_pad=2)
        code = str(n) if n else "000"
        return {"domain": host, "code": code,
                "ok": code not in ("000", "000000"),
                "elapsed": round(time.time() - t0, 2)}

    # Параллельно, но с общим дедлайном: клиент ждёт ответ не дольше 30 с.
    # Незапущенные пробы отменяем; частичный результат помечаем truncated.
    from concurrent.futures import (ThreadPoolExecutor, TimeoutError as
                                    FutureTimeout, as_completed)
    pool = ThreadPoolExecutor(max_workers=10)
    futures = {pool.submit(_probe, h): h for h in hosts}
    results: list[dict] = []
    try:
        for fut in as_completed(futures, timeout=25):
            host = futures[fut]
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001
                results.append({"domain": host, "code": "000", "ok": False,
                                "elapsed": 0, "error": str(e)[:80]})
    except FutureTimeout:
        pass
    finally:
        for fut in futures:
            fut.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
    order = {h: i for i, h in enumerate(hosts)}
    results.sort(key=lambda x: order.get(x["domain"], 999))
    return {"status": "ok", "results": results,
            "checked": len(results), "total": len(hosts),
            "truncated": len(results) < len(hosts)}


def games_add_domain(ctx: AppContext, data: dict) -> dict:
    """Добавить найденный в анализе домен прямо в игру."""
    _busy_or_409()
    game_id = str(data.get("game_id") or data.get("id") or "")
    domain = str(data.get("domain") or "")
    ok, message, added = games_store.add_game_domain(
        get_root_dir(), game_id, domain)
    return {"status": "ok" if ok else "error",
            "message": message, "added": added}
