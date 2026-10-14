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
