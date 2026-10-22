"""tester_proc.py - процессная обвязка winws2 (аудит #5).

Вынесено из Zapret2Tester: kill/poll-операции без состояния тестера (managed
процесс - исключение: владелец передаёт kill-колбэк в ensure_winws2_dead).
Внутри используется core.proc (аудит #7) - локале-независимые CSV-проверки.
"""
from __future__ import annotations

import subprocess
import time

from core.applog import log as _applog
from core.tester_defs import WINDIVERT_CLEANUP_DELAY


def any_winws_running() -> bool:
    """True если хотя бы один winws2.exe или winws.exe запущен (аудит #7)."""
    from core.proc import image_running
    return (image_running("winws2.exe", timeout=3)
            or image_running("winws.exe", timeout=3))


def any_winws2_running() -> bool:
    """True если winws2.exe запущен (только winws2, без winws.exe)."""
    from core.proc import image_running
    return image_running("winws2.exe", timeout=3)


def wait_windivert_free(timeout: float = WINDIVERT_CLEANUP_DELAY * 4) -> None:
    """Poll пока winws2 процессы не исчезнут (WinDivert освобождается).
    _TIMEOUT - upper bound, обычно <100ms если kill уже отработал."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not any_winws2_running():
            return
        time.sleep(0.1)


def run_quiet(args: list[str], timeout: float = 6.0) -> None:
    """Подпроцесс с гарантированным таймаутом; не бросает исключений."""
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="oem", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
    except Exception:
        pass


def process_exists(image_name: str) -> bool:
    """Быстрая проверка: запущен ли процесс с таким именем (аудит #7)."""
    from core.proc import image_running
    return image_running(image_name, timeout=5)


def kill_never_hang(image_name: str, allowed_paths=None) -> None:
    """Убить процесс по имени (несколько способов) без зависаний:
    сначала проверка существования, у каждого способа свой таймаут.

    allowed_paths: если задан - убиваем ТОЛЬКО процессы с таким exe
    (path-фильтр; две копии GUI не убивают движки друг друга, ревью 18.10).
    Name-wide wmic/PowerShell-фолбэки в этом режиме не используются."""
    if allowed_paths:
        from core.proc import kill_image_filtered
        for _ in range(2):
            if not process_exists(image_name):
                return
            kill_image_filtered(image_name, allowed_paths, timeout=6.0)
            time.sleep(0.2)
        return
    if not process_exists(image_name):
        return

    # Способ 1: taskkill
    run_quiet(["taskkill", "/F", "/IM", image_name], timeout=6.0)
    if not process_exists(image_name):
        return

    # Способ 2: wmic
    run_quiet(
        ["wmic", "process", "where", f"name='{image_name}'", "delete"],
        timeout=6.0,
    )
    if not process_exists(image_name):
        return

    # Способ 3: PowerShell
    base = image_name.replace(".exe", "").replace(".EXE", "")
    run_quiet(
        ["powershell", "-NoProfile", "-Command",
         f"Stop-Process -Name '{base}' -Force -ErrorAction SilentlyContinue"],
        timeout=6.0,
    )


def taskkill_safe(image_name: str, allowed_paths=None) -> None:
    """Убить процесс без зависаний: делегирует в kill_never_hang."""
    kill_never_hang(image_name, allowed_paths)


def kill_managed(proc) -> bool:
    """Погасить управляемый процесс тестера: PID-таргетинг + ОЖИДАНИЕ выхода.

    Возвращает True только при ПОДТВЕРЖДЁННОМ завершении процесса (ревью
    старшей модели, P1-1: taskkill/TerminateProcess асинхронны)."""
    if proc is None:
        return False
    pid = proc.pid
    # taskkill по PID надёжнее цепочки terminate/kill
    from core.proc import kill_pid
    kill_pid(pid, timeout=5)
    try:
        proc.wait(timeout=5)
        return True
    except subprocess.TimeoutExpired:
        pass
    if not any_winws2_running():
        return True
    # Фолбэк: terminate → kill (процесс не отвечает на taskkill)
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=2)
    except (subprocess.TimeoutExpired, OSError):
        try:
            proc.kill()
            proc.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return proc.poll() is not None


def ensure_winws2_dead(kill_managed_fn, allowed_paths=None) -> None:
    """Гарантированно убрать winws2: managed (PID, с подтверждением выхода) →
    задержка на освобождение хендлов → blanket kill (крайняя мера, если
    managed не подтвердился) → ожидание исчезновения winws2.

    kill_managed_fn - колбэк владельца (тестер хранит Popen-хэндл, P1-1)."""
    # Сначала управляемый процесс: PID + ожидание сигнализации процесса
    confirmed = kill_managed_fn()

    # Минимальная задержка на освобождение WinDivert: даже если процесс
    # уже мёртв, драйвер освобождает хендлы асинхронно.
    time.sleep(WINDIVERT_CLEANUP_DELAY)

    if not any_winws2_running():
        return

    # Живой winws2 после managed-остановки (или managed отсутствовал):
    # blanket kill - крайняя мера, фиксируем в логе разбор.
    if confirmed:
        _applog("tester_proc",
                "winws2 жив после подтверждённой смерти managed - blanket kill")
    else:
        _applog("tester_proc",
                "managed-процесс не подтверждён - blanket kill winws2")
    taskkill_safe("winws2.exe", allowed_paths)

    # Поллинг: ждём освобождения WinDivert вместо фиксированного sleep
    wait_windivert_free()
