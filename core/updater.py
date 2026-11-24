"""Updater (0.8): скачивание дистрибутива, бэкап юзер-файлов, честное обновление.

Контракт файлов:
  USER (никогда не трогаются): zapret2_config.json, lists/*-user.txt,
       юзерские пресеты (не из release-набора и не генерируемые), логи.
  SYSTEM (заменяются по манифесту): core/, server/, frontend/, bin/, lua/,
       blobs/, windivert/, presets/ release-набора, базовые lists/*.txt.
  RUNTIME (portable): python/ обновляется отдельным деревом (<root>/python.new)
       и переключается после выхода процесса; app/runtime.json говорит,
       какую ревизию рантайма требует код (миграция 0.10→0.11).

Источники скачивания: GitHub release asset -> jsDelivr-зеркало (CDN отдаёт
repo-файлы даже на сетях, где объекты GitHub IP-блокированы).

Подлинность: подписанный release.json (Ed25519, core.update_verify). Без
валидной подписи и подтверждённого sha256 обновление не применяется
(fail-closed) - зеркало считается недоверенным кэшем.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

_REPO = "TheFirstNoob/Zapret-2-GUI"
_UA = {"User-Agent": "Zapret2GUI"}
MAX_UPDATE_BYTES = 512 * 1024 * 1024  # заведомо больше релиза, но не «бесконечно»

RELEASE_PRESETS = (
    "default", "default-alt", "auto", "tcpmd5-fake", "fake-only",
    "fakedsplit", "fake-disorder", "fake-multidisorder", "hostfakesplit",
    "multisplit-pure", "multisplit-seqovl",
)

USER_FILES: tuple[str, ...] = (
    "zapret2_config.json",
    "games.json",
    "lists/list-include-user.txt",
    "lists/list-exclude-user.txt",
    "lists/list-games.txt",
    "lists/list-include-all.txt",
    "lists/ipset-include-user.txt",
    "lists/ipset-exclude-user.txt",
    "test_session.log",
    "test_session.old.log",
    "debug_winws2.log",
)

USER_PRESET_IGNORE = ("custom",)  # генерируется тестером - не трогаем

# ── Portable-runtime (python/) ──────────────────────────────────────────
# Portable-сборка: <root>/app (код) + <root>/python (embeddable-интерпретатор
# и site-packages). Обновлять python/ «на живую» нельзя - pythonw.exe запущен
# из этого каталога, поэтому новый рантайм распаковывается рядом
# (<root>/python.new), а переключение делает батник ПОСЛЕ выхода процесса
# (move python -> python.old, move python.new -> python; сбой = откат).
#
# Ревизия рантайма = SHA256(requirements.txt + версия Python): сборка пишет её
# в python/ZAPRET2_RUNTIME.json (факт) и app/runtime.json (требование). Так
# апдейт видит смешанную установку (0.10→0.11: app новый, а niquests/qh3 в
# site-packages не доехали - H3-проба «нет niquests»).
RUNTIME_DIR_NAME = "python"
RUNTIME_MARKER_NAME = "ZAPRET2_RUNTIME.json"  # внутри python/ (факт)
RUNTIME_REQUIRED_NAME = "runtime.json"        # внутри app/ (требование)
RUNTIME_STAGE_SUFFIX = ".new"
RUNTIME_OLD_SUFFIX = ".old"
# ключи runtime-файлов в update_manifest.json = пути в архиве
RUNTIME_KEY_PREFIX = RUNTIME_DIR_NAME + "/"
# пакеты, без которых portable деградирует (H3-проба/интерфейс) - проверяем
# их наличие в подготовленном и в установленном python/
RUNTIME_PACKAGES: tuple[str, ...] = ("niquests", "qh3", "webview")
# запас свободного места при staging (антивирус/кэш/временные файлы)
RUNTIME_FREE_SPACE_MARGIN = 64 * 1024 * 1024
# манифест релиза (release.json) крошечный - ограничиваем его скачивание
# отдельно от 512MB-лимита архивов (P3 аудита 2026-11-14)
MANIFEST_MAX_BYTES = 512 * 1024

# Runtime-файлы пользователя (генерируются обходом; обновление их не трогает,
# но в settings-export они не попадают - там домены, выученные autohostlist).
RUNTIME_FILES: tuple[str, ...] = (
    "lists/zapret-auto.txt",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _upd_log(msg: str) -> None:
    """Операционный лог апдейтера (тот же, что у службы и запуска)."""
    try:
        from core.applog import log as _applog
        _applog("update", msg)
    except Exception:
        pass


def is_user_file(rel: str) -> bool:
    """Файл, который обновление никогда не трогает.

    Сравнение регистронезависимое: NTFS не различает регистр, поэтому имя
    вида "lists/LIST-INCLUDE-USER.TXT" иначе перезаписало бы user-файл
    (P3 аудита 2026-11-14)."""
    rel = rel.replace("/", "\\").lstrip("\\")
    p = Path(rel.lower())
    if p.as_posix() in USER_FILES or p.as_posix() in RUNTIME_FILES:
        return True
    if p.parts[:1] == ("lists",) and p.name.endswith("-user.txt"):
        return True
    if p.parts[:2] == ("lists", "games"):
        return True  # сгенерированные CIDR-файлы игровых блокировок
    if p.parts[:1] == ("presets",) and p.name.endswith(".txt"):
        stem = p.stem
        if stem not in RELEASE_PRESETS:
            return True  # юзерский/генерируемый (custom) пресет - не трогаем
    return False


# ── Portable-runtime: ревизия, поиск, состояние ─────────────────────────

def _read_json_obj(path: Path) -> dict:
    """JSON-объект из файла; {} для отсутствующего/битого (апдейт не роняем)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def runtime_rev_for(requirements: bytes, python_version: str) -> str:
    """Ревизия набора runtime-зависимостей: SHA256(requirements + python)[:16].

    Одна и та же функция в сборке (маркеры) и в тестах; CRLF нормализуется,
    чтобы маркер не зависел от checkout-настроек git.
    """
    h = hashlib.sha256()
    h.update((requirements or b"").replace(b"\r\n", b"\n"))
    h.update(b"|python=")
    h.update(str(python_version or "").strip().encode("ascii", "ignore"))
    return h.hexdigest()[:16]


def read_runtime_rev(runtime_dir: Optional[Path]) -> str:
    """Фактическая ревизия установленного runtime ("" = маркера нет, 0.10-)."""
    if not runtime_dir:
        return ""
    return str(_read_json_obj(Path(runtime_dir) / RUNTIME_MARKER_NAME
                              ).get("rev") or "")


def read_required_runtime_rev(root_dir: Path) -> str:
    """Ревизия runtime, которую требует приложение (app/runtime.json).

    Файл лежит в app/ и приезжает вместе с кодом - его доставит даже старый
    апдейтер 0.10, поэтому смешанная установка детектируется.
    """
    return str(_read_json_obj(Path(root_dir) / RUNTIME_REQUIRED_NAME
                              ).get("rev") or "")


