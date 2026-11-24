"""YouTube GGC test worker API: session-only, default off."""
from __future__ import annotations

from pathlib import Path

from core import youtube_fix
from server.app_state import AppContext, get_root_dir, operation_guard, ui_debug


def _root(ctx: AppContext) -> Path:
    return get_root_dir()


def youtube_fix_status(ctx: AppContext) -> dict:
    try:
        return {"status": "ok", **youtube_fix.status(_root(ctx))}
    except Exception as e:  # noqa: BLE001
        ui_debug(f"youtube_fix status: {e}")
        return {"status": "error", "message": str(e)}


@operation_guard("youtube-fix")
def youtube_fix_enable(ctx: AppContext, data: dict) -> dict:
    try:
        ip = str((data or {}).get("ip") or "").strip()
        return {"status": "ok", "message": "YouTube GGC test worker включён",
                **youtube_fix.enable(_root(ctx), ip=ip)}
    except Exception as e:  # noqa: BLE001
        ui_debug(f"youtube_fix enable: {e}")
        return {"status": "error", "message": str(e)}


@operation_guard("youtube-fix")
def youtube_fix_rotate(ctx: AppContext) -> dict:
    try:
        return {"status": "ok", "message": "Google edge сменён",
                **youtube_fix.rotate(_root(ctx))}
    except Exception as e:  # noqa: BLE001
        ui_debug(f"youtube_fix rotate: {e}")
        return {"status": "error", "message": str(e)}


@operation_guard("youtube-fix")
def youtube_fix_disable(ctx: AppContext) -> dict:
    try:
        return {"status": "ok", "message": "YouTube GGC test worker выключен",
                **youtube_fix.disable(_root(ctx))}
    except Exception as e:  # noqa: BLE001
        ui_debug(f"youtube_fix disable: {e}")
        return {"status": "error", "message": str(e)}
