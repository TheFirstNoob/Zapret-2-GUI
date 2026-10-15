"""custom_build.py - сборка и проверка личной стратегии «custom» (аудит #3).

Вынесено из tester_flow (бывш. server.py): build_custom + подстановка args +
validate_args + smoke-запуск winws2 на 1.5 с. Вызывается из
tester_flow._test_profiles_branch; результаты прогона (all_results) и tester
передаются явно.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from server.app_state import ui_debug as _ui_debug


def build_custom_strategy(root_dir: Path, all_results, tester) -> dict:
    """Личная стратегия: лучший сегмент на семейство (Discord ← P_a,
    Google ← P_b, General ← P_c). Сборка → валидация args → фильтр --dry-run
    → реальный smoke-запуск (1.5 с): пресет может быть «валидным», но упасть
    при запуске (--in-range без --wf-tcp-in). Исключения не глотает -
    вызывающий ловит и кладёт в final["custom"]."""
    from core.strategy_builder import build_custom
    from core.launcher import build_args_from_preset, validate_args

    results_by_profile = {
        res.profile_name: [
            {"domain": r.domain, "status": r.status, "test_type": r.test_type}
            for r in res.results
        ]
        for res in all_results if res
    }
    custom = build_custom(root_dir, results_by_profile)
    _ui_debug(f"custom: built sources={custom.get('sources')} "
              f"error={custom.get('error')}")
    if not custom.get("error"):
        args = build_args_from_preset(
            root_dir, root_dir / "lua", root_dir / "blobs",
            root_dir / "presets" / "custom.txt")
        ok, err = validate_args(root_dir / "bin" / "winws2.exe",
                                args, cwd=root_dir)
        custom["valid"] = ok
        custom["error"] = None if ok else err
        _ui_debug(f"custom: validate ok={ok} err={err!r}")
        # --dry-run не открывает WinDivert: пресет может быть
        # «валидным», но упасть при запуске (--in-range без
        # --wf-tcp-in). Реальный smoke-запуск на 1.5 с.
        if ok:
            try:
                import time as _time
                from core.launcher import launch_winws2_direct
                # Прямой запуск: PID = сам winws2, гасим
                # только его дерево (blanket taskkill убил
                # бы чужой/сервисный winws2).
                proc, perr = launch_winws2_direct(
                    root_dir,
                    root_dir / "bin" / "winws2.exe",
                    args, timeout=1.5)
                if proc is None:
                    _ui_debug(f"custom: smoke start err={perr!r}")
                _time.sleep(1.5)
                alive = tester.is_running()
                _ui_debug(f"custom: smoke alive={alive}")
                if proc is not None and proc.poll() is None:
                    try:
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                       capture_output=True, timeout=5,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
                # Страховка: winws2 мог отцепиться от
                # дерева - в этот момент любой живой
                # winws2 только наш.
                if tester.is_running():
                    tester._ensure_winws2_dead()
                if not alive:
                    custom["valid"] = False
                    custom["error"] = ("custom не стартует на реальном запуске "
                                       "(проверьте --wf-tcp-in/--in-range сегментов)")
                    _ui_debug("custom: smoke FAILED (winws2 did not stay alive)")
            except Exception as e:
                custom["valid"] = False
                custom["error"] = f"smoke-запуск custom не удался: {e}"
        src = custom["sources"]
        custom["summary"] = (
            "Собрана личная стратегия «custom»: "
            f"Discord ← {src.get('discord')}, Google ← {src.get('google')}, "
            f"General ← {src.get('general')} (остальное из default).")
    return custom
