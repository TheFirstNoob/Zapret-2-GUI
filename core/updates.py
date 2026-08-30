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
API_URL = "https://api.github.com/repos/TheFirstNoob/Zapret-2-GUI/contents/VERSION"
RELEASES_URL = "https://github.com/TheFirstNoob/Zapret-2-GUI/releases"

_CHECK_TIMEOUT = 5.0
_UA = {"User-Agent": "Zapret2GUI"}


def _version_key(version: str) -> tuple:
    """Extract a comparable key from a version string.

    'Pre-Release 0.10' -> (0, 10); unknown formats fall back to (0,) so they
    never compare as "newer" by accident.
    """
    m = re.search(r"(\d+)\.(\d+)", version or "")
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (0,)


def _fetch_latest_raw() -> Optional[str]:
    """Latest version from the raw VERSION file (primary source)."""
    req = urllib.request.Request(VERSION_URL, headers=_UA)
    with urllib.request.urlopen(req, timeout=_CHECK_TIMEOUT) as r:
        return r.read(200).decode("utf-8", errors="replace").strip()


def _fetch_latest_api() -> Optional[str]:
    """Fallback via the GitHub API — raw.githubusercontent.com is frequently
    blocked/throttled on Russian ISPs (185.199.108.0/22 blackholed), while
    api.github.com (140.82.121.x) usually survives.  Uses the contents
    endpoint (works even without a published GitHub Release)."""
    req = urllib.request.Request(
        API_URL, headers={**_UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=_CHECK_TIMEOUT) as r:
        data = json.loads(r.read(8192).decode("utf-8", errors="replace"))
    import base64
    content = data.get("content") or ""
    try:
        text = base64.b64decode(content).decode("utf-8", errors="replace").strip()
    except Exception:
        return None
    return text or None


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
        latest = None
        try:
            latest = _fetch_latest_raw()
        except Exception:
            latest = _fetch_latest_api()  # raw blocked — API fallback
        if not latest:
            info["error"] = "empty VERSION file"
            return info
        info["latest"] = latest
        info["available"] = _version_key(latest) > _version_key(VERSION)
    except Exception as e:  # noqa: BLE001 — any failure must be silent
        info["error"] = str(e)[:120]
    return info
