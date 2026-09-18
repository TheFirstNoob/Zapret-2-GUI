from __future__ import annotations

import subprocess
import winreg
from typing import Optional

# Состояние TCP timestamps на современных Windows живёт в шаблонах
# NetTCPSetting ("Internet" default), НЕ в legacy-реестре Tcp1323Opts.
# На Win11 legacy-значение может читаться как 0x2 (timestamps "off") при
# включённом шаблоне — авторитетен шаблон. ts-fooling (tcp_ts=...) требует
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
    modern = _modern_ts_state()
    if modern is not None:
        return modern
    return _legacy_ts_enabled()


def _set_modern(enabled: bool) -> bool:
    # Set-NetTCPSetting ничего не печатает при успехе — судим по коду
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
    return timestamps_enabled() is (True if enabled else False)


def _set_legacy_netsh(enabled: bool) -> bool:
    try:
        r = subprocess.run(
            ["netsh", "int", "tcp", "set", "global",
             "timestamps=enabled" if enabled else "timestamps=disabled"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def enable_for_engine() -> tuple[bool, str]:
    """Гарантирует включённые TCP timestamps перед стартом движка.

    ts-fooling (tcp_ts=...) молча ничего не делает при выключенных
    timestamps в ОС.  Возвращает (ok, note).
    """
    if timestamps_enabled():
        return True, ""
    if _set_modern(True) or _set_legacy_netsh(True):
        if timestamps_enabled():
            return True, "TCP timestamps включены (были выключены — tcp_ts не работал)"
        return False, "timestamps включить не удалось"
    return False, "включить TCP timestamps не удалось (нужны права администратора)"