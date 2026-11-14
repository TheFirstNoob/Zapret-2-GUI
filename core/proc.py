"""proc.py - единая обвязка чтения/остановки процессов (аудит #7 от 2026-10-14).

Раньше 9 обёрток tasklist и 5+ путей taskkill жили независимо, с разными
краевыми случаями локалей («No tasks» vs пустой stdout) и форматами
(CSV/таблица). Здесь один CSV-парсер: локализованные INFO-строки («Задачи
отсутствуют...») не содержат пар кавычек и отсеиваются естественно.

2026-11-14 (T19): основной путь чтения процессов - Toolhelp32
(CreateToolhelp32Snapshot) с TTL-кэшем ~1 c вместо tasklist. /api/status
больше не запускает два tasklist на каждый poll (186 мс -> единицы мс), а
ожидание смерти известных PID - OpenProcess+WaitForSingleObject (миллисекунды
вместо 20 x sleep(0.25)). Любой сбой/недоступность Win32-API (не-Windows,
сбой ctypes, отказ SCM-подобных прав) откатывает на прежний tasklist-путь -
поведение и контракт функций не меняются.

Контракт: функции НЕ бросают исключений; чтение при сбое отдаёт пусто,
убийство - bool успешного exit code taskkill (не гарантия мгновенной смерти).
"""
from __future__ import annotations

import ctypes
import subprocess
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

__all__ = ["image_pids", "image_running", "running_images", "kill_pid",
           "kill_image", "process_image_path", "kill_image_filtered",
           "image_processes", "wait_pids_exit", "invalidate_snapshot_cache"]

# ── Win32-константы (T19) ───────────────────────────────────────────
_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_WAIT_FAILED = 0xFFFFFFFF
_ERROR_ACCESS_DENIED = 5
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_MAX_WAIT_OBJECTS = 64
_PROCESS_NAME_CHARS = 260

# Кэш снимка: /api/status поллится каждые ~4 c, а конфликт/diagnostics зовут
# image_pids ещё чаще. 1 c - безопасный TTL: kill-пути принудительно берут
# свежий снимок (force=True), так что устаревший кэш не влияет на мутации.
_SNAPSHOT_TTL = 1.0

_snapshot_lock = threading.Lock()
_snapshot_at = 0.0
_snapshot_value: Optional[tuple[tuple[int, str], ...]] = None

_k32_lock = threading.Lock()
_k32_cached = None

# ── tasklist fallback (прежний путь, аудит #7) ──────────────────────

def _tasklist_image_pids(image_name: str, *, timeout: float = 6.0) -> list[int]:
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


def _tasklist_running_images(*, timeout: float = 10.0) -> list[str]:
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


# ── Toolhelp32 (T19): один снимок процессов на ~1 c ────────────────

def _kernel32():
    """Закэшированная ctypes-обвязка kernel32; исключение - не-Windows/сбой."""
    global _k32_cached
    with _k32_lock:
        if _k32_cached is None:
            import ctypes.wintypes as wt
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            _k32_cached = (ctypes, wt, kernel32)
        return _k32_cached


def _read_toolhelp_snapshot() -> Optional[list[tuple[int, str]]]:
    """[(pid, exe_name_lower)] через CreateToolhelp32Snapshot; None - недоступно."""
    try:
        ctypes_mod, wt, kernel32 = _kernel32()

        class PROCESSENTRY32W(ctypes_mod.Structure):
            _fields_ = [("dwSize", wt.DWORD),
                        ("cntUsage", wt.DWORD),
                        ("th32ProcessID", wt.DWORD),
                        ("th32DefaultHeapID", ctypes_mod.c_size_t),
                        ("th32ModuleID", wt.DWORD),
                        ("cntThreads", wt.DWORD),
                        ("th32ParentProcessID", wt.DWORD),
                        ("pcPriClassBase", ctypes_mod.c_long),
                        ("dwFlags", wt.DWORD),
                        ("szExeFile", wt.WCHAR * _PROCESS_NAME_CHARS)]

        kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        kernel32.Process32FirstW.argtypes = [
            wt.HANDLE, ctypes_mod.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.argtypes = [
            wt.HANDLE, ctypes_mod.POINTER(PROCESSENTRY32W)]
        kernel32.CloseHandle.argtypes = [wt.HANDLE]
        snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if not snap or snap == _INVALID_HANDLE_VALUE:
            return None
        out: list[tuple[int, str]] = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes_mod.sizeof(entry)
            ok = kernel32.Process32FirstW(snap, ctypes_mod.byref(entry))
            while ok:
                pid = int(entry.th32ProcessID)
                name = str(entry.szExeFile or "").lower()
                if pid > 0 and name:
                    out.append((pid, name))
                ok = kernel32.Process32NextW(snap, ctypes_mod.byref(entry))
        finally:
            kernel32.CloseHandle(snap)
        return out
    except Exception:  # noqa: BLE001  (не-Windows/ctypes -> tasklist fallback)
        return None


def snapshot_processes(*, force: bool = False) -> Optional[list[tuple[int, str]]]:
    """Снимок процессов [(pid, name_lower)] с кэшем ~1 c; None - API недоступно.

    Кэш НЕ обновляется при ошибке: вызывающий уходит на tasklist и не портит
    последний удачный снимок."""
    global _snapshot_at, _snapshot_value
    now = time.monotonic()
    with _snapshot_lock:
        if (not force and _snapshot_value is not None
                and now - _snapshot_at < _SNAPSHOT_TTL):
            return list(_snapshot_value)
        procs = _read_toolhelp_snapshot()
        if procs is None:
            return None
        _snapshot_value = tuple(procs)
        _snapshot_at = now
        return list(procs)


def invalidate_snapshot_cache() -> None:
    """Сбросить кэш снимка (тесты/мутирующие операции с path-фильтром)."""
    global _snapshot_at, _snapshot_value
    with _snapshot_lock:
        _snapshot_at = 0.0
        _snapshot_value = None


# ── Публичный контракт чтения (контракт прежний, путь ускорен) ──────

def image_pids(image_name: str, *, timeout: float = 6.0) -> list[int]:
    """PID'ы процессов с именем image_name (Toolhelp32, fallback tasklist)."""
    name = (image_name or "").lower()
    if not name:
        return []
    procs = snapshot_processes()
    if procs is not None:
        return [pid for pid, exe in procs if exe == name]
    return _tasklist_image_pids(image_name, timeout=timeout)


def image_running(image_name: str, *, timeout: float = 6.0) -> bool:
    """True, если процесс с таким именем запущен."""
    return bool(image_pids(image_name, timeout=timeout))


def running_images(*, timeout: float = 10.0) -> list[str]:
    """Имена всех процессов (нижний регистр) - конфликт-скан."""
    procs = snapshot_processes()
    if procs is not None:
        return [exe for _pid, exe in procs]
    return _tasklist_running_images(timeout=timeout)


def process_image_path(pid: int) -> Optional[str]:
    """Полный путь exe процесса (None - недоступно: права/процесс умер)."""
    try:
        ctypes_mod, _wt, kernel32 = _kernel32()
        kernel32.OpenProcess.restype = ctypes_mod.c_void_p
        kernel32.OpenProcess.argtypes = [
            ctypes_mod.c_ulong, ctypes_mod.c_int, ctypes_mod.c_ulong]
        kernel32.CloseHandle.argtypes = [ctypes_mod.c_void_p]
        kernel32.QueryFullProcessImageNameW.restype = ctypes_mod.c_int
        kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes_mod.c_void_p, ctypes_mod.c_ulong,
            ctypes_mod.c_wchar_p, ctypes_mod.POINTER(ctypes_mod.c_ulong)]
        h = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False,
                                 int(pid))
        if not h:
            return None
        try:
            buf = ctypes_mod.create_unicode_buffer(32768)
            size = ctypes_mod.c_ulong(len(buf))
            ok = kernel32.QueryFullProcessImageNameW(
                h, 0, buf, ctypes_mod.byref(size))
            return buf.value if ok else None
        finally:
            kernel32.CloseHandle(h)
    except Exception:  # noqa: BLE001
        return None


def image_processes(image_name: str, allowed_paths: Optional[Iterable[str]] = None,
                    *, timeout: float = 6.0,
                    force: bool = True) -> list[tuple[int, str]]:
    """[(pid, exe_path)] процессов image_name; allowed_paths фильтрует по пути.

    force=True (по умолчанию) - свежий снимок: мутирующие пути (kill/install)
    не должны опираться на устаревший кэш. Пустой allowed_paths = без фильтра."""
    name = (image_name or "").lower()
    if not name:
        return []
    procs = snapshot_processes(force=force)
    if procs is None:
        pids = _tasklist_image_pids(image_name, timeout=timeout)
    else:
        pids = [pid for pid, exe in procs if exe == name]
    allowed: Optional[set[str]] = None
    if allowed_paths is not None:
        allowed = {str(Path(p).resolve()).lower() for p in allowed_paths if p}
        if not allowed:
            allowed = None
    out: list[tuple[int, str]] = []
    for pid in pids:
        path = process_image_path(pid)
        if not path:
            continue
        if allowed is not None:
            try:
                resolved = str(Path(path).resolve()).lower()
            except OSError:
                continue
            if resolved not in allowed:
                continue
        out.append((pid, path))
    return out


# ── Остановка процессов ─────────────────────────────────────────────

def kill_pid(pid: int, *, timeout: float = 5.0) -> bool:
    """taskkill /F /PID; True только при успешном exit code taskkill."""
    try:
        r = subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def kill_image(image_name: str, *, timeout: float = 6.0) -> bool:
    """taskkill /F /IM; True только при успешном exit code taskkill."""
    try:
        r = subprocess.run(["taskkill", "/F", "/IM", image_name],
                           capture_output=True, timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def kill_image_filtered(image_name: str, allowed_paths: Iterable[str],
                        *, timeout: float = 6.0) -> list[int]:
    """Убить только те процессы image_name, чей exe входит в allowed_paths.

    Ревью 18.10: две копии GUI в разных папках больше не убивают движки друг
    друга. Пустой allowed_paths -> legacy kill_image (все процессы).
    Возвращает список убитых PID."""
    allowed = {str(Path(p).resolve()).lower() for p in allowed_paths if p}
    if not allowed:
        invalidate_snapshot_cache()
        before = image_pids(image_name, timeout=timeout)
        kill_image(image_name, timeout=timeout)
        invalidate_snapshot_cache()
        after = set(image_pids(image_name, timeout=timeout))
        return [pid for pid in before if pid not in after]
    killed: list[int] = []
    for pid, _path in image_processes(image_name, allowed, timeout=timeout,
                                      force=True):
        if kill_pid(pid, timeout=timeout):
            killed.append(pid)
    if killed:
        invalidate_snapshot_cache()
    return killed


# ── Ожидание смерти по PID (T19): WaitForSingleObject вместо tasklist-циклов

def _open_synchronize(pids: Iterable[int]) -> tuple[dict[int, int], list[int], list[int]]:
    """Открыть SYNCHRONIZE-хендлы: (handles, unknown_pids, gone_pids).

    unknown - процесс, вероятно, жив, но хендл не открылся (отказ в доступе);
    gone - PID уже не существует (ERROR_INVALID_PARAMETER), завершение можно
    считать подтверждённым."""
    handles: dict[int, int] = {}
    unknown: list[int] = []
    gone: list[int] = []
    try:
        ctypes_mod, _wt, kernel32 = _kernel32()
        kernel32.OpenProcess.restype = ctypes_mod.c_void_p
        kernel32.OpenProcess.argtypes = [
            ctypes_mod.c_ulong, ctypes_mod.c_int, ctypes_mod.c_ulong]
    except Exception:  # noqa: BLE001
        return handles, list(pids), gone
    for pid in pids:
        try:
            h = kernel32.OpenProcess(_SYNCHRONIZE, False, int(pid))
        except Exception:  # noqa: BLE001
            h = 0
        if h:
            handles[int(pid)] = int(h)
        else:
            try:
                err = ctypes_mod.get_last_error()
            except Exception:  # noqa: BLE001
                err = _ERROR_ACCESS_DENIED
            if err == _ERROR_ACCESS_DENIED:
                unknown.append(int(pid))
            else:
                gone.append(int(pid))
    return handles, unknown, gone


def _close_handles(handles: dict[int, int]) -> None:
    try:
        ctypes_mod, _wt, kernel32 = _kernel32()
        kernel32.CloseHandle.argtypes = [ctypes_mod.c_void_p]
        for h in handles.values():
            try:
                kernel32.CloseHandle(ctypes_mod.c_void_p(h))
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def _wait_handles(handles: dict[int, int], timeout: float) -> set[int]:
    """Ждать сигнализации хендлов; вернуть PID, по которым НЕ дождались.

    Хендлы закрываются здесь же (собственность функции)."""
    if not handles:
        return set()
    pending = list(handles)
    try:
        ctypes_mod, _wt, kernel32 = _kernel32()
        kernel32.WaitForMultipleObjects.restype = ctypes_mod.c_ulong
        kernel32.WaitForMultipleObjects.argtypes = [
            ctypes_mod.c_ulong,
            ctypes_mod.POINTER(ctypes_mod.c_void_p),
            ctypes_mod.c_int, ctypes_mod.c_ulong]
    except Exception:  # noqa: BLE001
        _close_handles(handles)
        return set(pending)
    deadline = time.monotonic() + max(0.0, float(timeout))
    try:
        while pending:
            batch = pending[:_MAX_WAIT_OBJECTS]
            arr = (ctypes_mod.c_void_p * len(batch))(
                *[ctypes_mod.c_void_p(handles[p]) for p in batch])
            left = deadline - time.monotonic()
            wait_ms = int(left * 1000) if left > 0 else 0
            rc = kernel32.WaitForMultipleObjects(
                len(batch), arr, False, max(0, wait_ms))
            if rc == _WAIT_TIMEOUT or rc == _WAIT_FAILED:
                break
            idx = int(rc) - _WAIT_OBJECT_0
            if 0 <= idx < len(batch):
                pending.remove(batch[idx])
            else:  # WAIT_ABANDONED_* и прочие - не считаем смертью процесса
                break
            if time.monotonic() >= deadline:
                break
    finally:
        _close_handles(handles)
    return set(pending)


def wait_pids_exit(pids: Iterable[int], *, timeout: float = 5.0) -> list[int]:
    """Ждать завершения известных PID (OpenProcess+WaitForSingleObject).

    Возвращает PID, по которым завершение НЕ подтверждено (жив или нет прав
    открыть хендл). Пустой список = все подтверждённо завершились.
    Если Win32-API недоступно - возвращает все PID (вызывающий откатывается на
    поллинг по имени, как раньше)."""
    wanted: list[int] = []
    for p in pids:
        try:
            ip = int(p)
        except (TypeError, ValueError):
            continue
        if ip > 0 and ip not in wanted:
            wanted.append(ip)
    if not wanted:
        return []
    handles, unknown, gone = _open_synchronize(wanted)
    if not handles and not unknown and not gone:
        # OpenProcess недоступен (не-Windows/сбой) -> честно "не подтверждено".
        return list(wanted)
    leftover = _wait_handles(handles, timeout)
    leftover.update(unknown)
    return [pid for pid in wanted if pid in leftover and pid not in gone]
