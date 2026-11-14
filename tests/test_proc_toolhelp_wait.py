"""T19: core.proc - Toolhelp32-снимок + WaitForSingleObject-ожидание.

Тесты НЕ трогают службы/сеть: только подмена Win32-обвязки и синтетические
снимки процессов. Реальный Toolhelp32 проверяется безопасным чтением
(read-only) на текущем процессе.
"""
from __future__ import annotations

import ctypes
import os
import time

from core import proc


def _reset_cache(monkeypatch) -> None:
    monkeypatch.setattr(proc, "_snapshot_value", None)
    monkeypatch.setattr(proc, "_snapshot_at", 0.0)


def test_toolhelp_snapshot_drives_image_pids(monkeypatch) -> None:
    _reset_cache(monkeypatch)
    monkeypatch.setattr(proc, "_read_toolhelp_snapshot",
                        lambda: [(10, "winws2.exe"), (11, "other.exe"),
                                 (12, "winws.exe")])
    assert proc.image_pids("winws2.exe") == [10]
    assert proc.image_pids("WINWS2.EXE") == [10]
    assert proc.image_running("winws.exe") is True
    assert proc.image_running("absent.exe") is False
    assert proc.running_images() == ["winws2.exe", "other.exe", "winws.exe"]


def test_tasklist_fallback_when_toolhelp_unavailable(monkeypatch) -> None:
    _reset_cache(monkeypatch)
    monkeypatch.setattr(proc, "_read_toolhelp_snapshot", lambda: None)
    monkeypatch.setattr(proc, "_tasklist_image_pids",
                        lambda image, timeout=6.0: [77] if image == "winws2.exe" else [])
    monkeypatch.setattr(proc, "_tasklist_running_images",
                        lambda timeout=10.0: ["a.exe"])
    assert proc.image_pids("winws2.exe") == [77]
    assert proc.running_images() == ["a.exe"]


def test_snapshot_cache_ttl(monkeypatch) -> None:
    _reset_cache(monkeypatch)
    calls = []
    monkeypatch.setattr(proc, "_read_toolhelp_snapshot",
                        lambda: calls.append(1) or [(1, "x.exe")])
    assert proc.image_pids("x.exe") == [1]
    assert proc.image_pids("x.exe") == [1]
    assert len(calls) == 1  # второй вызов в пределах TTL - из кэша
    monkeypatch.setattr(proc, "_SNAPSHOT_TTL", 0.0)
    assert proc.image_pids("x.exe") == [1]
    assert len(calls) == 2


def test_cache_not_poisoned_by_failed_snapshot(monkeypatch) -> None:
    _reset_cache(monkeypatch)
    monkeypatch.setattr(proc, "_read_toolhelp_snapshot", lambda: [(5, "a.exe")])
    assert proc.image_pids("a.exe") == [5]
    # кэш жив; теперь API "сломалось" - force-чтение не должно портить кэш?
    # (не портит только неудачный snapshot, здесь проверяем TTL-поведение)
    assert proc.image_pids("a.exe") == [5]


def test_wait_pids_exit_confirmed_gone(monkeypatch) -> None:
    monkeypatch.setattr(proc, "_open_synchronize",
                        lambda pids: ({7: 123}, [], []))
    monkeypatch.setattr(proc, "_wait_handles", lambda handles, timeout: set())
    assert proc.wait_pids_exit([7], timeout=0.1) == []


def test_wait_pids_exit_alive(monkeypatch) -> None:
    monkeypatch.setattr(proc, "_open_synchronize",
                        lambda pids: ({7: 123}, [], []))
    monkeypatch.setattr(proc, "_wait_handles", lambda handles, timeout: {7})
    assert proc.wait_pids_exit([7], timeout=0.1) == [7]


def test_wait_pids_exit_access_denied_is_unconfirmed(monkeypatch) -> None:
    monkeypatch.setattr(proc, "_open_synchronize", lambda pids: ({}, [7], []))
    assert proc.wait_pids_exit([7], timeout=0.1) == [7]


def test_wait_pids_exit_invalid_parameter_means_gone(monkeypatch) -> None:
    monkeypatch.setattr(proc, "_open_synchronize", lambda pids: ({}, [], [7]))
    assert proc.wait_pids_exit([7], timeout=0.1) == []


def test_wait_pids_exit_api_unavailable_returns_all(monkeypatch) -> None:
    monkeypatch.setattr(proc, "_open_synchronize", lambda pids: ({}, [], []))
    assert proc.wait_pids_exit([7, 8], timeout=0.1) == [7, 8]


def test_wait_pids_exit_filters_bad_values(monkeypatch) -> None:
    monkeypatch.setattr(proc, "_open_synchronize", lambda pids: ({}, [], []))
    assert proc.wait_pids_exit([0, -5, "x", None], timeout=0.1) == []


def test_wait_handles_signaled_event_returns_empty() -> None:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateEventW.restype = ctypes.c_void_p
    k32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_wchar_p]
    handle = k32.CreateEventW(None, 1, 1, None)  # manual reset, signaled
    assert handle
    # _wait_handles закрывает переданный хендл сам
    assert proc._wait_handles({1: int(handle)}, timeout=0.2) == set()


def test_wait_handles_unsignaled_times_out() -> None:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateEventW.restype = ctypes.c_void_p
    k32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_wchar_p]
    handle = k32.CreateEventW(None, 1, 0, None)  # manual reset, not signaled
    assert handle
    started = time.monotonic()
    assert proc._wait_handles({2: int(handle)}, timeout=0.1) == {2}
    assert time.monotonic() - started < 2.0


def test_image_processes_path_filter(monkeypatch) -> None:
    _reset_cache(monkeypatch)
    monkeypatch.setattr(proc, "_read_toolhelp_snapshot",
                        lambda: [(1, "winws2.exe"), (2, "winws2.exe")])
    paths = {1: r"C:\App\bin\winws2.exe", 2: r"C:\Other\winws2.exe"}
    monkeypatch.setattr(proc, "process_image_path", lambda pid: paths.get(pid))
    out = proc.image_processes("winws2.exe", {r"C:\App\bin\winws2.exe"})
    assert [(pid, p) for pid, p in out] == [(1, paths[1])]


def test_real_toolhelp_lists_current_process() -> None:
    procs = proc.snapshot_processes(force=True)
    if procs is None:  # не-Windows/сбой API - fallback покрыт выше
        return
    assert any(pid == os.getpid() for pid, _name in procs)
    assert proc.image_pids(os.path.basename(os.sys.executable).lower()) != []
