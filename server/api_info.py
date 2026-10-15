"""api_info.py - информационные эндпоинты: версия, сборка, статус, профили.

Переехало из server.py (аудит #1, Inc C). Соглашение: (ctx, ...) -> dict."""
from __future__ import annotations

import sys

from core.config import VERSION
from server.app_state import (AppContext, get_controller, scan_winws_exe,
                              ui_presets, zapret1_installed)


def version(ctx: AppContext) -> dict:
    return {"status": "ok", "version": VERSION}


def app_info(ctx: AppContext) -> dict:
    """Техническая информация: версия, тип сборки, SHA256 exe, ключ OTA."""
    import hashlib
    from pathlib import Path as _Path
    from core import update_verify
    from core.utils import app_root
    frozen = bool(getattr(sys, "frozen", False))
    # portable = embeddable-рантайм рядом с приложением
    # (<...>/python/python(.w).exe); иначе - запуск из исходников
    # системным Python (аудит 2026-10: раньше он тоже звался portable).
    portable = bool(
        not frozen
        and _Path(sys.executable).parent.name.lower() == "python")
    info = {"version": VERSION,
            "frozen": frozen,
            "build": ("exe" if frozen else
                      "portable" if portable else "source"),
            "path": str(app_root()),
            "update_key": update_verify.pubkey_fingerprint(),
            "exe_sha256": ""}
    if info["frozen"]:
        try:
            h = hashlib.sha256()
            with open(sys.executable, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            info["exe_sha256"] = h.hexdigest()
        except OSError:
            pass
    return {"status": "ok", "info": info}


def status(ctx: AppContext) -> dict:
    controller = get_controller()
    status = controller.status()
    zapret1 = scan_winws_exe()
    profiles = ui_presets()
    return {
        "status": "ok",
        "zapret": {
            "running": status.running, "pid": status.pid,
            "strategy": status.strategy,
        },
        "zapret1": {**zapret1, "installed": zapret1_installed()},
        "profiles": profiles,
    }


def list_profiles(ctx: AppContext) -> dict:
    profiles = [
        {"name": name, "display_name": name, "description": "", "is_valid": True, "parse_error": "", "warnings": []}
        for name in ui_presets()
    ]
    return {"status": "ok", "profiles": profiles}
