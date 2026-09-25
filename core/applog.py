"""Операционный лог приложения: всегда включён, читается глазами.

Зачем (2026-09-25): разбор установки службы и запуска winws2 упирался в
отсутствие лога - ui_debug.log пишет только UI-события, probe_debug.log -
только анализ процессов. Здесь - служба и запуск: команды, коды возврата,
вывод sc/API, верификация binPath, откаты, повторы.

Файл: <каталог программы>/logs/zapret2.log (ротация >5MB -> zapret2.old.log).
Строка: "2026-09-25 19:30:44.123 [service] install: ...".
"""
from __future__ import annotations

import datetime as _dt
import threading
from pathlib import Path

_LOCK = threading.Lock()
_MAX_BYTES = 5 * 1024 * 1024


def log_dir() -> Path:
    from core.utils import app_root
    return app_root() / "logs"


def log_path() -> Path:
    return log_dir() / "zapret2.log"


def log(section: str, msg: str) -> None:
    """Дописать строку в операционный лог. Никогда не бросает."""
    try:
        ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"{ts} [{section}] {msg}\n"
        with _LOCK:
            p = log_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists() and p.stat().st_size > _MAX_BYTES:
                try:
                    p.replace(p.with_name("zapret2.old.log"))
                except OSError:
                    pass
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass
