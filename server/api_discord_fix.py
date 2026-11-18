"""Discord/Cloudflare fix (0.12): API мастера.

Действия меняют system hosts + NRPT + локальный DNS :53, поэтому только
после явного согласия пользователя и под operation_guard.
"""
from __future__ import annotations

from pathlib import Path

from core import discord_fix
from server.app_state import AppContext, get_root_dir, operation_guard, ui_debug


def _root(ctx: AppContext) -> Path:
    return get_root_dir()


def discord_fix_status(ctx: AppContext) -> dict:
    try:
        return {"status": "ok", **discord_fix.status(_root(ctx))}
    except Exception as e:  # noqa: BLE001
        ui_debug(f"discord_fix status: {e}")
        return {"status": "error", "message": str(e)}


def discord_fix_scan(ctx: AppContext) -> dict:
    try:
        return {"status": "ok", **discord_fix.scan_hosts(_root(ctx))}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}


@operation_guard("discord-fix")
def discord_fix_enable(ctx: AppContext, data: dict) -> dict:
    try:
        ip = str((data or {}).get("ip") or "").strip() or None
        return {"status": "ok", "message": "Discord/Cloudflare обход включён",
                **discord_fix.enable(_root(ctx), ip=ip)}
    except Exception as e:  # noqa: BLE001
        ui_debug(f"discord_fix enable: {e}")
        return {"status": "error", "message": str(e)}


@operation_guard("discord-fix")
def discord_fix_rotate(ctx: AppContext) -> dict:
    try:
        return {"status": "ok", "message": "Candidate IP сменён",
                **discord_fix.rotate(_root(ctx))}
    except Exception as e:  # noqa: BLE001
        ui_debug(f"discord_fix rotate: {e}")
        return {"status": "error", "message": str(e)}


@operation_guard("discord-fix")
def discord_fix_disable(ctx: AppContext) -> dict:
    try:
        return {"status": "ok", "message": "Discord/Cloudflare обход выключен",
                **discord_fix.disable(_root(ctx))}
    except Exception as e:  # noqa: BLE001
        ui_debug(f"discord_fix disable: {e}")
        return {"status": "error", "message": str(e)}