def _looks_like_runtime(path: Path) -> bool:
    """Похож ли каталог на embeddable-рантайм (python.exe/pythonw.exe)."""
    try:
        p = Path(path)
        return bool((p / "pythonw.exe").is_file()
                    or (p / "python.exe").is_file())
    except OSError:
        return False


def find_runtime_dir(root_dir: Path,
                     runtime_dir: Optional[Path] = None) -> Optional[Path]:
    """Каталог portable-runtime (python/ рядом с app/) или None.

    None - рантайма нет (exe-сборка, запуск из исходников, lite): обновление
    python/ неприменимо, апдейтер работает как раньше (только app/).
    """
    if runtime_dir is not None:
        cand = Path(runtime_dir)
        return cand if _looks_like_runtime(cand) else None
    try:
        root = Path(root_dir).resolve()
    except OSError:
        return None
    candidates: list[Path] = []
    # 1) запущенный интерпретатор - самый точный признак portable-раскладки
    try:
        exe_parent = Path(sys.executable).resolve().parent
    except OSError:
        exe_parent = None
    if (exe_parent is not None
            and exe_parent.name.lower() == RUNTIME_DIR_NAME
            and exe_parent.parent == root.parent):
        candidates.append(exe_parent)
    # 2) штатная раскладка portable: <root>/app + <root>/python. «Чужой»
    # python/ рядом с папкой, просто названной app (запуск из исходников/exe
    # в C:\app при наличии C:\python), трогать нельзя - принимаем, только
    # если мы запущены из него или это действительно portable-раскладка
    # (рядом с app лежит main.pyw).
    if root.name.lower() == "app":
        cand = root.parent / RUNTIME_DIR_NAME
        exe_inside = False
        if exe_parent is not None:
            try:
                exe_inside = exe_parent == cand.resolve()
            except OSError:
                exe_inside = False
        if exe_inside or (root / "main.pyw").is_file():
            candidates.append(cand)
    for cand in candidates:
        if _looks_like_runtime(cand):
            return cand
    return None


def _runtime_packages_ok(runtime_dir: Path) -> bool:
    """Есть ли в site-packages ключевые пакеты (H3-проба/интерфейс)."""
    site = Path(runtime_dir) / "Lib" / "site-packages"
    try:
        for pkg in RUNTIME_PACKAGES:
            if not ((site / pkg).is_dir() or (site / f"{pkg}.py").is_file()):
                return False
        return True
    except OSError:
        return False


def runtime_status(root_dir: Path,
                   runtime_dir: Optional[Path] = None) -> dict:
    """Состояние portable-runtime (диагностика + fail-closed проверки).

    state:
      not_portable      - рантайма рядом нет (exe/исходники/lite) - не наше;
      required_unknown  - приложение не знает требуемую ревизию (0.10-);
      runtime_missing   - python/ есть, но маркера нет (0.10-рантайм);
      stale             - ревизии расходятся;
      broken            - ревизия совпала, но нет niquests/qh3/webview;
      ok                - всё сходится.
    runtime_missing/stale/broken = смешанная установка: H3-проба деградирует.
    """
    out = {"portable": False, "state": "not_portable", "runtime_dir": "",
           "rev": "", "required_rev": "", "message": ""}
    try:
        rt = find_runtime_dir(root_dir, runtime_dir)
        required = read_required_runtime_rev(root_dir)
    except (OSError, RuntimeError):
        return out
    if rt is None:
        return out
    rev = read_runtime_rev(rt)
    out.update(portable=True, runtime_dir=str(rt), rev=rev,
               required_rev=required)
    if not required:
        out["state"] = "required_unknown"
        return out
    if not rev:
        out.update(state="runtime_missing", message=(
            "компоненты Python (python/) от старой версии - обновите их "
            "или переустановите portable-сборку (настройки сохраняются)"))
        return out
    if rev != required:
        out.update(state="stale", message=(
            "компоненты Python (python/) не соответствуют версии программы - "
            "обновите их или переустановите portable-сборку"))
        return out
    if not _runtime_packages_ok(rt):
        out.update(state="broken", message=(
            "в python/ нет части зависимостей (niquests/qh3/webview) - "
            "переустановите portable-сборку"))
        return out
    out["state"] = "ok"
    return out


def runtime_needs_update(root_dir: Path,
                         runtime_dir: Optional[Path] = None) -> bool:
    """True, если установленный python/ не соответствует коду приложения."""
    return runtime_status(root_dir, runtime_dir).get("state") in (
        "runtime_missing", "stale", "broken")


def runtime_switch_dirs(runtime_dir: Path) -> tuple[Path, Path]:
    """(staged, old) каталоги рядом с runtime для атомарного переключения."""
    rt = Path(runtime_dir)
    return (rt.with_name(rt.name + RUNTIME_STAGE_SUFFIX),
            rt.with_name(rt.name + RUNTIME_OLD_SUFFIX))


def _safe_archive_rel(rel: str) -> None:
    """Fail-closed проверка пути из архива: нет absolute/traversal/ADS.

    ADS-имя ("core/x.py:hidden") проверяем в ЛЮБОМ компоненте, а не только в
    первом: иначе в файл установки писался alternate data stream (P3).
    """
    parts = Path(rel).parts
    if (not rel or rel.startswith(("/", "\\")) or ".." in parts
            or any(":" in part for part in parts)):
        raise RuntimeError(f"небезопасный путь в архиве: {rel}")


def _manifest_completeness_problems(manifest_files: dict,
                                    runtime_manifest: dict,
                                    app_paths: set,
                                    raw_paths: set) -> list:
    """Файлы из манифеста обязаны быть в архиве (P3: недосборка проходила).

    Раньше архив, где манифест знает файл, а zip его не содержит, применялся
    молча - установка оставалась частичной без единого сообщения.
    """
    problems: list[str] = []
    for rel in sorted(manifest_files):
        if rel == "update_manifest.json" or is_user_file(rel):
            continue
        if rel not in app_paths:
            problems.append(f"в архиве нет файла из манифеста: {rel}")
    rfiles = runtime_manifest.get("files") if runtime_manifest else None
    if isinstance(rfiles, dict):
        for rel in sorted(rfiles):
            if rel not in raw_paths:
                problems.append(f"в архиве нет runtime-файла из манифеста: {rel}")
    if len(problems) > 5:
        problems = problems[:5] + [f"... ещё {len(problems) - 5}"]
    return problems


def _runtime_archive_bytes(zf: zipfile.ZipFile) -> int:
    """Несжатый размер python/** в архиве (для проверки свободного места)."""
    total = 0
    for info in zf.infolist():
        if not info.is_dir() and info.filename.startswith(RUNTIME_KEY_PREFIX):
            total += max(0, int(info.file_size))
    return total


