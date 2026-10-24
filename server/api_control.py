"""api_control.py - запуск/остановка обхода (кнопки «Запустить»/«Стоп»).

Переехало из server.py (аудит #1, Inc C). Соглашение: (ctx, ...) -> dict.
Если служба установлена, «Запустить»/«Стоп» работают через неё (её binPath
с актуальными аргументами), а не голым процессом winws2."""
from __future__ import annotations

from core.proc import kill_image, kill_image_filtered
from core.service_manager import (is_installed as svc_installed,
                                  start as svc_start, stop as svc_stop)
from server import api_service
from server.app_state import (AppContext, checkers_busy, get_config_manager,
                              get_controller, operation_guard, scan_winws_exe)


@operation_guard("bypass")
def start_zapret(ctx: AppContext, data: dict) -> dict:
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    z1 = scan_winws_exe()
    if z1["running"]:
        return {"status": "error", "message": "Zapret 1 (winws.exe) запущен. Остановите его перед запуском Zapret 2."}
    if svc_installed():
        # Служба установлена - «Запустить» поднимает службу (её же
        # binPath с актуальными аргументами), а не голый winws2: иначе
        # после сервис-осведомлённого «Стоп» обход оставался ручным.
        from core.service_manager import path_status as svc_path_status
        try:
            ps, ps_msg = svc_path_status()
            if ps == "mismatch":
                return {"status": "error",
                        "message": ("Служба zapret2 принадлежит другой копии "
                                    f"программы: {ps_msg}. Удалите/переустановите "
                                    "службу из той копии, затем повторите.")}
            args, err = api_service.prepare_service_args(
                data if isinstance(data, dict) else {})
            if err:
                return {"status": "error",
                        "message": f"Не удалось собрать аргументы службы: {err}"}
            ok, msg = svc_start(args)
            return {"status": "ok" if ok else "error", "message": msg}
        except Exception as e:  # noqa: BLE001
            return {"status": "error",
                    "message": f"Ошибка запуска службы: {type(e).__name__}: {e}"}
    try:
        controller = get_controller()
        profile_name = data.get("profile", "") if isinstance(data, dict) else ""
        cfg = get_config_manager().load()
        ok, msg = controller.start(
            profile_name,
            game_filter_mode=cfg.game_filter_mode,
            discord_voice=cfg.discord_voice,
            discord_voice_mode=cfg.discord_voice_mode,
            fake_blob=cfg.fake_blob,
            winws2_debug=cfg.winws2_debug,
            autohostlist=cfg.autohostlist,
            ipset_catchall=cfg.ipset_catchall,
            discord_alt=cfg.discord_alt,
        )
        return {"status": "ok" if ok else "error", "message": msg}
    except Exception as e:  # noqa: BLE001
        return {"status": "error",
                "message": f"Ошибка запуска: {type(e).__name__}: {e}"}


def _my_winws2_paths() -> set[str]:
    """Пути winws2 ТОЛЬКО этой установки (ревью 18.10: не гасим движок
    второй копии GUI в другом каталоге)."""
    from server.app_state import get_root_dir
    root = get_root_dir()
    return {str(root / "bin" / "winws2.exe"), str(root / "winws2.exe")}


@operation_guard("bypass")
def stop_zapret(ctx: AppContext) -> dict:
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    try:
        if svc_installed():
            from core.service_manager import path_status as svc_path_status
            ps, ps_msg = svc_path_status()
            if ps == "mismatch":
                return {"status": "error",
                        "message": ("Служба zapret2 принадлежит другой копии "
                                    f"программы: {ps_msg}. Не трогаю её.")}
            # Служба установлена - «Стоп» обязан гасить именно её (sc stop),
            # иначе SCM-recovery поднимет winws2 обратно через ~60 с, а
            # рестарт с /start даст двойной захват (аудит 2026-10).
            ok_s, msg_s = svc_stop()
            if not ok_s:
                return {"status": "error",
                        "message": f"Не удалось остановить службу: {msg_s}"}
            get_controller().stop()
            kill_image("winws.exe", timeout=6)
            kill_image_filtered("winws2.exe", _my_winws2_paths(), timeout=6)
            return {"status": "ok",
                    "message": "Обход остановлен (служба zapret2 "
                               "остановлена до следующего запуска)"}
        get_controller().stop()
        kill_image("winws.exe", timeout=6)
        kill_image_filtered("winws2.exe", _my_winws2_paths(), timeout=6)
        return {"status": "ok", "message": "Все процессы zapret остановлены"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error",
                "message": f"Ошибка остановки: {type(e).__name__}: {e}"}
