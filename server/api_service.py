"""api_service.py - хендлеры домена «служба» (аудит #1, Inc C, пилот).

Соглашение API-слоя: свободная функция (ctx: AppContext, ...) -> dict
(JSON-ответ, HTTP 200) либо ApiError для нестандартного статуса. Транспорт
(_send_json) вызывает роутер - хендлеры про HTTP не знают."""
from __future__ import annotations

from typing import Optional

from core.config import DEFAULT_PROFILE
from core.launcher import build_args_from_preset, validate_args
from core.service_manager import (SERVICE_NAME, install as svc_install,
                                  is_installed as svc_installed,
                                  path_status as svc_path_status,
                                  remove as svc_remove,
                                  repair as svc_repair, start as svc_start,
                                  status as svc_status, stop as svc_stop)
from server.app_state import (AppContext, checkers_busy, get_config_manager,
                              get_controller, get_root_dir, operation_guard,
                              ui_debug)


def _ownership_error() -> str:
    """Не даём этой копии GUI/lite трогать службу, установленную другой."""
    try:
        state, detail = svc_path_status()
    except Exception as e:  # noqa: BLE001
        return f"Не удалось проверить владельца службы: {e}"
    if state == "mismatch":
        return ("Служба zapret2 установлена из другой папки: "
                f"{detail}. Не трогаю её: удалите/переустановите службу "
                "из той копии программы.")
    return ""


def _svc_fail(action: str, e: Exception) -> dict:
    """Единый ответ на неожиданное исключение сервисного действия.

    Раньше такие ошибки (например, OSError записи pool-файла/временного
    conf) уходили наружу как HTTP 500. Ревью 23.10: возвращаем читаемую
    ошибку в JSON, детали - в ui_debug."""
    ui_debug(f"service {action}: {type(e).__name__}: {e}")
    return {"status": "error",
            "message": f"Ошибка службы ({action}): {type(e).__name__}: {e}"}


def prepare_service_args(data: dict) -> tuple[Optional[list[str]], str]:
    """Сборка и валидация аргументов winws2 для службы (direct-exe).

    Служба запускает winws2.exe сама; аргументы пишутся в
    logs/service_run.conf, binPath короткий (@-ссылка). Обновляются при
    install/start (без cmd/bat-обёртки)."""
    cfg = get_config_manager().load()
    profile = data.get("profile") or cfg.last_profile or DEFAULT_PROFILE
    game_filter = data.get("game_filter") or cfg.game_filter_mode or "off"
    voice_mode = (str(data.get("discord_voice_mode") or "").strip().lower()
                  or cfg.discord_voice_mode
                  or ("fake" if data.get("discord_voice", cfg.discord_voice) else "off"))
    discord_voice = voice_mode != "off"
    debug = bool(data.get("debug", cfg.winws2_debug))
    autohostlist = bool(data.get("autohostlist", cfg.autohostlist))
    ipset_catchall = bool(data.get("ipset_catchall", cfg.ipset_catchall))
    root = get_root_dir()
    exe = get_controller().winws2_path
    if exe is None:
        return None, "winws2.exe не найден"
    preset = root / "presets" / f"{profile}.txt"
    if not preset.exists():
        return None, f"Пресет '{profile}.txt' не найден"
    args = build_args_from_preset(root, root / "lua", root / "blobs", preset, debug=debug,
                                  game_filter_mode=game_filter,
                                  discord_voice=discord_voice,
                                  discord_voice_mode=voice_mode,
                                  fake_blob=str(data.get("fake_blob") or cfg.fake_blob or ""),
                                  autohostlist=autohostlist,
                                  ipset_catchall=ipset_catchall,
                                  discord_alt=bool(data.get("discord_alt", cfg.discord_alt)))
    ok, err = validate_args(exe, args, cwd=root)
    if not ok:
        return None, err
    return args, ""


def service_status(ctx: AppContext) -> dict:
    try:
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "installed": svc_installed(),
            "running": svc_status() == "running",
        }
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "service": SERVICE_NAME,
                "installed": False, "running": False,
                "message": f"Не удалось прочитать состояние службы: {e}"}


@operation_guard("service")
def service_install(ctx: AppContext, data: dict) -> dict:
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    owner = _ownership_error()
    if owner:
        return {"status": "error", "message": owner}
    try:
        args, err = prepare_service_args(data)
    except Exception as e:  # noqa: BLE001
        return _svc_fail("подготовка установки", e)
    if err:
        return {"status": "error", "message": f"Установка отменена - {err}"}
    cleanup = bool(data.get("cleanup_zapret1")) if isinstance(data, dict) else False
    try:
        ok, msg = svc_install(root_dir=get_root_dir(), args=args,
                              cleanup_zapret1=cleanup)
    except Exception as e:  # noqa: BLE001
        return _svc_fail("установка", e)
    if ok:
        # статус на главной показывал «стратегия «?»» - служба запускается
        # вне controller, и тот не знал профиль
        try:
            profile = str(data.get("profile") or "").strip()
            if profile:
                get_controller().current_strategy = profile
        except Exception:
            pass
    return {"status": "ok" if ok else "error", "message": msg}


@operation_guard("service")
def service_remove(ctx: AppContext) -> dict:
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    owner = _ownership_error()
    if owner:
        return {"status": "error", "message": owner}
    try:
        ok, msg = svc_remove()
    except Exception as e:  # noqa: BLE001
        return _svc_fail("удаление", e)
    return {"status": "ok" if ok else "error", "message": msg}


@operation_guard("service")
def service_repair(ctx: AppContext) -> dict:
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    owner = _ownership_error()
    if owner:
        return {"status": "error", "message": owner}
    try:
        result = svc_repair(root_dir=get_root_dir())
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}
    return {"status": "ok", **result}


@operation_guard("service")
def service_start(ctx: AppContext, data: dict | None = None) -> dict:
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    owner = _ownership_error()
    if owner:
        return {"status": "error", "message": owner}
    # Обновляем параметры службы текущими аргументами: устаревший conf молча
    # запустит старую стратегию. data передаёт те же profile/toggles, что
    # install (иначе второй вызов откатывал выбор к старому config).
    try:
        args, err = prepare_service_args(data if isinstance(data, dict) else {})
    except Exception as e:  # noqa: BLE001
        return _svc_fail("подготовка запуска", e)
    if err:
        return {"status": "error", "message": f"Служба не запущена - {err}"}
    try:
        ok, msg = svc_start(args)
    except Exception as e:  # noqa: BLE001
        return _svc_fail("запуск", e)
    if ok:
        try:
            get_controller().current_strategy = get_config_manager().load().last_profile
        except Exception:
            pass
    return {"status": "ok" if ok else "error", "message": msg}


@operation_guard("service")
def service_stop(ctx: AppContext) -> dict:
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    owner = _ownership_error()
    if owner:
        return {"status": "error", "message": owner}
    try:
        ok, msg = svc_stop()
    except Exception as e:  # noqa: BLE001
        return _svc_fail("остановка", e)
    if ok:
        try:
            get_controller().current_strategy = None
        except Exception:
            pass
    return {"status": "ok" if ok else "error", "message": msg}