def _check_runtime_disk_space(zf: zipfile.ZipFile, target: Path) -> None:
    """Хватит ли места на python.new (старый python/ живёт до переключения)."""
    needed = _runtime_archive_bytes(zf) + RUNTIME_FREE_SPACE_MARGIN
    try:
        free = int(shutil.disk_usage(str(target)).free)
    except (OSError, AttributeError, ValueError):
        return  # не смогли узнать - не блокируем (как раньше)
    if free < needed:
        raise RuntimeError(
            "недостаточно места на диске для обновления python/: нужно "
            f"~{needed // (1024 * 1024)} МБ, свободно "
            f"{free // (1024 * 1024)} МБ")


def _validate_staged_runtime(staged: Path, runtime_meta: dict) -> None:
    """Проверить подготовленный python.new ДО переключения (fail-closed)."""
    want_rev = str(runtime_meta.get("rev") or "")
    if not want_rev:
        raise RuntimeError("в обновлении нет ревизии runtime")
    got_rev = read_runtime_rev(staged)
    if got_rev != want_rev:
        raise RuntimeError(
            f"ревизия runtime в архиве ({got_rev or 'нет'}) не совпадает "
            f"с манифестом ({want_rev})")
    if not _looks_like_runtime(staged):
        raise RuntimeError("в обновлении нет python-рантайма (python.exe)")
    if not _runtime_packages_ok(staged):
        raise RuntimeError(
            "в обновлении runtime нет обязательных пакетов ("
            + ", ".join(RUNTIME_PACKAGES) + ")")


def _post_apply_problems(root_dir: Path, expected_version: Optional[str],
                         runtime_dir: Optional[Path], runtime_meta: dict,
                         staged_runtime: Optional[Path],
                         validate_app: bool) -> list:
    """Post-update проверка (fail-closed): VERSION vs app, полнота, runtime.

    Непустой список = изменения откатываются (apply_portable), установка
    остаётся в состоянии до обновления - смешанную копию не оставляем.
    """
    problems: list[str] = []
    if expected_version and validate_app:
        from core.updates import version_key
        ver_path = Path(root_dir) / "core" / "config.py"
        try:
            text = ver_path.read_text(encoding="utf-8")
        except OSError as e:
            text = ""
            problems.append(f"после обновления нет core/config.py: {e}")
        m = re.search(r"""VERSION\s*=\s*["']([^"']+)["']""", text or "")
        if not m:
            problems.append(
                "после обновления не найдена VERSION в core/config.py")
        elif version_key(m.group(1)) != version_key(expected_version):
            problems.append(
                f"после обновления в core/config.py версия {m.group(1)!r}, "
                f"а в манифесте {expected_version!r}")
    if runtime_dir is not None:
        required = read_required_runtime_rev(root_dir)
        actual = read_runtime_rev(runtime_dir)
        archive_rev = str((runtime_meta or {}).get("rev") or "")
        if archive_rev and required and archive_rev != required:
            problems.append(
                f"в архиве runtime rev {archive_rev}, а приложение требует "
                f"{required} (сборка несогласована)")
        elif staged_runtime is not None:
            staged_rev = read_runtime_rev(staged_runtime)
            if required and staged_rev != required:
                problems.append(
                    f"подготовленный runtime rev {staged_rev or 'нет'} не "
                    f"совпадает с требуемым {required}")
        elif required and actual != required:
            problems.append(
                "обновление не содержит python/-рантайма, а установленный "
                f"устарел (rev {actual or 'нет'} != {required}): нужна полная "
                "переустановка portable-сборки из свежего архива "
                "(настройки, списки и пресеты сохраняются)")
    return problems


def _bat_path_token(path: Path, root_dir: Path) -> str:
    """Путь для ASCII-батника: %~dp0<relative> (иначе абсолютный fallback).

    Относительные токены нужны, чтобы установка в папку с пробелами/
    кириллицей не ломала ASCII-батник (cmd получает путь из %~dp0).
    """
    try:
        rel = os.path.relpath(str(Path(path).resolve()), str(Path(root_dir)))
    except (OSError, ValueError):
        return str(Path(path))
    return "%~dp0" + rel.replace("/", "\\")


# Человекочитаемые имена релизных ассетов (0.10+, решение 2026-10-01):
# на GitHub Release прикрепляются ОБА имени - pretty (для людей) и
# каноническое (совместимость: клиенты 0.9.x знают только его). В git
# (`Windows build/`) имена ВСЕГДА канонические: переименование ломает
# jsDelivr-зеркало у старых версий.
_PRETTY_NAMES = {
    "exe": "Zapret2GUI-Full-PyInstaller.zip",
    "portable": "Zapret2GUI-portable-Recommended.zip",
    "lite": "Zapret2GUI-lite-CMD.zip",
}


def download_url(kind: str, tag: str) -> tuple[list[str], str]:
    """(primary-кандидаты по порядку, mirror) URL архива для kind.

    Primary: pretty-имя, затем каноническое (404 на отсутствующем имени не
    ломает обновление). Зеркало jsDelivr - только каноническое имя."""
    fname = {
        "exe": "Zapret2GUI.zip",
        "portable": "Zapret2GUI-portable.zip",
        "lite": "Zapret2GUI-lite.zip",
    }[kind]
    gh_base = f"https://github.com/{_REPO}/releases/download/{tag}/"
    primary = [gh_base + n for n in dict.fromkeys(
        (_PRETTY_NAMES[kind], fname))]
    mirror = (f"https://cdn.jsdelivr.net/gh/{_REPO}@{tag}/"
              f"Windows%20build/{fname}")
    return primary, mirror


MANIFEST_NAME = "release.json"
MANIFEST_SIG_NAME = "release.json.sig"
MANIFEST_SCHEMA = 1


def fetch_release_manifest(tag: str, dest_dir: Path) -> tuple[bytes, str]:
    """Скачать манифест релиза и подпись: GitHub asset → jsDelivr-зеркало.

    Возвращает (байты манифеста, текст подписи). Подпись проверяет
    вызывающий (core.update_verify) - здесь только доставка."""
    last_err: Optional[Exception] = None
    for base in (f"https://github.com/{_REPO}/releases/download/{tag}/",
                 f"https://cdn.jsdelivr.net/gh/{_REPO}@{tag}/"):
        try:
            m_dest = dest_dir / MANIFEST_NAME
            s_dest = dest_dir / MANIFEST_SIG_NAME
            # Манифест/подпись крошечные: отдельный лимит не даёт «капающему»
            # CDN забить диск 512MB-файлом вместо манифеста (P3 аудита).
            _download(base + MANIFEST_NAME, m_dest, timeout=30,
                      max_bytes=MANIFEST_MAX_BYTES)
            _download(base + MANIFEST_SIG_NAME, s_dest, timeout=30,
                      max_bytes=MANIFEST_MAX_BYTES)
            return (m_dest.read_bytes(),
                    s_dest.read_text(encoding="utf-8").strip())
        except Exception as e:  # noqa: BLE001 - пробуем следующий источник
            last_err = e
    raise RuntimeError(f"манифест обновления недоступен: {last_err}")


