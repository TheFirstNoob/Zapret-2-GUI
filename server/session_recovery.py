"""session_recovery.py - журнал незавершённой тест-сессии (crash-recovery).

Старший ревью (раунд 3) указал дыру: жёсткая гибель GUI посреди прогона
оставляет защиту снятой, а SCM-recovery - выключенным (finally не выполняется).
Здесь: durable-журнал logs/test_session_state.json, который пишется на старте
прогона (снимок защиты + сохранённая recovery-конфигурация) и очищается после
нормального завершения. На старте GUI (server.init) незавершённая сессия
обнаруживается и восстанавливается: recovery-конфигурация дословно + защита
(служба/процесс/Z1). Тот же путь используется при исключении посреди прогона
(восстановление сразу, не дожидаясь следующего старта).
"""
from __future__ import annotations

import datetime
import json
import os
import threading
from pathlib import Path
from typing import Callable, Optional

SESSION_JOURNAL_NAME = "test_session_state.json"


def journal_path(root_dir: Path) -> Path:
    return Path(root_dir) / "logs" / SESSION_JOURNAL_NAME


def _write(root_dir: Path, payload: dict) -> None:
    """Атомарная запись журнала (tmp + os.replace); ошибки не бросаем."""
    p = journal_path(root_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


def write_session_journal(root_dir: Path, action: str, protection: dict,
                          recovery: Optional[dict]) -> None:
    """Старт прогона: снимок для аварийного восстановления.

    protection: {"z2": bool, "z1": bool, "svc": bool}; recovery -
    service_manager.recovery_snapshot() или None."""
    _write(root_dir, {
        "state": "TESTING",
        "action": action,
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
        "protection": protection,
        "recovery": recovery,
    })


def clear_session_journal(root_dir: Path) -> None:
    """Нормальное завершение (или отработанное восстановление): журнал не нужен."""
    try:
        journal_path(root_dir).unlink(missing_ok=True)
    except OSError:
        pass


def read_session_journal(root_dir: Path) -> Optional[dict]:
    try:
        data = json.loads(journal_path(root_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def recover_unfinished_session(
        root_dir: Path,
        *,
        restore_recovery: Callable[[Optional[dict]], bool],
        restore_protection: Callable[[bool, bool, bool], str],
        log: Callable[[str], None]) -> Optional[str]:
    """Обработка незавершённой сессии (одна попытка, ошибки не бросает).

    restore_protection(z2_or_svc, z1, svc) -> строка-заметка (контракт
    как у restore_protection_after_naked). Возвращает описание или None."""
    data = read_session_journal(root_dir)
    if not data or data.get("state") != "TESTING":
        return None
    action = data.get("action") or "?"
    prot = data.get("protection") or {}
    z2 = bool(prot.get("z2"))
    z1 = bool(prot.get("z1"))
    svc = bool(prot.get("svc"))
    log(f"session-recovery: найдена незавершённая сессия "
        f"(action={action}, started={data.get('started', '?')})")
    notes: list[str] = []
    try:
        if restore_recovery(data.get("recovery")):
            notes.append("recovery-конфигурация восстановлена")
        else:
            notes.append("recovery-конфигурация НЕ восстановлена")
    except Exception as e:  # noqa: BLE001
        notes.append(f"recovery ошибка: {e}")
    try:
        if z2 or z1 or svc:
            note = restore_protection(z2 or svc, z1, svc)
            notes.append(note or "защита восстановлена")
        else:
            notes.append("защита не требовалась")
    except Exception as e:  # noqa: BLE001
        notes.append(f"защита: ошибка {e}")
    summary = "; ".join(notes)
    log(f"session-recovery: {summary}")
    _write(root_dir, {"state": "RECOVERED",
                      "action": action,
                      "started": data.get("started"),
                      "note": summary,
                      "recovered_at":
                          datetime.datetime.now().isoformat(timespec="seconds")})
    return summary


def start_startup_recovery() -> None:
    """Обработка журнала при init сервера (демон-поток, не тормозит старт).

    Импорты поздние: модуль должен быть безопасен на import-стадии."""
    def _worker() -> None:
        try:
            from core.service_manager import restore_recovery_from_snapshot
            from server.app_state import STATE, get_root_dir, ui_debug
            from server.tester_flow import restore_protection_after_naked

            def _restore_protection(z2_or_svc: bool, z1: bool, svc: bool) -> str:
                return restore_protection_after_naked(
                    z2_or_svc, z1, STATE.tester_state, svc)

            recover_unfinished_session(
                get_root_dir(),
                restore_recovery=restore_recovery_from_snapshot,
                restore_protection=_restore_protection,
                log=ui_debug)
        except Exception as e:  # noqa: BLE001
            try:
                from server.app_state import ui_debug
                ui_debug(f"session-recovery: исключение: {e}")
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True,
                     name="session-recovery").start()
