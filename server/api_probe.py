"""api_probe.py - хендлеры домена «анализ процессов» (аудит #1, Inc C).

Соглашение: (ctx: AppContext, ...) -> dict; исключения - только ApiError."""
from __future__ import annotations

from server.app_state import (AppContext, get_process_probe, probe_debug,
                              ui_debug)


def probe_scan(ctx: AppContext) -> dict:
    """Список процессов с сетью - ТОЛЬКО по явной кнопке (AV-safe)."""
    try:
        from core.process_probe import list_processes
        procs = list_processes()
        return {"status": "ok", "processes": procs}
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        probe_debug(f"scan: ОШИБКА {e}")
        return {"status": "error", "message": str(e)}


def probe_start(ctx: AppContext, data: dict) -> dict:
    proc = str(data.get("process") or "").strip()
    if not proc:
        return {"status": "error", "message": "Укажите имя процесса или PID"}
    try:
        d = int(data.get("duration") or 60)
        # 0 = постоянная запись до кнопки «Стоп» (фронт даёт option value=0)
        duration = 0 if d == 0 else max(10, min(d, 300))
    except (TypeError, ValueError):
        duration = 60
    ok, msg = get_process_probe().start(proc, duration)
    if not ok:
        probe_debug(f"start: FAIL - {msg}")
    return {"status": "ok" if ok else "error", "message": msg}


def probe_stop(ctx: AppContext) -> dict:
    st = get_process_probe().stop()
    return {"status": "ok", "state": st}


def probe_debug_log(ctx: AppContext, data: dict) -> dict:
    """Frontend-логи (вкладки, кнопки, ошибки JS) - в ui_debug.log."""
    msg = str(data.get("msg") or "")
    if msg:
        ui_debug(f"frontend: {msg}")
    return {"status": "ok"}


def probe_status(ctx: AppContext) -> dict:
    return {"status": "ok", "state": get_process_probe().get_status()}


def probe_report(ctx: AppContext) -> dict:
    probe = get_process_probe()
    path = probe.save_report()
    return {"status": "ok", "report": probe.report_text(), "path": str(path)}