def validate_release(manifest: dict, tag: str, current_version: str,
                     kind: str) -> Optional[str]:
    """Проверить манифест: тег, версия новее текущей (анти-даунгрейд),
    наличие артефакта для способа обновления и формат его SHA256.
    None = манифест корректен."""
    from core.updates import version_key
    if not isinstance(manifest, dict):
        return "манифест обновления повреждён"
    if manifest.get("schema") != MANIFEST_SCHEMA:
        return "неподдерживаемый формат манифеста обновления"
    if str(manifest.get("tag") or "") != tag:
        return "манифест обновления не совпадает с релизом"
    version = str(manifest.get("version") or "")
    if version_key(version) <= version_key(current_version):
        return "в манифесте нет версии новее текущей"
    # Опциональный анти-даунгрейд: min_version в подписанном манифесте -
    # минимальная ТЕКУЩАЯ версия, с которой допустим апдейт (ревью 18.10).
    min_v = str(manifest.get("min_version") or "").strip()
    if min_v:
        min_key = version_key(min_v)
        if min_key <= (0,):
            # Опечатка в min_version молча отключала анти-даунгрейд-флор
            # (version_key("garbage") == (0,)) - fail-closed (P3 аудита).
            return "в манифесте некорректный min_version"
        if version_key(current_version) < min_key:
            return (f"обновление требует версию не ниже {min_v} "
                    f"(сейчас {current_version}) - обновитесь по шагам")
    artifacts = manifest.get("artifacts")
    art = artifacts.get(kind) if isinstance(artifacts, dict) else None
    if not isinstance(art, dict):
        return "в манифесте нет артефакта для этого способа обновления"
    sha = str(art.get("sha256") or "").lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        return "в манифесте некорректная контрольная сумма"
    if kind == "exe":
        inner = str(art.get("exe_sha256") or "").lower()
        if len(inner) != 64 or any(c not in "0123456789abcdef"
                                   for c in inner):
            return "в манифесте нет контрольной суммы exe"
    return None


