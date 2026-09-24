"""list_health.py - здоровье списков: дубли, пересечения, покрытие доменов.

Универсальный слой для всех блоков, которые добавляют записи в списки
(probe, «Спорные домены», CDN-стабилизатор), и для фоновой проверки при
старте. Пользователь может править списки и в блокноте - поэтому проверка
идёт по файлам, а не по истории API.
"""
from __future__ import annotations

import re
from pathlib import Path

# include-домены: bundled (наши) + пользовательский
DOMAIN_INCLUDE_BUNDLED = ("list-general.txt", "list-google.txt",
                          "list-discord.txt", "list-cdn-fix.txt")
DOMAIN_INCLUDE_USER = "list-include-user.txt"
# exclude-домены: исключение приоритетнее включения (проверяется первым)
DOMAIN_EXCLUDE_BUNDLED = ("list-exclude.txt",)
DOMAIN_EXCLUDE_USER = "list-exclude-user.txt"
# файлы, которые чистит dedupe (редактируются через GUI)
USER_EDITABLE = (DOMAIN_INCLUDE_USER, DOMAIN_EXCLUDE_USER,
                 "ipset-include-user.txt", "ipset-exclude.txt")

_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$")


def _entry(line: str) -> str:
    """Значимая часть строки: без комментария и пробелов, в нижнем регистре."""
    return line.split("#", 1)[0].strip().lower()


