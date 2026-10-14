"""api_zapret1.py - хендлеры домена «Zapret 1 (управление)» (аудит #1, Inc C).

Соглашение: (ctx: AppContext, ...) -> dict; ApiError - для нестандартных
статусов (busy у stop исторически отдаётся с HTTP 409)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from core.proc import kill_image
from server.api_common import ApiError
from server.app_state import (AppContext, checkers_busy, get_config_manager,
                              get_controller)


def zapret1_strategies(ctx: AppContext) -> dict:
    cfg = get_config_manager().load()
    dir_path = cfg.zapret1_dir
    if not dir_path or not Path(dir_path).is_dir():
        return {"status": "ok", "strategies": []}
    bats = []
    for f in sorted(Path(dir_path).glob("*.bat")):
        name = f.stem.lower()
        if name == "service":
            continue
        bats.append({"name": f.stem, "path": str(f)})
    return {"status": "ok", "strategies": bats}


def zapret1_save_dir(ctx: AppContext, data: dict) -> dict:
    path = data.get("path", "").strip()
    if not path or not Path(path).is_dir():
        return {"status": "error",
                "message": "Укажите существующую папку Zapret 1"}
    cfg = get_config_manager().load()
    cfg.zapret1_dir = path
    get_config_manager().save(cfg)
    return {"status": "ok", "message": "Путь сохранён"}


def zapret1_start(ctx: AppContext, data: dict) -> dict:
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    strategy = data.get("strategy", "").strip()
    if not strategy:
        return {"status": "error", "message": "Стратегия не указана"}
    # имя файла стратегии строится из клиентского значения (L2): без этой
    # проверки '..'/'../..' запускали .bat вне папки Zapret 1
    if Path(strategy).name != strategy or ".." in strategy or any(
            c in strategy for c in "/\\:*?\"<>|"):
        return {"status": "error", "message": "Недопустимое имя стратегии"}
    controller = get_controller()
    z2 = controller.status()
    if z2.running:
        return {"status": "error",
                "message": "Zapret 2 (winws2.exe) запущен. "
                           "Остановите его перед запуском Zapret 1."}
    cfg = get_config_manager().load()
    dir_path = cfg.zapret1_dir
    if not dir_path:
        return {"status": "error", "message": "Папка Zapret 1 не указана"}
    bat_path = Path(dir_path) / f"{strategy}.bat"
    if not bat_path.exists():
        return {"status": "error", "message": f"Файл {strategy}.bat не найден"}
    try:
        subprocess.Popen([str(bat_path)], cwd=str(bat_path.parent),
                         creationflags=subprocess.CREATE_NO_WINDOW)
        cfg.zapret1_last_strategy = strategy
        get_config_manager().save(cfg)
        return {"status": "ok", "message": f"Zapret 1 запущен: {strategy}.bat"}
    except OSError as e:
        return {"status": "error", "message": str(e)}


def zapret1_stop(ctx: AppContext) -> dict:
    busy = checkers_busy()
    if busy:
        # исторический контракт: 409 Conflict (не 200)
        raise ApiError(409, {"status": "error", "message": busy})
    if kill_image("winws.exe", timeout=8):
        return {"status": "ok", "message": "Zapret 1 остановлен"}
    return {"status": "error", "message": "taskkill для winws.exe не отработал"}