def _download(url: str, dest: Path, timeout: int = 300,
              max_bytes: int = MAX_UPDATE_BYTES) -> None:
    req = urllib.request.Request(url, headers=_UA)
    deadline = time.monotonic() + max(1, int(timeout))
    total = 0
    with urllib.request.urlopen(req, timeout=timeout) as r, \
            open(dest, "wb") as f:
        while True:
            # Socket timeout сбрасывается каждым read; общий wall-clock
            # дедлайн не даёт «капающему» CDN держать update вечно.
            if time.monotonic() > deadline:
                raise TimeoutError(f"загрузка превысила {timeout} с")
            chunk = r.read(1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError("слишком большой файл обновления")
            f.write(chunk)


def fetch_update(kind: str, tag: str, dest_dir: Path,
                 sha256_expected: Optional[str] = None) -> Path:
    """Скачать zip обновления: GitHub asset → jsDelivr-зеркало.

    Fail-closed: без подтверждённой SHA256 (из подписанного манифеста)
    ничего не качаем и не применяем."""
    if not sha256_expected:
        raise RuntimeError("контрольная сумма обновления не подтверждена")
    dest = dest_dir / f"update_{kind}.zip"
    primary, mirror = download_url(kind, tag)
    last_err = ""
    for url in [*primary, mirror]:
        try:
            _download(url, dest)
            got = _sha256(dest)
            if got == sha256_expected:
                return dest
            # Хеш не совпал (обрыв/битый кэш CDN) - пробуем зеркало, а не
            # падаем сразу: зеркало ровно для таких сетей и делалось (аудит)
            last_err = f"SHA256 не совпал ({got[:16]}…)"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        dest.unlink(missing_ok=True)
    raise RuntimeError(f"не удалось скачать обновление (GitHub и зеркало): {last_err}")


def _backup_user_files(root_dir: Path, old_version: str) -> Optional[Path]:
    """ZIP юзер-файлов перед обновлением (страховка для любого сценария)."""
    backup_dir = root_dir / "backups"
    name = f"backup_{old_version.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M%S}.zip"
    backup_path = backup_dir / name
    try:
        # mkdir ВНУТРИ try: если на месте backups/ лежит файл (FileExistsError),
        # апдейт раньше падал с невнятной ошибкой вместо «без бэкапа» (P3).
        backup_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in USER_FILES:
                p = root_dir / rel
                if p.exists():
                    zf.write(p, rel)
            # юзерские пресеты (не из release-набора и не генерируемые)
            presets = root_dir / "presets"
            if presets.is_dir():
                for pf in sorted(presets.glob("*.txt")):
                    if pf.stem not in RELEASE_PRESETS \
                            and pf.stem not in USER_PRESET_IGNORE:
                        zf.write(pf, f"presets/{pf.name}")
        return backup_path
    except (OSError, ValueError):
        # ValueError: zipfile не умеет mtime < 1980 (0/битые timestamps
        # user-файлов) - бэкап не должен блокировать portable-апдейт.
        return None


def export_settings_zip(root_dir: Path) -> Optional[Path]:
    """Экспорт настроек: config + *-user.txt + юзерские пресеты - один zip
    в корне программы (страховка сценария «снёс всё и поставил заново»)."""
    name = f"zapret2_settings_{datetime.now():%Y%m%d_%H%M%S}.zip"
    export_path = root_dir / name
    try:
        with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Метка экспорта (совместимость между версиями): импорт её
            # игнорирует (не USER-файл), но GUI показывает, из какой версии
            # архив. Конфиг мигрирует сам - ConfigManager.load() терпит
            # неизвестные/недостающие поля.
            from core.config import VERSION as _ver
            zf.writestr("settings_meta.json", json.dumps({
                "app": "Zapret2GUI",
                "version": _ver,
                "exported": datetime.now().isoformat(timespec="seconds"),
            }, ensure_ascii=False, indent=2))
            for rel in USER_FILES:
                p = root_dir / rel
                if p.exists():
                    zf.write(p, rel)
            presets = root_dir / "presets"
            if presets.is_dir():
                for pf in sorted(presets.glob("*.txt")):
                    if pf.stem not in RELEASE_PRESETS \
                            and pf.stem not in USER_PRESET_IGNORE:
                        zf.write(pf, f"presets/{pf.name}")
        return export_path
    except (OSError, ValueError):
        return None


def read_settings_meta(zip_data: bytes) -> dict:
    """Метка архива экспорта (версия/дата) - {} если нет/битая."""
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            if "settings_meta.json" in zf.namelist():
                meta = json.loads(zf.read("settings_meta.json").decode("utf-8"))
                return meta if isinstance(meta, dict) else {}
    except Exception:
        pass
    return {}


def import_settings_zip(zip_data: bytes, root_dir: Path) -> tuple[int, int]:
    """Импорт настроек из zip: восстанавливаются ТОЛЬКО юзер-файлы
    (config, *-user.txt, юзерские пресеты). settings_meta.json и всё
    остальное пропускается. Возвращает (imported, skipped)."""
    import io
    imported = 0
    skipped = 0
    total_size = 0
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # Не даём маленькому zip'у распаковаться в гигабайты.
            total_size += max(0, int(info.file_size))
            if info.file_size > 8 * 1024 * 1024 or total_size > 32 * 1024 * 1024:
                raise RuntimeError("архив настроек слишком большой")
            rel_posix = info.filename
            rel = rel_posix.replace("/", "\\")
            # защита от path traversal внутри чужого zip
            if rel.startswith(("/", "\\")) or ".." in rel:
                skipped += 1
                continue
            # USER_FILES записаны в posix-виде (lists/...), поэтому сравнивать
            # надо ДО замены "/" на "\\"; иначе list-games/list-include-all
            # молча терялись при импорте (P2 2026-11-15).
            is_user = (
                rel_posix in USER_FILES
                or (Path(rel_posix).parts[:1] == ("lists",)
                    and Path(rel_posix).name.endswith("-user.txt"))
                or (Path(rel_posix).parts[:1] == ("presets",)
                    and Path(rel_posix).name.endswith(".txt")
                    and Path(rel_posix).stem not in RELEASE_PRESETS
                    and Path(rel_posix).stem != "custom")
            )
            if not is_user:
                skipped += 1
                continue
            target = root_dir / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                # Атомарно: обрыв/лок/диск не должны оставить user-файл
                # обрезанным (аудит 24.10).
                fd, tmp_name = tempfile.mkstemp(
                    prefix=f".{target.name}.import.", dir=str(target.parent))
                try:
                    with zf.open(info) as src, os.fdopen(fd, "wb") as out:
                        shutil.copyfileobj(src, out)
                    os.replace(tmp_name, target)
                except Exception:
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
                    raise
                imported += 1
            except (OSError, RuntimeError):
                skipped += 1
    return imported, skipped


def changed_windivert_files(zip_path: Path, root_dir: Path) -> list[str]:
    """Вернуть windivert/-файлы, которые реально отличаются от установки.

    Нужен апдейтеру, чтобы не выгружать драйвер зря, если WinDivert.dll/sys
    не менялись, и наоборот - выгрузить его перед заменой изменённого
    драйверного файла. Читает только windivert/.
    """
    root = Path(root_dir)
    changed: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        prefix = "app/" if any(n.startswith("app/") for n in names) else ""
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if prefix:
                if not name.startswith(prefix):
                    continue
                rel = name[len(prefix):]
            else:
                rel = name
            if not rel.startswith("windivert/"):
                continue
            target = root / rel
            try:
                if (not target.is_file()
                        or _sha256(target) != hashlib.sha256(
                            zf.read(info)).hexdigest()):
                    changed.append(rel)
            except OSError:
                changed.append(rel)
    return changed


def apply_portable(zip_path: Path, root_dir: Path,
                   progress_cb=None,
                   runtime_dir: Optional[Path] = None,
                   expected_version: Optional[str] = None) -> dict:
    """Обновить portable/lite-папку из скачанного zip, СОХРАНЯЯ юзер-файлы.

    Порядок (fail-closed):
      1) app-файлы распаковываются во временную папку и сверяются по sha256
         из манифеста ДО записи в установку;
      2) portable-runtime (python/**) распаковывается в <runtime>.new: живой
         каталог python/ трогать нельзя (pythonw.exe запущен из него) -
         переключение делает батник после выхода процесса
         (prepare_app_restart_bat), с откатом на <runtime>.old;
      3) app-файлы копируются с откатом при сбое;
      4) post-check: ревизия runtime, VERSION из нового core/config.py,
         наличие файлов из манифеста. Провал = откат app-файлов + удаление
         подготовленного runtime (смешанную установку не оставляем).

    Юзер-файлы (конфиг, *-user.txt, юзерские пресеты, логи) не трогаются.
    Одинаковые файлы не перезаписываются: это важно для загруженного
    WinDivert.dll/WinDivert64.sys и вообще уменьшает окно отказа.
    Возвращает {updated, skipped_identical, skipped_user, skipped_nonapp, backup,
    runtime_staged, runtime_files, runtime_skipped, runtime_rev}."""
    root_dir = Path(root_dir)

    def cb(x):
        if progress_cb:
            try:
                progress_cb(x)
            except Exception:
                pass

    # Portable: python/ рядом с app/. Явно переданный каталог обязан
    # существовать (ошибка вызывающего), иначе ищем сами (None для exe/dev).
    if runtime_dir is not None:
        runtime_dir = Path(runtime_dir)
        if not _looks_like_runtime(runtime_dir):
            raise RuntimeError(
                f"каталог portable-runtime не найден: {runtime_dir}")
    else:
        runtime_dir = find_runtime_dir(root_dir)

    backup = _backup_user_files(root_dir, "old")
    cb("Резервная копия настроек создана")

    updated = 0
    skipped_identical = 0
    skipped_user = 0
    skipped_nonapp = 0
    runtime_files = 0
    runtime_skipped = ""
    staged_runtime: Optional[Path] = None
    staged_cleanup: Optional[Path] = None
    manifest_runtime: dict = {}
    manifest_rev = ""
    success = False
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # portable-архив кладёт код в app/, lite - в корне архива
            prefix = "app/" if any(n.startswith("app/") for n in names) else ""
            try:
                manifest_raw = zf.read(prefix + "update_manifest.json")
            except KeyError:
                manifest_raw = b""
            if not manifest_raw:
                raise RuntimeError("в обновлении нет манифеста файлов")
            try:
                manifest_doc = json.loads(manifest_raw.decode("utf-8"))
            except Exception:
                raise RuntimeError("манифест файлов обновления повреждён")
            if not isinstance(manifest_doc, dict):
                raise RuntimeError("манифест файлов обновления повреждён")
            manifest_files = manifest_doc.get("files") or {}
            if not isinstance(manifest_files, dict):
                manifest_files = {}
            manifest_runtime = manifest_doc.get("runtime") or {}
            if not isinstance(manifest_runtime, dict):
                manifest_runtime = {}
            runtime_manifest_files = manifest_runtime.get("files") or {}
            if not isinstance(runtime_manifest_files, dict):
                runtime_manifest_files = {}
            manifest_rev = str(manifest_runtime.get("rev") or "")

            # Пути архива: app-относительные (для манифеста app) и «как есть»
            # (для runtime-секции); полнота манифеста проверяется до записи.
            app_paths: set = set()
            raw_paths: set = set()
            for name in names:
                raw_paths.add(name)
                if name.endswith("/"):
                    continue
                if prefix and name.startswith(prefix):
                    app_paths.add(name[len(prefix):])
                elif not prefix:
                    app_paths.add(name)
            completeness = _manifest_completeness_problems(
                manifest_files, manifest_runtime, app_paths, raw_paths)
            if completeness:
                raise RuntimeError(
                    "архив обновления неполный: " + "; ".join(completeness))

            # Нужен ли runtime: только portable и только при расхождении
            # ревизий. Одинаковая ревизия = 40MB не копируем зря.
            staged_dir: Optional[Path] = None
            if runtime_dir is not None and runtime_manifest_files:
                staged_dir, old_dir = runtime_switch_dirs(runtime_dir)
                if manifest_rev and read_runtime_rev(runtime_dir) == manifest_rev:
                    runtime_skipped = "up_to_date"
                    staged_dir = None
                else:
                    _check_runtime_disk_space(zf, staged_dir.parent)
                    for stale in (staged_dir, old_dir):
                        if stale.exists():
                            try:
                                shutil.rmtree(stale)
                            except OSError as e:
                                raise RuntimeError(
                                    f"не удалось очистить {stale}: {e}") from e
                    staged_dir.mkdir(parents=True)
                    staged_cleanup = staged_dir
            elif runtime_dir is not None:
                runtime_skipped = "absent_in_archive"

            tmp_dir = root_dir / "updates" / "_extract"
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            extracted: list[str] = []
            try:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    rel = info.filename
                    if prefix and rel.startswith(prefix):
                        rel = rel[len(prefix):]
                    elif prefix:
                        # portable-архив: всё вне app/. python/** - отдельное
                        # дерево runtime (переключается после выхода), прочее
                        # (install.cmd, readme) - каркас установки, его меняет
                        # только полная распаковка; в app/ копировать нельзя
                        # (раньше рантайм дублировался в app/python - аудит)
                        if (staged_dir is not None
                                and rel.startswith(RUNTIME_KEY_PREFIX)):
                            rrel = rel[len(RUNTIME_KEY_PREFIX):]
                            _safe_archive_rel(rrel)
                            target = staged_dir / rrel
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(info) as src, \
                                    open(target, "wb") as out:
                                shutil.copyfileobj(src, out)
                            expected = str(runtime_manifest_files.get(
                                rel) or "").lower()
                            if len(expected) != 64:
                                raise RuntimeError(
                                    "в обновлении нет контрольной суммы "
                                    f"runtime-файла: {rel}")
                            if _sha256(target) != expected:
                                raise RuntimeError(
                                    f"файл обновления повреждён: {rel}")
                            runtime_files += 1
                            continue
                        skipped_nonapp += 1
                        continue
                    if not rel or rel == "update_manifest.json":
                        continue
                    _safe_archive_rel(rel)
                    if is_user_file(rel):
                        skipped_user += 1
                        continue
                    target_tmp = (tmp_dir / rel)
                    try:
                        target_tmp.resolve().relative_to(tmp_dir.resolve())
                    except ValueError:
                        raise RuntimeError(
                            f"небезопасный путь в архиве: {rel}")
                    target_tmp.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target_tmp, "wb") as out:
                        shutil.copyfileobj(src, out)
                    # Сверяем только известные манифесту файлы: сам zip уже
                    # подтверждён подписью, а неизвестные (bat/readme и т.п.)
                    # исторически в манифест не попадали.
                    expected = str(manifest_files.get(rel) or "").lower()
                    if expected and _sha256(target_tmp) != expected:
                        raise RuntimeError(f"файл обновления повреждён: {rel}")
                    extracted.append(rel)

                if staged_dir is not None:
                    _validate_staged_runtime(staged_dir, manifest_runtime)
                    cb("Компоненты Python подготовлены")

                # Копирование с ОТКАТОМ (ревью 18.10): занятый файл
                # (антивирус, запущенный exe) раньше оставлял смешанную
                # установку. Оригиналы сохраняем и при сбое возвращаем.
                rollback_dir = tmp_dir / "__rollback__"
                root_res = root_dir.resolve()
                replaced: list[str] = []
                try:
                    for rel in extracted:
                        target = root_dir / rel
                        try:
                            target.resolve().relative_to(root_res)
                        except ValueError:
                            raise RuntimeError(
                                f"небезопасный путь в архиве: {rel}")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        # Не трогаем уже идентичный файл: WinDivert.dll/sys
                        # могут держаться загруженным драйвером, а обновление
                        # не должно падать из-за неизменившегося файла.
                        try:
                            if (target.is_file()
                                    and _sha256(target) == _sha256(tmp_dir / rel)):
                                skipped_identical += 1
                                cb(f"без изменений: {rel}")
                                continue
                        except OSError:
                            pass
                        if target.exists():
                            bak = rollback_dir / rel
                            bak.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(target, bak)
                        # Фиксируем ДО copy: если copy упадёт после open("wb"),
                        # rollback обязан восстановить/удалить этот файл.
                        replaced.append(rel)
                        shutil.copyfile(tmp_dir / rel, target)
                        updated += 1
                        cb(f"обновлено: {rel}")
                    # Post-check ВНУТРИ откатываемого блока: несоответствие
                    # версии/файлов/runtime отменяет изменения (P1 T22).
                    validate_app = bool(prefix) and "core/config.py" in app_paths
                    post = _post_apply_problems(
                        root_dir, expected_version, runtime_dir,
                        manifest_runtime, staged_dir, validate_app)
                    if post:
                        raise RuntimeError("; ".join(post))
                except Exception as e:  # noqa: BLE001
                    for rel in reversed(replaced):
                        bak = rollback_dir / rel
                        if bak.exists():
                            try:
                                shutil.copyfile(bak, root_dir / rel)
                            except OSError:
                                pass
                        else:
                            # Файла не было до обновления - убираем недописанный.
                            try:
                                (root_dir / rel).unlink(missing_ok=True)
                            except OSError:
                                pass
                    raise RuntimeError(
                        f"обновление не применено (откат выполнен): {e}") from e
                staged_runtime = staged_dir
                staged_cleanup = None
                success = True
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
    finally:
        # Неудачный апдейт не должен оставлять мусорный python.new: следующий
        # запуск иначе увидит «подготовленный» рантайм неизвестного качества.
        if not success and staged_cleanup is not None:
            shutil.rmtree(staged_cleanup, ignore_errors=True)
    return {"updated": updated, "skipped_identical": skipped_identical,
            "skipped_user": skipped_user,
            "skipped_nonapp": skipped_nonapp,
            "backup": str(backup) if backup else None,
            "runtime_staged": str(staged_runtime) if staged_runtime else None,
            "runtime_files": runtime_files,
            "runtime_skipped": runtime_skipped,
            "runtime_rev": manifest_rev}


