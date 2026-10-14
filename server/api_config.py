"""api_config.py - домен «конфиг и настройки» (аудит #1, Inc C).

Соглашение: (ctx: AppContext, ...) -> dict; исключения - только ApiError."""
from __future__ import annotations

from core.config import VERSION
from server.app_state import AppContext, get_config_manager, get_root_dir


def get_config(ctx: AppContext) -> dict:
    cfg = get_config_manager().load()
    return {"status": "ok", "config": {
        "root_dir": cfg.root_dir,
        "last_profile": cfg.last_profile,
        "zapret1_dir": cfg.zapret1_dir,
        "zapret1_last_strategy": cfg.zapret1_last_strategy,
        "game_filter_mode": cfg.game_filter_mode,
        "discord_voice": cfg.discord_voice,
        "discord_voice_mode": cfg.discord_voice_mode,
        "winws2_debug": cfg.winws2_debug,
        "autohostlist": cfg.autohostlist,
        "ipset_catchall": cfg.ipset_catchall,
        "discord_alt": cfg.discord_alt,
        # fake_blob обязателен в ответе: фронт читает его при старте
        # (app.js loadConfig) и без него селект блока сбрасывается на
        # «Пресет (Google)», а следующий save/restart затирал бы настройку
        # (REVIEW_VERDICT.md §2.3).
        "fake_blob": cfg.fake_blob,
        "tour_done": cfg.tour_done,
        "notice_done": cfg.notice_done,
    }}


def save_config(ctx: AppContext, data: dict) -> dict:
    cfg = get_config_manager().load()
    if "last_profile" in data: cfg.last_profile = data["last_profile"]
    if "zapret1_dir" in data: cfg.zapret1_dir = data["zapret1_dir"]
    if "game_filter_mode" in data: cfg.game_filter_mode = data["game_filter_mode"]
    if "discord_voice" in data: cfg.discord_voice = bool(data["discord_voice"])
    if "discord_voice_mode" in data:
        mode = str(data["discord_voice_mode"]).lower()
        if mode in ("off", "fake", "udplen"):
            cfg.discord_voice_mode = mode
            cfg.discord_voice = mode != "off"  # совместимость со старыми сборками
    if "winws2_debug" in data: cfg.winws2_debug = bool(data["winws2_debug"])
    if "fake_blob" in data:
        fb = str(data["fake_blob"]).strip()
        if fb:
            blobs_dir = get_root_dir() / "blobs"
            alt = blobs_dir / f"tls_clienthello_{fb}.bin"
            if not alt.exists() and fb.startswith("blob_"):
                # цифро-ключи селект отдаёт как "blob_<key>" - проверяем
                # и алиас, иначе выбор молча не сохранялся (аудит 2026-10)
                alt = blobs_dir / f"tls_clienthello_{fb[5:]}.bin"
            if not alt.exists():
                return {"status": "error", "message": f"неизвестный блоб: {fb}"}
        cfg.fake_blob = fb
    if "autohostlist" in data: cfg.autohostlist = bool(data["autohostlist"])
    if "ipset_catchall" in data: cfg.ipset_catchall = bool(data["ipset_catchall"])
    if "discord_alt" in data: cfg.discord_alt = bool(data["discord_alt"])
    if "tour_done" in data: cfg.tour_done = bool(data["tour_done"])
    if "notice_done" in data: cfg.notice_done = bool(data["notice_done"])
    ok = get_config_manager().save(cfg)
    return {"status": "ok" if ok else "error"}


def settings_export(ctx: AppContext) -> dict:
    """Экспорт настроек: config + *-user.txt + юзерские пресеты → один zip."""
    from core.updater import export_settings_zip
    path = export_settings_zip(get_root_dir())
    if not path:
        return {"status": "error", "message": "Не удалось создать файл экспорта"}
    return {"status": "ok", "file": str(path), "name": path.name}


def settings_import(ctx: AppContext, data: dict) -> dict:
    """Импорт настроек из zip (base64): только юзер-файлы восстанавливаются."""
    import base64
    try:
        zip_data = base64.b64decode(data.get("data") or "")
    except Exception:
        return {"status": "error", "message": "Некорректный файл"}
    if not zip_data:
        return {"status": "error", "message": "Пустой файл"}
    from core.updater import import_settings_zip, read_settings_meta
    meta = read_settings_meta(zip_data)
    imported, skipped = import_settings_zip(zip_data, get_root_dir())
    note = ""
    ver = str(meta.get("version") or "")
    if ver and ver != VERSION:
        note = (f" Архив из версии {ver}: настройки перенесены, "
                "недостающие параметры взяты из текущей версии.")
    return {"status": "ok", "imported": imported,
            "skipped": skipped, "source_version": ver,
            "message": f"Восстановлено записей: {imported}." + note
                       + " Перезапустите программу, чтобы применилось."}
