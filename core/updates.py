"""Ненавязчивая проверка обновлений.

Сравнивает локальную версию с текстовым файлом ``VERSION`` в GitHub-репо.
По замыслу best-effort: любая ошибка сети/таймаут/парсинг молча дают «нет
данных об обновлении» - проверка не должна мешать пользователю. Обновление
только *рекомендуется* (тост + закрываемый баннер в GUI), не навязывается.
"""
from __future__ import annotations

import re
import urllib.request
from typing import Optional

from core.config import VERSION

# Однострочный VERSION в корне репозитория, например "Pre-Release 0.3".
# raw.githubusercontent может быть недоступен в некоторых сетях - это ок,
# проверка молча падает.
VERSION_URL = "https://raw.githubusercontent.com/TheFirstNoob/Zapret-2-GUI/main/VERSION"
# Зеркало того же файла через jsDelivr: работает в сетях, где raw режется,
# и НЕ имеет лимитов GitHub API (api.github.com: 60 запросов/час на IP -
# при общем/проксированном IP лимит выедается чужими запросами).
MIRROR_VERSION_URL = ("https://cdn.jsdelivr.net/gh/TheFirstNoob/Zapret-2-GUI"
                      "@main/VERSION")
RELEASES_URL = "https://github.com/TheFirstNoob/Zapret-2-GUI/releases"
# jsDelivr отдаёт файлы репо с другого CDN - работает даже в сетях,
# где raw/objects.githubusercontent заблокированы по IP.
MIRROR_URL = ("https://cdn.jsdelivr.net/gh/TheFirstNoob/Zapret-2-GUI@main/"
              "Windows%20build/Zapret2GUI.zip")

_CHECK_TIMEOUT = 5.0
_UA = {"User-Agent": "Zapret2GUI"}


def version_key(version: str) -> tuple:
    """Сравнимый ключ из строки версии.

    'Pre-Release 0.10' -> (0, 10); неизвестный формат -> (0,), чтобы он
    случайно не оказался «новее».
    """
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version or "")
    if m:
        key = (int(m.group(1)), int(m.group(2)))
        return key + ((int(m.group(3)),) if m.group(3) else ())
    return (0,)


def tag_from_version(version: str) -> str:
    """Конвенция тегов релизов (2026-09-13): только «Pre-Release-X.Y.Z»
    (пробел → дефис). Теги вида «0.7.1-hotfix» ломали порядок списка -
    от них отказались."""
    return (version or "").strip().replace(" ", "-")


def _fetch_latest_raw() -> Optional[str]:
    """Последняя версия из raw VERSION (основной источник)."""
    req = urllib.request.Request(VERSION_URL, headers=_UA)
    with urllib.request.urlopen(req, timeout=_CHECK_TIMEOUT) as r:
        return r.read(200).decode("utf-8", errors="replace").strip()


def _fetch_latest_mirror() -> Optional[str]:
    """Fallback через jsDelivr-зеркало: raw.githubusercontent.com часто
    блокируется/режется у российских провайдеров (185.199.108.0/22 в
    blackhole). Зеркало отдаёт тот же файл репозитория, но без лимитов
    GitHub API."""
    req = urllib.request.Request(MIRROR_VERSION_URL, headers=_UA)
    with urllib.request.urlopen(req, timeout=_CHECK_TIMEOUT) as r:
        return r.read(200).decode("utf-8", errors="replace").strip()


def merge_version_sources(raw: Optional[str],
                          mirror: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Сверить независимые источники версии (raw/зеркало). Оба доступны и
    расходятся → (None, причина): возможна подмена, апдейт не предлагаем.
    Возвращает (версия|None, ошибка|None)."""
    raw = (raw or "").strip() or None
    mirror = (mirror or "").strip() or None
    if raw and mirror and raw != mirror:
        return None, "источники версии расходятся"
    latest = raw or mirror
    if not latest:
        return None, "не удалось получить версию"
    return latest, None


def check_for_updates() -> dict:
    """Информация об обновлении: {current, latest, available, error, url}."""
    info = {
        "current": VERSION,
        "latest": "",
        "tag": "",
        "available": False,
        "error": None,
        "url": RELEASES_URL,
        "mirror_url": MIRROR_URL,
    }
    try:
        raw = None
        mirror = None
        try:
            raw = _fetch_latest_raw()
        except Exception:
            raw = None
        try:
            mirror = _fetch_latest_mirror()
        except Exception:
            mirror = None
        latest, err = merge_version_sources(raw, mirror)
        if latest is None:
            info["error"] = err
            return info
        info["latest"] = latest
        info["tag"] = tag_from_version(latest)
        info["available"] = version_key(latest) > version_key(VERSION)
    except Exception as e:  # noqa: BLE001 - any failure must be silent
        info["error"] = str(e)[:120]
    return info