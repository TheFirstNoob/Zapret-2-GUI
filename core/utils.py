from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile
from pathlib import Path


def short_path(path: Path) -> Path:
    """Windows short (8.3) path; falls back to the original when short
    names are disabled or unavailable."""
    try:
        long_name = str(path.resolve())
        buf = ctypes.create_unicode_buffer(260)
        res = ctypes.windll.kernel32.GetShortPathNameW(long_name, buf, 260)
        if res and res < 260:
            return Path(buf.value)
    except Exception:
        pass
    return path


def get_temp_dir() -> Path:
    """Stable temp dir for probe artifacts (probe etl/txt, reports)."""
    d = Path(tempfile.gettempdir()) / "zapret2_probe"
    d.mkdir(exist_ok=True)
    return d


def known_desktop_dir() -> Path:
    """Реальный рабочий стол через SHGetKnownFolderPath (учитывает
    OneDrive-редирект Known Folder). Фолбэк — профиль\\Desktop.

    Явные argtypes/restype — best practice ctypes на x64 (сигнатуры
    снимают вопросы по умолчанию)."""
    try:
        import ctypes

        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort),
                        ("Data4", ctypes.c_ubyte * 8)]

        g = _GUID()
        # FOLDERID_Desktop {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
        g.Data1, g.Data2, g.Data3 = 0xB4BFCC3A, 0xDB2C, 0x4C24
        g.Data4 = (ctypes.c_ubyte * 8)(
            0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41)
        shell32 = ctypes.windll.shell32
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_GUID), ctypes.c_ulong,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.HRESULT
        buf = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(
                ctypes.byref(g), 0, None, ctypes.byref(buf)) == 0:
            path = Path(buf.value).resolve()
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return path
    except (OSError, AttributeError):
        pass
    return (Path(os.path.expanduser("~")) / "Desktop").resolve()


def run_quiet(cmd: list[str], timeout: int = 30) -> None:
    """Run a command silently; failures are ignored (best-effort helpers)."""
    try:
        subprocess.run(cmd, capture_output=True, text=True, encoding="oem",
                       errors="replace", timeout=timeout,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass