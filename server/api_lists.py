"""api_lists.py - домен «здоровье/правка списков» (аудит #1, Inc C).

Соглашение: (ctx: AppContext, ...) -> dict; исключения - только ApiError."""
from __future__ import annotations

from server.app_state import (AppContext, checkers_busy, get_root_dir)


def lists_health(ctx: AppContext) -> dict:
    try:
        from core import list_health
        report = list_health.check_health(get_root_dir())
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}
    return {"status": "ok", **report}


def lists_dedupe(ctx: AppContext) -> dict:
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    try:
        from core import list_health
        result = list_health.dedupe(get_root_dir())
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}
    return {"status": "ok", **result}


def lists_add_domain(ctx: AppContext, data: dict) -> dict:
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    mode = "exclude" if data.get("mode") == "exclude" else "include"
    try:
        from core import list_health
        result = list_health.add_domain(
            get_root_dir(), str(data.get("domain") or ""), mode)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}
    ok = result.get("result") in ("added", "moved", "already")
    if ok and mode == "include":
        # combined-файл (user+games) - то, на что ссылаются args
        try:
            from core import games as games_store
            games_store.sync_include_list(get_root_dir())
        except Exception:
            pass
    return {"status": "ok" if ok else "error", **result}
