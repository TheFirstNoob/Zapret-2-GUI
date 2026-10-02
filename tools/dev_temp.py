"""Чистка temp-профилей браузера, которые оставляют dev-инструменты UI.

В программу не входит: у пользователей таких каталогов не бывает - это
dev-забота. Запуск вручную: `python tools/dev_temp.py` - подчистит хвосты
старше 24ч от UI-скриншотов и старых дамп-скриптов (кейс 2026-10-01: такие
профили накопили ~40 ГБ).
"""
from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

# Префиксы каталогов, которые создают наши dev-инструменты в %TEMP%:
# tools/_ui_shots.py (z2edge_*), старые chk_*.mjs (edge-chk-*),
# ui_dump* (edge-ui-dump-*), smoke-скрипты (spcb-browser-smoke-*).
PROFILE_PREFIXES = (
    "z2edge_",
    "edge-ui-dump-",
    "edge-chk-",
    "spcb-browser-smoke-",
)


def cleanup_stale_temp_profiles(
        prefixes: tuple[str, ...] = PROFILE_PREFIXES,
        max_age_h: float = 24.0) -> list[str]:
    """Удалить старые профили по префиксам имён.

    Свежие каталоги не трогаем: может работать параллельный запуск.
    Возвращает имена удалённых каталогов.
    """
    tmp = Path(tempfile.gettempdir())
    now = time.time()
    removed: list[str] = []
    try:
        entries = list(tmp.iterdir())
    except OSError:
        return removed
    for p in entries:
        try:
            if not p.is_dir() or p.is_symlink():
                continue
            if not any(p.name.startswith(pref) for pref in prefixes):
                continue
            if now - p.stat().st_mtime < max_age_h * 3600:
                continue
            shutil.rmtree(p, ignore_errors=True)
            if not p.exists():
                removed.append(p.name)
        except OSError:
            continue
    return removed


if __name__ == "__main__":
    freed = cleanup_stale_temp_profiles()
    print(f"удалено профилей: {len(freed)}")
    for n in freed:
        print("  ", n)
