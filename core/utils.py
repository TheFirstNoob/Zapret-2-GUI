from __future__ import annotations

import ctypes
import subprocess
import tempfile
from pathlib import Path


def short_path(path: Path) -> Path:
    """Return the Windows short (8.3) path for an existing file/directory.
    Falls back to the original path if short names are disabled or unavailable.
    """
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


def run_quiet(cmd: list[str], timeout: int = 30) -> None:
    """Run a command silently; failures are ignored (best-effort helpers)."""
    try:
        subprocess.run(cmd, capture_output=True, text=True, encoding="oem",
                       errors="replace", timeout=timeout,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass
