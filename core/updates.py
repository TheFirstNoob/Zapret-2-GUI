"""Non-intrusive update check.

Compares the local application version against a plain-text ``VERSION`` file
hosted in the GitHub repository.  Best effort by design: any network error,
timeout or parse failure silently results in "no update info" — the check
must never block or disturb the user.  Updates are only ever *recommended*
(a toast + dismissible banner in the GUI), never enforced.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Optional

from core.config import VERSION

# Single-line version file in the repository root, e.g. "Pre-Release 0.3".
# raw.githubusercontent may be unreachable in some networks — that's fine,
# the check fails silently.
VERSION_URL = "https://raw.githubusercontent.com/TheFirstNoob/Zapret-2-GUI/main/VERSION"
RELEASES_URL = "https://github.com/TheFirstNoob/Zapret-2-GUI/releases"

_CHECK_TIMEOUT = 5.0


def _version_key(version: str) -> tuple:
    """Extract a comparable key from a version string.

    'Pre-Release 0.10' -> (0, 10); unknown formats fall back to (0,) so they
    never compare as "newer" by accident.
    """
    m = re.search(r"(\d+)\.(\d+)", version or "")
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (0,)


def check_for_updates() -> dict:
    """Return update info: {current, latest, available, error, url}."""
    info = {
        "current": VERSION,
        "latest": "",
        "available": False,
        "error": None,
        "url": RELEASES_URL,
    }
    try:
        req = urllib.request.Request(VERSION_URL, headers={"User-Agent": "Zapret2GUI"})
        with urllib.request.urlopen(req, timeout=_CHECK_TIMEOUT) as r:
            latest = r.read(200).decode("utf-8", errors="replace").strip()
        if not latest:
            info["error"] = "empty VERSION file"
            return info
        info["latest"] = latest
        info["available"] = _version_key(latest) > _version_key(VERSION)
    except Exception as e:  # noqa: BLE001 — any failure must be silent
        info["error"] = str(e)[:120]
    return info
