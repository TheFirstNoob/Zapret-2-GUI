"""api_update.py - домен «обновление программы» (аудит #1, Inc C).

Соглашение: (ctx: AppContext, ...) -> dict; исключения - только ApiError.
Сюда переехали и хендлеры, и фоновый worker (_run_update_worker).
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from core.config import VERSION
from server.app_state import (STATE, AppContext, checkers_busy, get_root_dir,
                              ui_debug)

# Кэш проверки обновлений: одна проверка за сессию приложения
# (значения - в STATE, аудит #1).
UPDATE_CHECK_TTL = 6 * 3600  # авто-проверка не чаще раза в 6 часов

# Ревью 18.10: check-and-set запуска - под локом (два одновременных
# /api/update/start поднимали два воркера с одним _extract).
_UPDATE_START_LOCK = threading.Lock()
_UPDATE_APPLY_LOCK = threading.Lock()


def _mk(dir_path: Path) -> Path:
    dir_path.mkdir(exist_ok=True)
    return dir_path


def run_update_worker(kind: str, tag: str, info: dict) -> None:
    """Worker обновления: скачать → бэкап → применить (portable) или
    подготовить self-update (exe) → проверить службу (аргументы устарели?)."""
    from core.updater import (apply_portable, fetch_release_manifest,
                              fetch_update, prepare_app_restart_bat,
                              prepare_exe_update,
                              service_args_stale, validate_release)
    from core.update_verify import verify as verify_signature
    from core.config import ConfigManager
    from core.launcher import build_args_from_preset
    from core.service_manager import (_read_stored_binpath, is_installed as
                                      svc_installed)

    updater_state = STATE.updater_state

    def prog(pct, msg):
        updater_state["percent"] = pct
        updater_state["phase"] = msg
        ui_debug(f"update: {pct}% {msg}")

    # Сброс состояния: повторный прогон не должен видеть error/result прошлого
    updater_state.update({"running": True, "phase": "проверка подписи",
                          "percent": 0, "error": None, "result": None})
    try:
        root_dir = get_root_dir()
        update_dir = root_dir / "updates"
        update_dir = update_dir if update_dir.is_dir() else _mk(update_dir)

        prog(10, "Проверка подписи обновления…")
        # Fail-closed: без валидной подписи офлайн-ключа обновление не ставим
        manifest_bytes, sig_text = fetch_release_manifest(tag, update_dir)
        if not verify_signature(manifest_bytes, sig_text):
            raise RuntimeError(
                "обновление не прошло проверку подлинности - скачайте версию "
                "вручную с GitHub и сверьте SHA256 из описания релиза")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except Exception:
            raise RuntimeError("манифест обновления повреждён")
        manifest_err = validate_release(manifest, tag, VERSION, kind)
        if manifest_err:
            raise RuntimeError(manifest_err)
        expected = str(manifest["artifacts"][kind]["sha256"]).lower()

        prog(25, "Скачивание обновления…")
        zip_path = fetch_update(kind, tag, update_dir,
                                sha256_expected=expected)

        prog(55, "Резервная копия настроек…")
        result: dict = {"applied": 0, "backup": None,
                        "service_mismatch": False,
                        "signature_verified": True,
                        "restart_required": True}

        if kind == "exe":
            prog(70, "Подготовка замены EXE…")
            # %TEMP%\_MEI* (onefile) удаляет сам батник: нас убивает taskkill,
            # а закрыться мы не успеваем - папка осталась бы висеть в TEMP.
            mei = getattr(sys, "_MEIPASS", "") if getattr(sys, "frozen", False) else ""
            bat = prepare_exe_update(
                zip_path, root_dir,
                exe_sha256=manifest["artifacts"]["exe"].get("exe_sha256"),
                mei_dir=mei or None)
            # Батник НЕ запускаем здесь: пользователь должен увидеть
            # «обновление применено» до того, как программа закроется.
            # Запуск - отдельным запросом /api/update/apply (REVIEW_VERDICT.md §2.7).
            result["update_bat"] = str(bat)
            result["restart_required"] = True
        else:
            # «Как в стиме»: обход стопаем ДО замены файлов (winws2 держит
            # bin/winws2.exe на диске - копирование в занятый файл падало бы),
            # после применения поднимаем обратно тем же binPath.
            svc_was = False
            ctrl_was = False
            ctrl = None
            ctrl_cfg = None
            try:
                from core.service_manager import start as _svc_start
                from core.service_manager import status as _svc_status
                from core.service_manager import stop as _svc_stop
                svc_was = _svc_status() == "running"
            except Exception:
                _svc_stop = _svc_start = None
            if not svc_was:
                # Portable/dev: обход может быть запущен напрямую controller'ом.
                # Его тоже надо остановить, иначе apply наткнётся на занятый
                # bin/winws2.exe (аудит 24.10).
                try:
                    from server.app_state import get_controller, get_config_manager
                    ctrl = get_controller()
                    ctrl_was = ctrl.status().running
                    ctrl_cfg = get_config_manager().load()
                except Exception as e:  # noqa: BLE001
                    ui_debug(f"update: controller probe failed: {e}")
            if svc_was and _svc_stop:
                prog(58, "Остановка обхода…")
                try:
                    _svc_stop()
                except Exception as e:  # noqa: BLE001
                    ui_debug(f"update: stop service failed: {e}")
                time.sleep(1.0)
            elif ctrl_was and ctrl:
                prog(58, "Остановка обхода…")
                try:
                    ctrl.stop()
                except Exception as e:  # noqa: BLE001
                    ui_debug(f"update: stop controller failed: {e}")
                time.sleep(1.0)
            prog(70, "Применение обновления…")
            # try/finally: служба/controller, остановленные ДО apply, обязаны
            # подняться и при исключении в apply.
            applied = None
            try:
                applied = apply_portable(
                    zip_path, root_dir,
                    progress_cb=lambda m: prog(80, str(m)))
            finally:
                if svc_was and _svc_start:
                    prog(92, "Запуск обхода…")
                    try:
                        _svc_start()
                    except Exception as e:  # noqa: BLE001
                        ui_debug(f"update: start service failed: {e}")
                elif ctrl_was and ctrl and ctrl_cfg:
                    prog(92, "Запуск обхода…")
                    try:
                        ctrl.start(
                            ctrl_cfg.last_profile,
                            game_filter_mode=ctrl_cfg.game_filter_mode,
                            discord_voice=ctrl_cfg.discord_voice,
                            discord_voice_mode=ctrl_cfg.discord_voice_mode,
                            fake_blob=ctrl_cfg.fake_blob,
                            winws2_debug=ctrl_cfg.winws2_debug,
                            autohostlist=ctrl_cfg.autohostlist,
                            ipset_catchall=ctrl_cfg.ipset_catchall,
                            discord_alt=ctrl_cfg.discord_alt,
                        )
                    except Exception as e:  # noqa: BLE001
                        ui_debug(f"update: start controller failed: {e}")
            result.update(applied=applied["updated"],
                          skipped_user=applied["skipped_user"],
                          backup=applied["backup"])
            # Автоперезапуск приложения (portable/dev): сервер уже на новых
            # файлах, но процесс - старый; батник убьёт наш PID и запустит
            # заново тем же интерпретатором. Ошибки не фатальны - останется
            # ручной перезапуск.
            try:
                import os as _os
                bat = prepare_app_restart_bat(root_dir, _os.getpid())
                result["restart_bat"] = str(bat) if bat else ""
            except Exception as e:  # noqa: BLE001
                ui_debug(f"update: restart bat failed: {e}")
                result["restart_bat"] = ""
            result["restart_required"] = True

        # Служба установлена? Сравнить её аргументы с собранными из НОВЫХ
        # файлов - при расхождении предложить переустановку службы
        prog(95, "Проверка конфигурации службы…")
        if svc_installed():
            cfg = ConfigManager(root_dir).load()
            new_args = build_args_from_preset(
                root_dir, root_dir / "lua", root_dir / "blobs",
                root_dir / "presets" / f"{cfg.last_profile or 'default'}.txt",
                lists_dir=root_dir / "lists",
                windivert_dir=root_dir / "windivert",
                debug=cfg.winws2_debug, game_filter_mode=cfg.game_filter_mode,
                discord_voice=cfg.discord_voice,
                discord_voice_mode=cfg.discord_voice_mode,
                autohostlist=cfg.autohostlist,
                ipset_catchall=cfg.ipset_catchall,
                fake_blob=cfg.fake_blob,
                discord_alt=cfg.discord_alt)
            stored = _read_stored_binpath()
            result["service_mismatch"] = service_args_stale(stored, new_args)
            ui_debug(f"update: service_mismatch={result['service_mismatch']}")
        else:
            result["service_mismatch"] = False

        prog(100, "Обновление готово")
        updater_state["result"] = result
    except Exception as e:  # noqa: BLE001
        ui_debug(f"update: EXCEPTION {e}")
        updater_state["error"] = str(e)[:200]
    finally:
        updater_state["running"] = False


def update_check(ctx: AppContext, params: dict) -> dict:
    force = "1" in (params or {}).get("force", [])
    now = time.time()
    if (force or STATE.update_check_cache is None
            or (now - STATE.update_check_at) > UPDATE_CHECK_TTL):
        from core.updates import check_for_updates
        STATE.update_check_cache = check_for_updates()
        STATE.update_check_at = now
    return {"status": "ok", **STATE.update_check_cache}


def update_status(ctx: AppContext) -> dict:
    return {"status": "ok", **STATE.updater_state}


def update_start(ctx: AppContext) -> dict:
    with _UPDATE_START_LOCK:
        busy = checkers_busy()
        if busy:
            return {"status": "error", "message": busy}
        if STATE.updater_state["running"]:
            return {"status": "error",
                    "message": "Обновление уже выполняется"}
        info = (STATE.update_check_cache or {}).copy()
        if not info.get("available"):
            return {"status": "error",
                    "message": "Обновление недоступно или версия уже актуальна"}

        tag = info.get("tag") or info.get("latest", "").replace(" ", "-")
        kind = "portable" if not getattr(sys, "frozen", False) else "exe"
        STATE.updater_state.update({"running": True, "phase": "скачивание",
                                    "percent": 5, "error": None, "result": None})
        t = threading.Thread(target=run_update_worker,
                             args=(kind, tag, info), daemon=True)
        t.start()
        return {"status": "ok", "action": "started"}


def update_apply(ctx: AppContext) -> dict:
    """Запуск замены EXE (шаг 2 самообновления).

    Батник лежит рядом с exe (_update_self.bat), путь клиент не задаёт:
    он переживает наш процесс и закрывает его сам. Вызывается один раз
    после того, как пользователь увидел результат проверки подписи."""
    from core.updater import launch_update_bat
    with _UPDATE_APPLY_LOCK:
        if STATE.updater_state["running"]:
            return {"status": "error", "message": "Обновление ещё выполняется"}
        res = STATE.updater_state.get("result") or {}
        if res.get("applied_launch"):
            return {"status": "error", "message": "Замена уже запущена"}
        cand = str(res.get("update_bat") or res.get("restart_bat") or "")
        bat_name = Path(cand).name
        if bat_name not in ("_update_self.bat", "_restart_app.bat"):
            return {"status": "error", "message":
                    "Замена программы не подготовлена - запустите обновление заново"}
        bat = get_root_dir() / bat_name
        if not bat.exists():
            return {"status": "error", "message":
                    "Файл обновления не найден, запустите обновление заново"}
        try:
            launch_update_bat(bat)
        except RuntimeError as e:
            return {"status": "error", "message": str(e)}
        # Убираем результат, чтобы второй apply не запустил bat повторно.
        STATE.updater_state["result"] = {**res, "applied_launch": True}
        ui_debug("update: self-update bat launched")
        return {"status": "ok", "message":
                "Программа сейчас закроется и запустится заново"}
