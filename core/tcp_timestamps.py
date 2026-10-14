from __future__ import annotations

import subprocess
import threading
import winreg
from typing import Optional

# Состояние TCP timestamps на современных Windows живёт в шаблонах
# NetTCPSetting ("Internet" default), НЕ в legacy-реестре Tcp1323Opts.
# На Win11 legacy-значение может читаться как 0x2 (timestamps "off") при
# включённом шаблоне - авторитетен шаблон. ts-fooling (tcp_ts=...) требует
# включённых timestamps.

_KEY = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"
_VALUE = "Tcp1323Opts"
TS_BIT = 0x1

_PS_GET = ("Get-NetTCPSetting -SettingName Internet -ErrorAction SilentlyContinue | "
           "Select-Object -ExpandProperty Timestamps")
_PS_SET_ON = "Set-NetTCPSetting -SettingName Internet -Timestamps Enabled"
_PS_SET_OFF = "Set-NetTCPSetting -SettingName Internet -Timestamps Disabled"


def _ps_run(script: str, timeout: float = 10.0) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return (r.stdout or "").strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _modern_ts_state() -> Optional[bool]:
    out = _ps_run(_PS_GET)
    if out.lower().startswith("enabled"):
        return True
    if out.lower().startswith("disabled"):
        return False
    return None


def _legacy_ts_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _KEY) as k:
            val, _ = winreg.QueryValueEx(k, _VALUE)
            return bool(int(val) & TS_BIT)
    except OSError:
        return True


def timestamps_enabled() -> bool:
    """Состояние TCP timestamps (кэш на процесс: PS-чтение занимает 3-5с)."""
    global _ts_cache
    with _ts_lock:
        if _ts_cache is None:
            _ts_cache = _ts_read_uncached()
        return bool(_ts_cache)


def _ts_read_uncached() -> bool:
    modern = _modern_ts_state()
    if modern is not None:
        return modern
    return _legacy_ts_enabled()


# Кэш живёт на процесс: PowerShell-чтение ~3-5с раньше платилось НА КАЖДОМ
# старте движка (рестарты службы/обхода). Внешние изменения timestamps посреди
# сессии не отслеживаются - осознанный размен (мы сами их и включаем).
_ts_cache: Optional[bool] = None
_ts_lock = threading.Lock()


def _set_modern(enabled: bool) -> bool:
    # Set-NetTCPSetting ничего не печатает при успехе - судим по коду
    # возврата, затем подтверждаем авторитетным геттером.
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             _PS_SET_ON if enabled else _PS_SET_OFF],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            return False
    except (subprocess.TimeoutExpired, OSError):
        return False
    return _ts_read_uncached() is (True if enabled else False)


def _set_legacy_netsh(enabled: bool) -> bool:
    # encoding обязателен: вывод netsh локализован, а text=True без явной
    # кодировки на OEM-консоли (cp866) даёт UnicodeDecodeError - и он НЕ
    # ловится ниже, потому что прилетает на этапе разбора вывода. Раньше это
    # означало стектрейс вместо внятного сообщения уже ПОСЛЕ остановки
    # движка (enable_for_engine зовут из zapret_controller/service_manager
    # после stop()). Код возврата от локали не зависит - судим только по нему.
    try:
        r = subprocess.run(
            ["netsh", "int", "tcp", "set", "global",
             "timestamps=enabled" if enabled else "timestamps=disabled"],
            capture_output=True, text=True, timeout=10,
            encoding="oem", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def enable_for_engine() -> tuple[bool, str]:
    """Гарантирует включённые TCP timestamps перед стартом движка.

    ts-fooling (tcp_ts=...) молча ничего не делает при выключенных
    timestamps в ОС.  Возвращает (ok, note).  Состояние кэшируется на
    процесс (см. _ts_cache) - горячий путь старта больше не платит PS.
    """
    global _ts_cache
    with _ts_lock:
        if _ts_cache is None:
            _ts_cache = _ts_read_uncached()
        if _ts_cache:
            return True, ""
        if _set_modern(True):
            _ts_cache = True
            return True, "TCP timestamps включены (были выключены - tcp_ts не работал)"
        if _set_legacy_netsh(True) and _ts_read_uncached():
            # netsh мог примениться только к legacy-пути - подтверждаем чтением
            _ts_cache = True
            return True, "TCP timestamps включены (были выключены - tcp_ts не работал)"
        _ts_cache = False
        return False, "включить TCP timestamps не удалось (нужны права администратора)"