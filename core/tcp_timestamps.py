from __future__ import annotations

import subprocess
import winreg
from typing import Optional

# TCP timestamps state on modern Windows lives in the NetTCPSetting
# templates ("Internet" default), NOT in the legacy Tcp1323Opts registry
# value.  On Win11 the legacy value can read 0x2 (timestamps "off") while
# the template says Enabled — the template is authoritative.
# ts-fooling (tcp_ts=...) needs timestamps ON.

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
    return bool(_ps_run(_PS_SET_ON if enabled else _PS_SET_OFF))


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
    """Make sure TCP timestamps are ON before the engine starts.

    ts-fooling (tcp_ts=...) silently does nothing when the OS has
    timestamps disabled.  Returns (ok, note).
    """
    if timestamps_enabled():
        return True, ""
    if _set_modern(True) or _set_legacy_netsh(True):
        if timestamps_enabled():
            return True, "TCP timestamps включены (были выключены — tcp_ts не работал)"
        return False, "timestamps включить не удалось"
    return False, "включить TCP timestamps не удалось (нужны права администратора)"


def restore_after_engine() -> str:
    """Restore the pre-session state if we changed it.  Idempotent."""
    if timestamps_enabled():
        return ""
    _set_modern(False) or _set_legacy_netsh(False)
    return ""