def read_entries(path: Path) -> list[str]:
    """Записи файла по порядку (без пустых строк и комментариев), с BOM-фиксом."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    return [e for e in (_entry(ln) for ln in text.splitlines()) if e]


def _files(root: Path) -> dict[str, list[str]]:
    names = DOMAIN_INCLUDE_BUNDLED + (DOMAIN_INCLUDE_USER,) \
        + DOMAIN_EXCLUDE_BUNDLED + (DOMAIN_EXCLUDE_USER,)
    return {n: read_entries(root / "lists" / n) for n in names}


def coverage(root: Path, domains: list[str]) -> dict[str, dict]:
    """Для каждого домена: где он уже есть - {includes: [файлы], excludes: [...]}."""
    files = _files(root)
    out: dict[str, dict] = {}
    for raw in domains:
        d = (raw or "").strip().lower().rstrip(".")
        if not d:
            continue
        out[d] = {
            "includes": [n for n in DOMAIN_INCLUDE_BUNDLED
                         + (DOMAIN_INCLUDE_USER,) if d in files[n]],
            "excludes": [n for n in DOMAIN_EXCLUDE_BUNDLED
                         + (DOMAIN_EXCLUDE_USER,) if d in files[n]],
        }
    return out


def check_health(root: Path) -> dict:
    """Дубли внутри файлов, повторы между include-файлами, конфликты
    «включение ↔ исключение» и лишние повторы в user-файлах."""
    files = _files(root)
    dups, cross, redundant, conflicts = [], [], [], []

    for name, entries in files.items():
        seen: dict[str, int] = {}
        for e in entries:
            seen[e] = seen.get(e, 0) + 1
        for e, count in seen.items():
            if count > 1:
                dups.append({"file": name, "entry": e, "count": count})

    bundled_inc = set()
    for n in DOMAIN_INCLUDE_BUNDLED:
        bundled_inc.update(files[n])
    bundled_exc = set()
    for n in DOMAIN_EXCLUDE_BUNDLED:
        bundled_exc.update(files[n])
    for e in sorted(bundled_inc & set(files[DOMAIN_INCLUDE_USER])):
        redundant.append({"file": DOMAIN_INCLUDE_USER, "entry": e,
                          "also_in": "стандартные списки"})
    for e in sorted(bundled_exc & set(files[DOMAIN_EXCLUDE_USER])):
        redundant.append({"file": DOMAIN_EXCLUDE_USER, "entry": e,
                          "also_in": DOMAIN_EXCLUDE_BUNDLED[0]})

    inc_all: dict[str, list[str]] = {}
    for n in DOMAIN_INCLUDE_BUNDLED + (DOMAIN_INCLUDE_USER,):
        for e in files[n]:
            inc_all.setdefault(e, []).append(n)
    for e, where in inc_all.items():
        if len(where) > 1:
            cross.append({"entry": e, "files": where})

    exc_all = set()
    for n in DOMAIN_EXCLUDE_BUNDLED + (DOMAIN_EXCLUDE_USER,):
        exc_all.update(files[n])
    for e in sorted(set(inc_all) & exc_all):
        conflicts.append({
            "entry": e,
            "include": inc_all[e],
            "exclude": [n for n in DOMAIN_EXCLUDE_BUNDLED
                        + (DOMAIN_EXCLUDE_USER,) if e in files[n]],
        })

    # Пользователю показываем только то, что он может исправить: дубли/кросс/
    # конфликты с участием его файлов. Пересечения bundled-файлов - наша зона
    # (не должны вечно висеть у него предупреждением).
    dups_user = [d for d in dups if d["file"] in USER_EDITABLE]
    cross_user = [c for c in cross if any(n in USER_EDITABLE for n in c["files"])]
    conflicts_user = [c for c in conflicts
                      if any(n in USER_EDITABLE
                             for n in c["include"] + c["exclude"])]
    return {"dups": dups, "cross": cross, "redundant": redundant,
            "conflicts": conflicts, "total_dups": len(dups_user),
            "total_cross": len(cross_user),
            "total_redundant": len(redundant),
            "total_conflicts": len(conflicts_user),
            "bundled_dups": len(dups) - len(dups_user),
            "bundled_cross": len(cross) - len(cross_user),
            "bundled_conflicts": len(conflicts) - len(conflicts_user)}


def dedupe(root: Path) -> dict:
    """Чистит редактируемые файлы: дубли внутри файла + записи, уже входящие
    в bundled-списки (для user-включений/исключений). Комментарии сохраняются."""
    files = _files(root)
    bundled_inc = set()
    for n in DOMAIN_INCLUDE_BUNDLED:
        bundled_inc.update(files[n])
    bundled_exc = set()
    for n in DOMAIN_EXCLUDE_BUNDLED:
        bundled_exc.update(files[n])
    drop_map = {
        DOMAIN_INCLUDE_USER: bundled_inc,
        DOMAIN_EXCLUDE_USER: bundled_exc,
        "ipset-include-user.txt": set(),
        "ipset-exclude.txt": set(),
    }
    removed: dict[str, int] = {}
    for name, drop in drop_map.items():
        path = root / "lists" / name
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig",
                                   errors="replace").splitlines()
        except OSError:
            continue
        out, seen, n_removed = [], set(), 0
        for ln in lines:
            e = _entry(ln)
            if not e or ln.strip().startswith("#"):
                out.append(ln)
                continue
            if e in drop or e in seen:
                n_removed += 1
                continue
            seen.add(e)
            out.append(ln)
        if n_removed:
            path.write_text("\n".join(out) + ("\n" if out else ""),
                            encoding="utf-8")
            removed[name] = n_removed
    return {"removed": removed, "total": sum(removed.values())}


def _append_entry(path: Path, entry: str) -> None:
    """Добавляет запись в конец файла (создаёт файл и переводит строку)."""
    try:
        text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    except OSError:
        text = ""
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + entry + "\n", encoding="utf-8")


def _remove_entry(path: Path, entry: str) -> bool:
    """Удаляет запись из файла (комментарии и порядок сохраняются)."""
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8-sig",
                               errors="replace").splitlines()
    except OSError:
        return False
    out, removed = [], False
    for ln in lines:
        e = _entry(ln)
        if e == entry and not ln.strip().startswith("#"):
            removed = True
            continue
        out.append(ln)
    if removed:
        path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
    return removed


def add_domain(root: Path, domain: str, mode: str = "include") -> dict:
    """Добавляет домен в user-список с дедупом и разбором конфликтов.

    result: added | already | moved | blocked | invalid.
    """
    d = (domain or "").strip().lower().rstrip(".")
    if not d or len(d) > 253 or ".." in d or not _DOMAIN_RE.match(d):
        return {"result": "invalid", "message": "Некорректный домен"}
    files = _files(root)
    inc_files = [n for n in DOMAIN_INCLUDE_BUNDLED + (DOMAIN_INCLUDE_USER,)
                 if d in files[n]]
    exc_files = [n for n in DOMAIN_EXCLUDE_BUNDLED + (DOMAIN_EXCLUDE_USER,)
                 if d in files[n]]

    if mode == "exclude":
        if exc_files:
            return {"result": "already", "files": exc_files,
                    "message": "Домен уже в исключениях"}
        moved = _remove_entry(root / "lists" / DOMAIN_INCLUDE_USER, d)
        _append_entry(root / "lists" / DOMAIN_EXCLUDE_USER, d)
        return {"result": "moved" if moved else "added",
                "message": "Перенесён из обхода в исключения" if moved
                           else "Добавлен в исключения"}

    if inc_files:
        return {"result": "already", "files": inc_files,
                "message": "Домен уже в обходе"}
    blocked = [n for n in exc_files if n in DOMAIN_EXCLUDE_BUNDLED]
    if blocked:
        return {"result": "blocked", "files": blocked,
                "message": f"Домен в стандартных исключениях ({blocked[0]}) - "
                           "исключение сильнее, обход не сработает"}
    moved = _remove_entry(root / "lists" / DOMAIN_EXCLUDE_USER, d)
    _append_entry(root / "lists" / DOMAIN_INCLUDE_USER, d)
    return {"result": "moved" if moved else "added",
            "message": "Перенесён из исключений в обход" if moved
                       else "Добавлен в обход"}


def remove_domain(root: Path, domain: str, mode: str = "include") -> bool:
    """Убирает домен из user-списка (включений/исключений); True если убрали."""
    d = (domain or "").strip().lower().rstrip(".")
    if not d:
        return False
    fname = DOMAIN_INCLUDE_USER if mode == "include" else DOMAIN_EXCLUDE_USER
    return _remove_entry(root / "lists" / fname, d)
