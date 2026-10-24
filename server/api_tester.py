"""api_tester.py - тестер: статус, запуск действий, ASN-скан (аудит #1, Inc C).

Соглашение: (ctx, ...) -> dict; исключения - только ApiError. Busy-контракт
исторический: HTTP 409 (в старом server.py эти ветки шли с
HTTPStatus.CONFLICT). Сами воркеры - в server/tester_flow.py."""
from __future__ import annotations

import threading

from server import tester_flow
from server.api_common import ApiError
from server.app_state import STATE, AppContext, checkers_busy, get_tester


def tester_status(ctx: AppContext) -> dict:
    return STATE.tester_state.to_dict()


def tester_action(ctx: AppContext, data: dict) -> dict:
    action = data.get("action", "") if isinstance(data, dict) else ""
    if action == "cancel":
        with STATE.tester_state.lock:
            get_tester().signal_shutdown()
            STATE.tester_state.cancelled = True
        return {"status": "ok", "action": "cancelled"}
    busy = checkers_busy()
    if busy:
        raise ApiError(409, {"status": "error", "message": busy})
    # Решение «занят/свободен» и сброс cancel/event - атомарно под локом:
    # cancel после этой секции уже не будет потерян worker'ом.
    try:
        tester = get_tester()
    except Exception as e:  # noqa: BLE001
        raise ApiError(503, {"status": "error", "message": str(e)})
    with STATE.tester_state.lock:
        if STATE.tester_state.running:
            raise ApiError(409, {"status": "error",
                                 "message": "Тестер уже занят - дождитесь завершения"})
        tester.shutdown_event.clear()
        STATE.tester_state.cancelled = False
        STATE.tester_state.running = True
    t = threading.Thread(target=tester_flow.run_tester_action, args=(data,), daemon=True)
    t.start()
    return {"status": "ok", "action": "started"}


def asn_scan(ctx: AppContext, data: dict) -> dict:
    busy = checkers_busy()
    if busy:
        raise ApiError(409, {"status": "error", "message": busy})
    try:
        tester = get_tester()
    except Exception as e:  # noqa: BLE001
        raise ApiError(503, {"status": "error", "message": str(e)})
    with STATE.tester_state.lock:
        if STATE.tester_state.running:
            raise ApiError(409, {"status": "error", "message": "Тестер занят"})
        tester.shutdown_event.clear()
        STATE.tester_state.cancelled = False
        STATE.tester_state.running = True
    t = threading.Thread(target=tester_flow.run_asn_scan, daemon=True)
    t.start()
    return {"status": "ok"}
