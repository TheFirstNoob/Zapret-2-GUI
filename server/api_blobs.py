"""api_blobs.py - TLS-фейк-блобы: список доступных и перебор (аудит #1).

Соглашение: (ctx, ...) -> dict; исключения - только ApiError (busy = 409,
исторический контракт). Перебор выполняет воркер из server/tester_flow.py."""
from __future__ import annotations

import threading

from server import tester_flow
from server.api_common import ApiError
from server.app_state import STATE, AppContext, checkers_busy, get_root_dir
from server.recommend import BLOB_PRIORITY, BLOB_STOPLIST


def fake_blobs(ctx: AppContext) -> dict:
    """Ключи доступных TLS-фейк-блобов (blobs/tls_clienthello_<key>.bin).

    Порядок - РУЧНОЙ приоритет BLOB_PRIORITY (живучесть на тестовой сети,
    батарея блобов); остальные после по алфавиту. Огромные (>700:
    снижают долю google-фейков) - помечаются. Имена с цифры в начале -
    через префикс (баг winws2, AGENTS правило 2)."""
    blobs_dir = get_root_dir() / "blobs"
    items = []
    if blobs_dir.is_dir():
        for f in blobs_dir.glob("tls_clienthello_*.bin"):
            key = f.stem.removeprefix("tls_clienthello_")
            if not key or key.endswith("_kyber") or key in BLOB_STOPLIST:
                continue
            size = f.stat().st_size if f.exists() else 0
            safe = key if not key[0].isdigit() else "blob_" + key
            recommended = key in BLOB_PRIORITY and size <= 700
            items.append({"key": safe, "size": size, "recommended": recommended,
                          "rank": BLOB_PRIORITY.index(key) if key in BLOB_PRIORITY else 999})
    # recommended (по ручному приоритету) → остальные по алфавиту
    items.sort(key=lambda it: (it["rank"] if it["recommended"] else 1000, it["key"]))
    return {"status": "ok",
            "blobs": [it["key"] for it in items],
            "sizes": {it["key"]: it["size"] for it in items},
            "recommended": [it["key"] for it in items if it["recommended"]]}


def blob_probe(ctx: AppContext, data: dict) -> dict:
    busy = checkers_busy()
    if busy:
        raise ApiError(409, {"status": "error", "message": busy})
    with STATE.tester_state.lock:
        if STATE.tester_state.running:
            raise ApiError(409, {"status": "error", "message": "Тестер занят"})
        STATE.tester_state.running = True
    t = threading.Thread(target=tester_flow.run_blob_probe, args=(data or {},), daemon=True)
    t.start()
    return {"status": "ok"}
