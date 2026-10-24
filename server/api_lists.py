"""api_lists.py - домен «списки» (аудит #1, Inc C): здоровье/правка/CRUD,
bundled-домены и разовая нормализация user-списков при старте.

Соглашение: (ctx: AppContext, ...) -> dict; исключения - только ApiError."""
from __future__ import annotations

from server.api_common import ApiError
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
        with list_health.list_lock():
            result = list_health.dedupe(get_root_dir())
            from core import games as games_store
            games_store.sync_include_list(get_root_dir())
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "partial": True,
                "message": f"Списки очищены не полностью: {e}"}
    return {"status": "ok", **result}


def lists_add_domain(ctx: AppContext, data: dict) -> dict:
    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    mode = "exclude" if data.get("mode") == "exclude" else "include"
    result: dict = {}
    try:
        from core import list_health
        with list_health.list_lock():
            result = list_health.add_domain(
                get_root_dir(), str(data.get("domain") or ""), mode)
            ok = result.get("result") in ("added", "moved", "already")
            if ok:
                # combined-файл (user+games) - то, на что ссылаются args.
                # Нужен и для mode=exclude: add_domain мог убрать домен из
                # include-user. Держим тот же lock до обновления.
                from core import games as games_store
                games_store.sync_include_list(get_root_dir())
    except Exception as e:  # noqa: BLE001
        partial = result.get("result") in ("added", "moved", "already")
        return {"status": "error", "partial": partial,
                "message": f"Список изменён не полностью: {e}", **result}
    return {"status": "ok" if ok else "error", **result}


def get_list(ctx: AppContext, filename: str) -> dict:
    path = get_root_dir() / "lists" / filename
    content = ""
    if path.exists():
        # utf-8-sig: не тащим BOM (Notepad) в текстовое поле - иначе он
        # станет частью первой строки и сломает матчинг домена/подсети.
        # errors=replace: ANSI/битый файл не должен давать HTTP 500 и
        # оставлять вкладку списков пустой.
        try:
            content = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            return {"status": "error", "message": f"Не удалось прочитать список: {e}"}
    return {"status": "ok", "content": content}


def save_list(ctx: AppContext, data: dict, filename: str) -> dict:
    # Пустой/битый POST НЕ должен стирать пользовательский список: требуем
    # явный ключ content (внешнее ревью 14.10 - класс "потери данных").
    # content:"" допустим - это осознанная очистка списка пользователем.
    if not isinstance(data, dict) or "content" not in data:
        raise ApiError(400, {"status": "error",
                             "message": "Нет поля content - список не изменён"})
    raw_content = data.get("content", "")
    if not isinstance(raw_content, str):
        raise ApiError(400, {"status": "error",
                             "message": "content должен быть строкой"})
    content = _clean_list_text(raw_content).strip()
    saved = False
    try:
        # Атомарно и под локом (core.list_health.save_user_list): запись
        # на месте при обрыве процесса обрезала бы список до нуля, а живой
        # winws2 продолжил бы читать пустой hostlist. Имя приходит только
        # из маршрутов выше и всегда из USER_LIST_FILES; проверка внутри
        # save_user_list закрыта от записи системных списков.
        from core import list_health
        with list_health.list_lock():
            list_health.save_user_list(get_root_dir(), filename, content)
            saved = True
            # args ссылаются на combined-файл (user+games) - обновляем его
            # под тем же lock, чтобы параллельная правка домена не оставила
            # stale list-include-all.txt.
            if filename == "list-include-user.txt":
                from core import games as games_store
                games_store.sync_include_list(get_root_dir())
        return {"status": "ok", "message": "Список сохранён"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "partial": saved,
                "message": (f"Список сохранён, но combined-файл не обновился: {e}"
                            if saved else f"Не удалось сохранить список: {e}")}


def bundled_domains(ctx: AppContext) -> dict:
    """Домены из наших (не пользовательских) включений - для клиентского
    guard'а приоритетов список/исключение на странице «Списки»."""
    from core import list_health
    domains: set[str] = set()
    for name in ("list-general.txt", "list-google.txt", "list-discord.txt"):
        domains.update(list_health.read_entries(get_root_dir() / "lists" / name))
    return {"status": "ok", "domains": sorted(domains)}


# Списки, редактируемые через GUI: нормализуются при старте - BOM/zero-width
# в первой строке не даёт движку сматчить домен/подсеть (кейс 2026-09-14).
# ТОЛЬКО user-файлы: lists/ipset-exclude.txt - системный список приватных
# диапазонов, GUI его не правит (решение автора, REVIEW_VERDICT.md §2.9),
# поэтому чистить его здесь было неверно - правится ipset-exclude-user.txt.
USER_LIST_FILES = ("list-include-user.txt", "list-exclude-user.txt",
                   "ipset-include-user.txt", "ipset-exclude-user.txt")


def _clean_list_text(text: str) -> str:
    """Убирает невидимый мусор (BOM/zero-width), который ломает матчинг
    домена/подсети: прилетает из буфера обмена или из старых файлов с BOM."""
    return text.replace("\ufeff", "").replace("\u200b", "")


def normalize_user_lists() -> None:
    """Разово чистит user-списки от BOM/zero-width (наследие старых файлов и
    вставок из буфера обмена). Идемпотентно: чистые файлы не перезаписываются."""
    try:
        root = get_root_dir()
    except RuntimeError:
        return
    for name in USER_LIST_FILES:
        path = root / "lists" / name
        try:
            if not path.exists():
                continue
            decoded = path.read_bytes().decode("utf-8", errors="replace")
            cleaned = _clean_list_text(decoded)
            if cleaned != decoded:
                # Тот же атомарный путь, что у редактора: нормализация идёт
                # на каждом старте, и обрыв посреди записи оставил бы
                # пользователя без списка.
                from core.list_health import atomic_write_text
                atomic_write_text(path, cleaned)
        except OSError:
            continue
