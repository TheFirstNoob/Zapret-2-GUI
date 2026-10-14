"""api_diag.py - домен «диагностика системы» (аудит #1, Inc C).

Соглашение: (ctx: AppContext, ...) -> dict; исключения - только ApiError."""
from __future__ import annotations

from server.app_state import (STATE, AppContext, checkers_busy,
                              get_config_manager, get_root_dir)


def diagnose_action(ctx: AppContext, data: dict) -> dict:
    import threading as _th
    import time as _time
    from core.diagnostics import run_diagnostics, format_report_text
    # Диагностика и тестер - взаимно исключающие проверки: во время прогона
    # тестера отчёт был бы смесью «стабильно/перезапускается».
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    # Атомарная отметка «занято» - закрывает окно для параллельного POST.
    with STATE.diag_lock:
        if STATE.diag_state.get("running"):
            return {"status": "error", "message": "Проверка уже выполняется"}
        STATE.diag_state.update({"running": True, "progress": "", "report": None,
                                 "error": None, "started": _time.time()})

    def _worker():
        try:
            def _cb(name):
                with STATE.diag_lock:
                    STATE.diag_state["progress"] = name
            report = run_diagnostics(get_root_dir(), get_config_manager().load(),
                                     progress_cb=_cb)
            report["elapsed_sec"] = round(_time.time()
                                          - STATE.diag_state["started"], 1)
            report["report_text"] = format_report_text(report)
            with STATE.diag_lock:
                STATE.diag_state["report"] = report
        except Exception as e:  # noqa: BLE001
            with STATE.diag_lock:
                STATE.diag_state["error"] = str(e)
        finally:
            with STATE.diag_lock:
                STATE.diag_state["running"] = False

    _th.Thread(target=_worker, daemon=True).start()
    return {"status": "ok"}


def diagnose_status(ctx: AppContext) -> dict:
    with STATE.diag_lock:
        return {"status": "ok",
                **{k: STATE.diag_state[k]
                   for k in ("running", "progress", "error")},
                "report": STATE.diag_state["report"]}
