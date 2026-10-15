"""api_tester.py - тестер: статус, запуск действий, ASN-скан (аудит #1, Inc C).

Соглашение: (ctx, ...) -> dict; исключения - только ApiError. Busy-контракт
исторический: HTTP 409 (в старом server.py эти ветки шли с
HTTPStatus.CONFLICT). Сами воркеры - в server/tester_flow.py."""
from __future__ import annotations

import threading

from server import tester_flow
from server.api_common import ApiError
from server.app_state import (STATE, AppContext, checkers_busy, get_tester,
                              scan_winws_exe)


def tester_status(ctx: AppContext) -> dict:
    return STATE.tester_state.to_dict()


def tester_action(ctx: AppContext, data: dict) -> dict:
    action = data.get("action", "")
    if action == "cancel":
        get_tester().signal_shutdown()
        with STATE.tester_state.lock:
            STATE.tester_state.cancelled = True
        return {"status": "ok", "action": "cancelled"}
    busy = checkers_busy()
    if busy:
        raise ApiError(409, {"status": "error", "message": busy})
    # P1-2: Zapret 1 (winws.exe) своим десинком искажает «голый» тест и все
    # профили. Действия, которые сами его не обрабатывают (current/naked/
    # cdn_scan умеют), отказывают - как это делает кнопка «Запустить».
    if action in ("test", "test_profiles", "full_analysis") and \
            scan_winws_exe()["running"]:
        raise ApiError(409, {"status": "error",
                             "message": "Zapret 1 (winws.exe) запущен. "
                                        "Остановите его перед запуском проверки."})
    # Решение «занят/свободен» принимаем атомарно под локом: отметка
    # running=True здесь же закрывает окно для второго параллельного POST.
    with STATE.tester_state.lock:
        if STATE.tester_state.running:
            raise ApiError(409, {"status": "error",
                                 "message": "Тестер уже занят - дождитесь завершения"})
        STATE.tester_state.running = True
    t = threading.Thread(target=tester_flow.run_tester_action, args=(data,), daemon=True)
    t.start()
    return {"status": "ok", "action": "started"}


def asn_scan(ctx: AppContext, data: dict) -> dict:
    busy = checkers_busy()
    if busy:
        raise ApiError(409, {"status": "error", "message": busy})
    with STATE.tester_state.lock:
        if STATE.tester_state.running:
            raise ApiError(409, {"status": "error", "message": "Тестер занят"})
        STATE.tester_state.running = True
    t = threading.Thread(target=tester_flow.run_asn_scan, daemon=True)
    t.start()
    return {"status": "ok"}
