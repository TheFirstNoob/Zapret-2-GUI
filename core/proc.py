"""proc.py - единая обвязка tasklist/taskkill (аудит #7 от 2026-10-14).

Раньше 9 обёрток tasklist и 5+ путей taskkill жили независимо, с разными
краевыми случаями локалей («No tasks» vs пустой stdout) и форматами
(CSV/таблица). Здесь один CSV-парсер: локализованные INFO-строки («Задачи
отсутствуют...») не содержат пар кавычек и отсеиваются естественно.

Контракт: функции НЕ бросают исключений; чтение при сбое отдаёт пусто,
убийство - bool (команда выполнена; не гарантия смерти процесса).
"""
from __future__ import annotations

import ctypes
import subprocess
from pathlib import Path
from typing import Iterable, Optional

__all__ = ["image_pids", "image_running", "running_images", "kill_pid",
           "kill_image", "process_image_path", "kill_image_filtered"]


def image_pids(image_name: str, *, timeout: float = 6.0) -> list[int]:
    """PID'ы процессов с именем image_name (CSV; локаль-независимо)."""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="oem", errors="replace",
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:  # noqa: BLE001
        return []
    name = image_name.lower()
    pids: list[int] = []
    for line in (r.stdout or "").splitlines():
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 2 and parts[0].lower() == name:
            try:
                pids.append(int(parts[1]))
            except ValueError:
                continue
    return pids


def image_running(image_name: str, *, timeout: float = 6.0) -> bool:
    """True, если процесс с таким именем запущен."""
    return bool(image_pids(image_name, timeout=timeout))


def running_images(*, timeout: float = 10.0) -> list[str]:
    """Имена всех процессов (нижний регистр, порядок tasklist) - конфликт-скан."""
    try:
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="oem", errors="replace",
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for line in (r.stdout or "").splitlines():
        parts = line.split(",")
        if parts and parts[0].strip('"'):
            out.append(parts[0].strip('"').lower())
    return out


def kill_pid(pid: int, *, timeout: float = 5.0) -> bool:
    """taskkill /F /PID; True - команда выполнена (не гарантия смерти)."""
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True,
                       timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except Exception:  # noqa: BLE001
        return False


def kill_image(image_name: str, *, timeout: float = 6.0) -> bool:
    """taskkill /F /IM; True - команда выполнена (не гарантия смерти)."""
    try:
        subprocess.run(["taskkill", "/F", "/IM", image_name], capture_output=True,
                       timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except Exception:  # noqa: BLE001
        return False


def process_image_path(pid: int) -> Optional[str]:
    """Полный путь exe процесса (None - недоступно: права/процесс умер)."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_ulong(len(buf))
            ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
            return buf.value if ok else None
        finally:
            k32.CloseHandle(h)
    except Exception:  # noqa: BLE001
        return None


def kill_image_filtered(image_name: str, allowed_paths: Iterable[str],
                        *, timeout: float = 6.0) -> list[int]:
    """Убить только те процессы image_name, чей exe входит в allowed_paths.

    Ревью 18.10: две копии GUI в разных папках больше не убивают движки друг
    друга. Пустой allowed_paths -> legacy kill_image (все процессы).
    Возвращает список убитых PID."""
    allowed = {str(Path(p).resolve()).lower() for p in allowed_paths if p}
    if not allowed:
        kill_image(image_name, timeout=timeout)
        return image_pids(image_name, timeout=timeout)
    killed: list[int] = []
    for pid in image_pids(image_name, timeout=timeout):
        path = process_image_path(pid)
        if not path:
            continue
        try:
            resolved = str(Path(path).resolve()).lower()
        except OSError:
            continue
        if resolved in allowed and kill_pid(pid, timeout=timeout):
            killed.append(pid)
    return killed
