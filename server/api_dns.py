"""api_dns.py — быстрые DNS-профили (Основной/Резервный).

Изменение системного DNS — явное действие пользователя: применить профиль
или вернуть исходное состояние. Серверы не меняются автоматически.
"""
from __future__ import annotations

from dataclasses import replace

from core import dns_manager
from server.app_state import (AppContext, operation_guard, get_config_manager)
from server.api_config import _CONFIG_LOCK


def _cfg_payload(cfg, state: dict) -> dict:
    return {
        "status": "ok",
        "state": state,
        "active": dns_manager.active_profile(cfg, state) if state.get("ok") else "unknown",
        "profiles": dns_manager.profiles_payload(cfg),
    }


def _parse_profiles(data: dict):
    raw = data.get("profiles")
    if not isinstance(raw, dict):
        return None
    fields = {}
    for key, p1, p2 in (
        ("main", "dns_main_primary", "dns_main_secondary"),
        ("reserve", "dns_reserve_primary", "dns_reserve_secondary"),
    ):
        item = raw.get(key)
        if not isinstance(item, dict):
            raise dns_manager.DnsError(f"Некорректный профиль DNS: {key}")
        primary = str(item.get("primary") or "").strip()
        secondary = str(item.get("secondary") or "").strip()
        servers = dns_manager.normalize_servers(primary, secondary)
        fields[p1] = servers[0]
        fields[p2] = servers[1] if len(servers) > 1 else ""
    return fields


def _save_profiles(fields: dict) -> None:
    with _CONFIG_LOCK:
        cfg = get_config_manager().load()
        new_cfg = replace(cfg, **fields)
        if not get_config_manager().save(new_cfg):
            raise dns_manager.DnsError("Не удалось сохранить DNS-профили")


def dns_status(ctx: AppContext) -> dict:
    cfg = get_config_manager().load()
    try:
        state = dns_manager.current_status()
    except Exception as e:  # noqa: BLE001
        state = {"ok": False, "error": str(e), "servers": []}
    return _cfg_payload(cfg, state)


@operation_guard("dns")
def dns_apply(ctx: AppContext, data: dict) -> dict:
    if not isinstance(data, dict):
        return {"status": "error", "message": "JSON body должен быть объектом"}
    try:
        profile = str(data.get("profile") or "main").lower()
        if profile not in ("main", "reserve"):
            return {"status": "error", "message": "Неизвестный DNS-профиль"}
        fields = _parse_profiles(data)
        if fields:
            _save_profiles(fields)
        cfg = get_config_manager().load()
        state = dns_manager.apply_profile(ctx.root_dir, cfg, profile)
        return _cfg_payload(cfg, state)
    except dns_manager.DnsError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Ошибка DNS: {type(e).__name__}: {e}"}


@operation_guard("dns")
def dns_reset(ctx: AppContext) -> dict:
    cfg = get_config_manager().load()
    try:
        state = dns_manager.reset(ctx.root_dir)
        return _cfg_payload(cfg, state)
    except dns_manager.DnsError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Ошибка DNS: {type(e).__name__}: {e}"}


def dns_save(ctx: AppContext, data: dict) -> dict:
    if not isinstance(data, dict):
        return {"status": "error", "message": "JSON body должен быть объектом"}
    try:
        fields = _parse_profiles(data)
        if not fields:
            return {"status": "error", "message": "Нет профилей DNS"}
        _save_profiles(fields)
        cfg = get_config_manager().load()
        return _cfg_payload(cfg, dns_manager.current_status())
    except dns_manager.DnsError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Ошибка DNS: {type(e).__name__}: {e}"}

