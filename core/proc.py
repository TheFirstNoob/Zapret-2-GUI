"""proc.py - единая обвязка tasklist/taskkill (аудит #7 от 2026-10-14).

Раньше 9 обёрток tasklist и 5+ путей taskkill жили независимо, с разными
краевыми случаями локалей («No tasks» vs пустой stdout) и форматами
(CSV/таблица). Здесь один CSV-парсер: локализованные INFO-строки («Задачи
отсутствуют...») не содержат пар кавычек и отсеиваются естественно.

Контракт: функции НЕ бросают исключений; чтение при сбое отдаёт пусто,
убийство - bool (команда выполнена; не гарантия смерти процесса).
"""
from __future__ import annotations

import subprocess

__all__ = ["image_pids", "image_running", "running_images", "kill_pid", "kill_image"]


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
