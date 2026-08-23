from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except (AttributeError, OSError):
        return False


def relaunch_as_admin() -> bool:
    if is_admin():
        return True
    try:
        args = " ".join(
            f'"{a}"' if " " in a else a for a in sys.argv[1:]
        )
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{sys.argv[0]}" {args}', None, 1
        )
        return True
    except (AttributeError, OSError):
        return False


def ensure_admin() -> None:
    if not is_admin():
        relaunch_as_admin()
        sys.exit(0)


# ── Privilege helpers ──
# WinDivert driver loading requires SeLoadDriverPrivilege enabled in the token.
# UAC-elevated Python processes often have it disabled; enable it before spawning winws2.

SE_PRIVILEGE_ENABLED = 0x00000002
TOKEN_QUERY = 0x0008
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_LINKED_TOKEN = 19


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_long)]


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", _LUID), ("Attributes", ctypes.c_ulong)]


class _TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", ctypes.c_ulong), ("Privileges", _LUID_AND_ATTRIBUTES * 1)]


# ── Fix ctypes 64-bit HANDLE truncation ──
# ctypes.windll defaults to c_int (32-bit) for return types and parameters.
# HANDLE is 64-bit on x64 → must set restype/argtypes explicitly.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=False)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=False)

_kernel32.GetCurrentProcess.restype = wintypes.HANDLE

_kernel32.SetLastError.argtypes = [ctypes.c_ulong]
_kernel32.SetLastError.restype = None

_kernel32.GetLastError.restype = ctypes.c_ulong

_advapi32.OpenProcessToken.restype = wintypes.BOOL
_advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, ctypes.c_ulong, ctypes.POINTER(wintypes.HANDLE)]

_advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
_advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(_LUID)]

_advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL
_advapi32.AdjustTokenPrivileges.argtypes = [
    wintypes.HANDLE, wintypes.BOOL, ctypes.c_void_p, ctypes.c_ulong,
    ctypes.c_void_p, ctypes.c_void_p,
]

_advapi32.GetTokenInformation.restype = wintypes.BOOL
_advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong),
]


def _lookup_privilege_luid(name: str) -> _LUID:
    luid = _LUID()
    if not _advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
        raise ctypes.WinError()
    return luid


def enable_privilege(name: str) -> bool:
    try:
        process = _kernel32.GetCurrentProcess()
        token = wintypes.HANDLE()
        _kernel32.SetLastError(0)
        if not _advapi32.OpenProcessToken(process, TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)):
            err = _kernel32.GetLastError()
            print(f"[privilege] OpenProcessToken failed: {err}")
            return False

        luid = _lookup_privilege_luid(name)
        tp = _TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED

        _kernel32.SetLastError(0)
        ret = _advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), ctypes.sizeof(tp), None, None)
        last_err = _kernel32.GetLastError()
        print(f"[privilege] AdjustTokenPrivileges ret={ret}, last_err={last_err}")
        if last_err == 0:
            return True

        # ── Fallback: Try with the linked token (full admin token) ──
        linked_token = wintypes.HANDLE()
        try:
            size = ctypes.c_ulong(0)
            _advapi32.GetTokenInformation(token, TOKEN_LINKED_TOKEN, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if _advapi32.GetTokenInformation(token, TOKEN_LINKED_TOKEN, buf, size, ctypes.byref(size)):
                linked_token = ctypes.cast(buf, ctypes.POINTER(wintypes.HANDLE)).contents
                if linked_token:
                    _kernel32.SetLastError(0)
                    ret2 = _advapi32.AdjustTokenPrivileges(linked_token, False, ctypes.byref(tp), ctypes.sizeof(tp), None, None)
                    err2 = _kernel32.GetLastError()
                    print(f"[privilege] linked token AdjustTokenPrivileges ret={ret2}, last_err={err2}")
                    return err2 == 0
                print(f"[privilege] linked token not found")
        except Exception as e:
            print(f"[privilege] linked token exception: {e}")

        return False
    except Exception as e:
        print(f"[privilege] exception: {e}")
        return False


def get_enabled_privileges() -> list[str]:
    try:
        process = _kernel32.GetCurrentProcess()
        token = wintypes.HANDLE()
        if not _advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return []

        size = ctypes.c_ulong(0)
        _advapi32.GetTokenInformation(token, 3, None, 0, ctypes.byref(size))
        buf = (ctypes.c_byte * size.value)()
        if not _advapi32.GetTokenInformation(token, 3, ctypes.byref(buf), size, ctypes.byref(size)):
            return []

        count = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ulong)).contents.value
        enabled = []
        offset = ctypes.sizeof(ctypes.c_ulong)
        luid_size = ctypes.sizeof(_LUID)
        _LookupPrivilegeNameW = _advapi32.LookupPrivilegeNameW
        _LookupPrivilegeNameW.restype = wintypes.BOOL
        _LookupPrivilegeNameW.argtypes = [
            wintypes.LPCWSTR, ctypes.POINTER(_LUID), wintypes.LPWSTR,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        for i in range(count):
            luid_ptr = ctypes.cast(ctypes.byref(buf, offset), ctypes.POINTER(_LUID))
            attr_ptr = ctypes.cast(ctypes.byref(buf, offset + luid_size), ctypes.POINTER(ctypes.c_ulong))
            if attr_ptr.contents.value & SE_PRIVILEGE_ENABLED:
                name_buf = ctypes.create_unicode_buffer(256)
                name_len = ctypes.c_ulong(256)
                if _LookupPrivilegeNameW(None, luid_ptr, name_buf, ctypes.byref(name_len)):
                    enabled.append(name_buf.value)
            offset += luid_size + ctypes.sizeof(ctypes.c_ulong)
        return enabled
    except Exception:
        return []
