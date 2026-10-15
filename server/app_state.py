"""app_state.py - единое состояние HTTP-сервера (аудит #1, Inc B).

Раньше это были модульные глобалы server.py (~42 точки прямого доступа).
Теперь: скаляры (root_dir/token/controller/tester/config/server/probe, кэши)
читаются и пишутся через STATE; объектные состояния (TesterState, diag/
updater-словари, локи) - стабильные ссылки, server.py держит их алиасами.

Следующий шаг (Inc C): хендлеры уезжают в api_*.py и получают ctx явно (DI).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from core.test_logger import TestLogger
from core.config import ConfigManager
from core.tester import Zapret2Tester
from core.zapret_controller import ZapretController


class TesterState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.progress_pct = 0
        self.progress_msg = ""
        self.results: list[dict] = []
        self.final_result: Optional[dict] = None
        self.all_results: Optional[list[dict]] = None
        self.error: Optional[str] = None
        self.cancelled = False
        self.action_type: Optional[str] = None
        self.logger: Optional[TestLogger] = None
        # ярлыки завершённых стратегий: UI закрывает их строки при каждом
        # опросе (сообщение «Стратегия X: N%» могло перезаписаться следующим)
        self.completed: list[str] = []

    def reset(self):
        self.progress_pct = 0
        self.progress_msg = ""
        self.results = []
        self.final_result = None
        self.all_results = None
        self.error = None
        self.cancelled = False
        self.action_type = None
        self.logger = None
        self.completed = []

    def to_dict(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "progress": {"percent": self.progress_pct, "message": self.progress_msg},
                "results": list(self.results),
                "final_result": self.final_result,
                "all_results": self.all_results,
                "error": self.error,
                "cancelled": self.cancelled,
                "action": self.action_type,
                "completed": list(self.completed),
            }

    def set_progress(self, pct: int, msg: str) -> None:
        with self.lock:
            self.progress_pct = pct
            self.progress_msg = msg

    def add_result(self, data: dict) -> None:
        with self.lock:
            self.results.append(data)

    def set_final(self, result: dict, all_results: Optional[list[dict]] = None) -> None:
        with self.lock:
            self.final_result = result
            self.all_results = all_results
            self.running = False


class AppContext:
    """Состояние сервера в одном месте (DI-контейнер предстоящего Inc C)."""

    def __init__(self) -> None:
        # скаляры
        self.root_dir: Optional[Path] = None
        self.app_token: str = ""
        self.controller = None
        self.tester = None
        self.config_manager = None
        self.server = None
        self.process_probe = None
        # кэши
        self.update_check_cache: Optional[dict] = None
        self.update_check_at: float = 0.0
        self.zapret1_installed_cache: Optional[bool] = None
        # объектные состояния (никто не переприсваивает - ссылки стабильны)
        self.tester_lock = threading.Lock()
        self.diag_lock = threading.Lock()
        self.tester_state = TesterState()
        self.diag_state = {"running": False, "progress": "", "report": None,
                           "error": None, "started": 0.0}
        self.updater_state = {
            "running": False,
            "phase": "",
            "percent": 0,
            "error": None,
            "result": None,   # {applied, backup, service_mismatch, restart_required}
        }


STATE = AppContext()


# ── Фабрики доступа (переехали из server.py, Inc B/C) ──────────────

def get_root_dir() -> Path:
    if STATE.root_dir is None:
        raise RuntimeError("Service not initialised")
    return STATE.root_dir


def get_controller() -> ZapretController:
    if STATE.controller is None:
        raise RuntimeError("Service not initialised")
    return STATE.controller


def get_config_manager() -> ConfigManager:
    if STATE.config_manager is None:
        raise RuntimeError("Service not initialised")
    return STATE.config_manager


def get_tester() -> Zapret2Tester:
    if STATE.tester is None:
        raise RuntimeError("Service not initialised")
    return STATE.tester


def get_process_probe():
    """Singleton process-probe (анализ сетевой активности игры/приложения)."""
    if STATE.process_probe is None:
        from core.process_probe import ProcessProbe
        STATE.process_probe = ProcessProbe()
    return STATE.process_probe


def checkers_busy() -> Optional[str]:
    """Сообщение о занятости проверки, или None, если всё свободно.

    Тестер (стратегии/CDN/ASN/blob) и диагностика взаимоисключающие; запуск/
    остановка обхода и службы во время проверки тоже запрещены."""
    with STATE.tester_state.lock:
        if STATE.tester_state.running:
            return "Тестер занят - завершите текущую проверку"
    with STATE.diag_lock:
        if STATE.diag_state.get("running"):
            return "Диагностика выполняется - дождитесь завершения"
    return None


# ── Debug-логи (переехали из server.py, Inc C) ────────────────────

def debug_append(file_name: str, msg: str) -> None:
    """Debug-лог с ротацией (L7): >5MB - старый уходит в .old.log."""
    import datetime as _dt
    try:
        from core.utils import get_temp_dir
        p = get_temp_dir() / file_name
        if p.exists() and p.stat().st_size > 5 * 1024 * 1024:
            try:
                p.replace(p.with_suffix(".old.log"))
            except OSError:
                pass
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{_dt.datetime.now().strftime('%H:%M:%S.%f')[:-3]} {msg}\n")
    except Exception:
        pass


def probe_debug(msg: str) -> None:
    """Probe-логи: в консоль (если есть) + в файл (GUI без консоли)."""
    print(f"[probe] {msg}", flush=True)
    debug_append("probe_debug.log", msg)


def ui_debug(msg: str) -> None:
    """UI/flow-логи (вкладки, кнопки, сбросы тестера) - ui_debug.log.

    Всегда активен: ловит «выкинуло на главный блок посреди теста»."""
    debug_append("ui_debug.log", msg)


# ── Системные запросы (переехали из server.py, Inc C) ─────────────

def ui_presets() -> list[str]:
    """Профили для GUI: exp-/test-/cand- префиксы - стенды экспериментов и
    кандидатов, пользователь не должен видеть их в интерфейсе."""
    presets_dir = get_root_dir() / "presets"
    if not presets_dir.is_dir():
        return []
    return sorted(
        f.stem for f in presets_dir.glob("*.txt")
        if not f.stem.startswith(("exp-", "test-", "cand-", "_probe"))
    )


def scan_winws_exe() -> dict:
    """Zapret 1 (winws.exe) на машине? running/pid (CSV-парсер core.proc)."""
    from core.proc import image_pids
    pids = image_pids("winws.exe", timeout=6)
    return {"running": bool(pids), "pid": pids[0] if pids else 0}


def zapret1_installed() -> bool:
    """Zapret 1 есть в системе? (настроенная папка или служба zapret).

    Нужно, чтобы не показывать панель «Zapret 1» тем, у кого его нет.
    Кэшируется на сеанс: службы в рамках сеанса не появляются/исчезают.
    """
    if STATE.zapret1_installed_cache is not None:
        return STATE.zapret1_installed_cache
    installed = False
    try:
        cfg = get_config_manager().load()
        installed = bool(cfg.zapret1_dir)
    except Exception:
        installed = False
    if not installed:
        try:
            from core.utils import run_sc
            code, _ = run_sc(["query", "zapret"])
            installed = code == 0
        except Exception:
            installed = False
    STATE.zapret1_installed_cache = installed
    return installed