def prepare_exe_update(zip_path: Path, root_dir: Path,
                       exe_name: str = "Zapret2GUI.exe",
                       exe_sha256: Optional[str] = None,
                       mei_dir: Optional[str] = None) -> Path:
    """exe-версия обновляет СЕБЯ через батник: zip уже скачан - извлечь exe
    рядом, сверять его sha256 (из подписанного манифеста), создать
    updater-bat, который после закрытия текущего процесса заменит exe и
    запустит новый. Возвращает путь к батнику; запускает его вызывающий
    (launch_update_bat) - иначе батник умрёт вместе с нами.
    Fail-closed: без совпадения хеша .new и батник не создаются.

    Батник ПЕРЕЗАПИСЫВАЕТ САМ СЕБЯ, поэтому пишется без абсолютных путей
    (только %~dp0 - каталог самого батника) и в ASCII: иначе установка в
    папку с кириллицей или знаками препинания ломает и кодировку, и парсинг
    командной строки cmd. Каталог onefile-распаковки (%TEMP%\\_MEI...) не
    удаляется, если процесс убит taskkill'ом - передаём его и чистим.
    """
    import sys as _sys

    if not exe_sha256:
        raise RuntimeError("контрольная сумма exe не подтверждена")
    # Имя exe попадает в taskkill / move - оставляем только безопасные символы.
    if not exe_name or any(c in exe_name for c in '/\\:*?"<>|'):
        raise RuntimeError("недопустимое имя исполняемого файла")
    with zipfile.ZipFile(zip_path) as zf:
        # next() без default давал StopIteration с пустым текстом ошибки -
        # пользователь видел «обновление не удалось: ""» (P3 аудита).
        exe_member = next(
            (n for n in zf.namelist() if n.endswith(exe_name)), None)
        if not exe_member:
            raise RuntimeError(f"в архиве обновления нет {exe_name}")
        data = zf.read(exe_member)

    new_exe = root_dir / f"{exe_name}.new"
    new_exe.write_bytes(data)
    if _sha256(new_exe) != exe_sha256.lower():
        new_exe.unlink(missing_ok=True)
        raise RuntimeError("исполняемый файл обновления повреждён")

    cur_exe = Path(_sys.executable)
    # Батник заменяет <каталог>/<exe_name> и убивает процесс по имени образа.
    # Если запущенное имя не совпадает (другой каталог/имя) - замена не
    # сработает: taskkill не убьёт нас, .new останется лежать. Проверяем
    # только в реальном onefile (frozen): сервер идёт по ветке exe только
    # тогда, а из исходников/тестов батник не используется.
    if getattr(_sys, "frozen", False) and cur_exe.name.lower() != exe_name.lower():
        new_exe.unlink(missing_ok=True)
        raise RuntimeError(
            f"имя запущенного файла ({cur_exe.name}) не совпадает с "
            f"обновляемым ({exe_name}) - самообновление отменено, "
            f"скачайте новую версию вручную")

    log = root_dir / "logs" / "update_self.log"
    lines = [
        "@echo off",
        "rem Self-update: replace the exe and restart. Paths are relative to"
        " this script (%%~dp0) so a non-ASCII install path cannot break cmd.",
        # ping вместо timeout: в DETACHED-процессе без консоли timeout
        # завершается сразу (ревью 18.10), ping даёт реальную паузу.
        "ping -n 5 127.0.0.1 >nul",
        f'taskkill /F /IM {exe_name} >nul 2>&1',
        "ping -n 3 127.0.0.1 >nul",
        f'move /y "%~dp0{exe_name}.new" "%~dp0{exe_name}" >nul',
        "if errorlevel 1 (",
        f'  >>"%~dp0logs\\update_self.log" echo %DATE% %TIME% move FAILED',
        f'  >>"%~dp0logs\\update_self.log" echo %DATE% %TIME% kept: "%~dp0{exe_name}.new"',
        # Не оставляем пользователя без приложения: даже при неудачном move
        # запускаем старый exe. Сам update.bat удалится ниже.
        f'  start "" "%~dp0{exe_name}"',
        "  del \"%~f0\"",
        "  exit /b 1",
        ")",
    ]
    if mei_dir:
        # Только каталог, который сам PyInstaller создал для этого процесса.
        safe_mei = (mei_dir.replace("%", "%%").replace('"', "")
                   .replace("&", "^&").replace("|", "^|"))
        lines += [f'rmdir /s /q "{safe_mei}" >nul 2>&1']
    lines += [
        f'>>"%~dp0logs\\update_self.log" echo %DATE% %TIME% replaced, starting',
        f'start "" "%~dp0{exe_name}"',
        'del "%~f0"',
    ]
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    bat_path = root_dir / "_update_self.bat"
    # newline="": иначе текстовый режим допишет \r к нашим \r\n и батник
    # получится с \r\r\n (нарушение правила .bat в AGENTS.md).
    with open(bat_path, "w", encoding="ascii", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return bat_path


def launch_update_bat(bat_path: Path) -> None:
    """Запустить батник самообновления ОТДЕЛЬНЫМ процессом.

    Он переживает наш процесс: taskkill внутри батника убивает нас, а сам он
    уже отвязан (DETACHED_PROCESS + своя группа). Ошибка здесь означает, что
    обновление скачано и проверено, но замена exe не произойдёт - пишем в
    лог, чтобы это не осталось незамеченным.
    """
    import subprocess as _sp
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= getattr(_sp, name, 0)
    try:
        # cmd /c + ВНЕШНИЙ кавычечный слой: путь с пробелами/скобками
        # (Program Files (x86)) иначе теряет кавычки, и запускается только
        # первый токен — "C:\Program" (ревью 18.10).
        cmdline = f'cmd.exe /c ""{bat_path}""'
        _sp.Popen(cmdline, cwd=str(bat_path.parent),
                  close_fds=True, creationflags=flags)
    except (OSError, _sp.SubprocessError) as e:
        _upd_log(f"update: не удалось запустить батник самообновления: {e!r}")
        raise RuntimeError(
            "обновление скачано, но запустить замену программы не получилось - "
            "перезапустите программу вручную") from e


def prepare_app_restart_bat(root_dir: Path, pid: int,
                            runtime_staged: Optional[Path] = None,
                            runtime_dir: Optional[Path] = None) -> Optional[Path]:
    """Перезапуск приложения для portable/dev (не frozen): тот же
    интерпретатор + тот же скрипт после паузы. Frozen обновляется через
    `_update_self.bat` (prepare_exe_update) - этот батник не для него.

    runtime_staged/runtime_dir (portable-апдейт): перед стартом батник
    атомарно переключает python/ -> <runtime>.new, а при сбое возвращает
    <runtime>.old (живой каталог нельзя заменить, пока запущен pythonw.exe).
    Все пути пишутся относительно %~dp0: установка с пробелами/кириллицей
    не ломает ASCII-батник. Возвращает путь."""
    import sys as _sys

    root_res = Path(root_dir).resolve()
    use_runtime = runtime_staged is not None or runtime_dir is not None
    if use_runtime and (runtime_staged is None or runtime_dir is None):
        raise RuntimeError(
            "runtime_staged и runtime_dir задаются только вместе")

    def _cmd(path: Path) -> str:
        path = Path(path).resolve()
        try:
            return f"%~dp0{path.relative_to(root_res)}"
        except ValueError:
            pass
        # portable: интерпретатор лежит в <root>/python, а root_dir = <root>/app
        try:
            if (path.parent.name.lower() == RUNTIME_DIR_NAME
                    and path.parent.parent == root_res.parent
                    and _looks_like_runtime(path.parent)):
                return f"%~dp0..\\{RUNTIME_DIR_NAME}\\{path.name}"
        except OSError:
            pass
        return str(path)

    exe_cmd = _cmd(Path(_sys.executable))
    script_cmd = _cmd(Path(_sys.argv[0]).resolve())
    lines = [
        "@echo off",
        "rem Self-restart: kill this app instance, start it again.",
    ]
    if use_runtime:
        lines.append("rem Runtime switch: python -> python.old, python.new ->"
                     " python (rollback on failure).")
    lines += [
        "ping -n 3 127.0.0.1 >nul",
        f"taskkill /F /PID {int(pid)} >nul 2>&1",
        # после kill нужна пауза: каталог python/ переименовывается только
        # когда процесс полностью отпустил образ/файлы.
        "ping -n 5 127.0.0.1 >nul" if use_runtime else "ping -n 3 127.0.0.1 >nul",
    ]
    if use_runtime:
        rt = Path(runtime_dir)
        rt_tok = _bat_path_token(rt, root_res)
        st_tok = _bat_path_token(Path(runtime_staged), root_res)
        old_tok = _bat_path_token(
            rt.with_name(rt.name + RUNTIME_OLD_SUFFIX), root_res)
        lines += [
            f'if not exist "{st_tok}" goto start_app',
            f'if exist "{old_tok}" rmdir /s /q "{old_tok}" >nul 2>&1',
            f'move /y "{rt_tok}" "{old_tok}" >nul 2>&1',
            "if errorlevel 1 goto switch_failed",
            f'move /y "{st_tok}" "{rt_tok}" >nul 2>&1',
            "if errorlevel 1 goto rollback",
            f'rmdir /s /q "{old_tok}" >nul 2>&1',
            "goto start_app",
            ":rollback",
            ">>\"%~dp0logs\\update_self.log\" echo %DATE% %TIME% "
            "runtime switch FAILED - rollback",
            f'move /y "{old_tok}" "{rt_tok}" >nul 2>&1',
            "goto start_app",
            ":switch_failed",
            ">>\"%~dp0logs\\update_self.log\" echo %DATE% %TIME% "
            "runtime move FAILED - keep current",
            ":start_app",
        ]
    lines += [
        f'start "" "{exe_cmd}" "{script_cmd}"',
        'del "%~f0"',
    ]
    text = "\r\n".join(lines) + "\r\n"
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        # Абсолютный путь с не-ASCII (запуск из исходников в такой папке):
        # ASCII-батник НЕ пишем молча битым - пусть пользователь перезапустит
        # вручную (воркер это ловит и не считает автоперезапуск удавшимся).
        raise RuntimeError(
            "автоперезапуск невозможен: путь установки содержит не-ASCII "
            "символы - перезапустите программу вручную") from None
    bat_path = root_dir / "_restart_app.bat"
    # newline="": текстовый режим дописал бы \r к нашим \r\n (правило .bat).
    with open(bat_path, "w", encoding="ascii", newline="") as f:
        f.write(text)
    return bat_path


def write_manifest(base_dir: Path, version: str,
                   runtime_dir: Optional[Path] = None) -> Path:
    """update_manifest.json: версия + SHA256 всех SYSTEM-файлов дистрибутива
    (юзер-файлы в манифест не попадают - updater их никогда не трогает).

    runtime_dir (portable): добавляется секция "runtime" - ревизия, версия
    Python и SHA256 файлов python/** (ключи как пути в архиве). Апдейтер
    распаковывает их в python.new и переключает после выхода процесса;
    наличие хешей = проверка каждого файла до записи. Формат аддитивный:
    старые апдейтеры читают только "files" и не замечают новую секцию."""
    files: dict[str, str] = {}
    for p in sorted(base_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base_dir).as_posix()
        if is_user_file(rel):
            continue
        if rel.endswith(".log") or rel in ("data_version.txt",):
            continue
        # __pycache__/*.pyc - артефакты сборки, в архив их не кладут
        # (build_portable чистит их ПОСЛЕ сбора). Попадая в манифест, они
        # давали записи о файлах, которых в обновлении нет: манифест
        # переставал описывать ровно то, что приедет к пользователю.
        if "__pycache__" in rel.split("/") or rel.endswith((".pyc", ".pyo")):
            continue
        files[rel] = _sha256(p)
    doc: dict = {"version": version, "files": files}
    if runtime_dir is not None:
        rt = Path(runtime_dir)
        marker = _read_json_obj(rt / RUNTIME_MARKER_NAME)
        packages = marker.get("packages")
        if not isinstance(packages, list) or not packages:
            packages = list(RUNTIME_PACKAGES)
        runtime_files: dict[str, str] = {}
        for p in sorted(rt.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(rt).as_posix()
            if "__pycache__" in rel.split("/") or rel.endswith((".pyc", ".pyo")):
                continue
            runtime_files[f"{RUNTIME_KEY_PREFIX}{rel}"] = _sha256(p)
        doc["runtime"] = {
            "rev": str(marker.get("rev") or ""),
            "python": str(marker.get("python") or ""),
            "packages": [str(x) for x in packages],
            "files": runtime_files,
        }
    manifest = base_dir / "update_manifest.json"
    manifest.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return manifest


def service_args_stale(stored_binpath: str, new_args: list[str]) -> bool:
    """True, если аргументы установленной службы отличаются от собранных
    из НОВЫХ файлов (после обновления) - службе нужен пересбор.

    binPath нового формата ("exe" @"conf") хранит аргументы в conf-файле -
    сравниваем его построчно (токен на строку, DQ-кавычки снимаем)."""
    try:
        if not stored_binpath:
            return False
        from core.utils import split_windows_cmdline
        tokens = split_windows_cmdline(stored_binpath.replace('\\"', '"'))
        if len(tokens) >= 2 and tokens[1].startswith("@"):
            conf = Path(tokens[1][1:])
            old_args = []
            for line in conf.read_text(encoding="utf-8").splitlines():
                t = line.strip()
                if not t:
                    continue
                if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
                    t = t[1:-1]
                old_args.append(t)
        else:
            old_args = tokens[1:]  # exe-токен пропускаем, сравниваем аргументы
        new_tokens = [str(a) for a in new_args]
        if len(old_args) != len(new_tokens):
            return True
        for old, new in zip(old_args, new_tokens):
            if old.replace("/", "\\").lower() != new.replace("/", "\\").lower():
                return True
        return False
    except Exception:
        return False  # не смогли прочитать - не пугаем пользователя