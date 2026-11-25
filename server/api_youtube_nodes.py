"""api_youtube_nodes.py - тестовая проба пула кэшей googlevideo.

Только диагностика: проверяет узлы пула и возвращает таблицу + подсказку
hosts. Ничего не меняет в системе.
"""
from __future__ import annotations

from core import youtube_nodes
from server.app_state import AppContext, ui_debug


def youtube_nodes_scan(ctx: AppContext, data: dict) -> dict:
    target = str((data or {}).get("target") or "").strip()
    pool = youtube_nodes.parse_pool(target)
    if not pool:
        return {"status": "error",
                "message": "Не удалось определить пул: вставьте ссылку/имя вида "
                           "rr3---sn-xxxx.googlevideo.com или sn-xxxx из F12"}
    try:
        out = youtube_nodes.scan_pool(pool, check_http=True, timeout=2.5)
        return {"status": "ok", "result": out}
    except Exception as e:  # noqa: BLE001
        ui_debug(f"youtube_nodes scan: {e}")
        return {"status": "error", "message": str(e)[:300]}
