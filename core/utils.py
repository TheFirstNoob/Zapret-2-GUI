from __future__ import annotations

import ctypes
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
