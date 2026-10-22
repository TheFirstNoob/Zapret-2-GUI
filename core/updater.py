"""Updater (0.8): скачивание дистрибутива, бэкап юзер-файлов, честное обновление.

Контракт файлов:
  USER (никогда не трогаются): zapret2_config.json, lists/*-user.txt,
       юзерские пресеты (не из release-набора и не генерируемые), логи.
  SYSTEM (заменяются по манифесту): core/, server/, frontend/, bin/, lua/,
       blobs/, windivert/, presets/ release-набора, базовые lists/*.txt.

Источники скачивания: GitHub release asset -> jsDelivr-зеркало (CDN отдаёт
repo-файлы даже на сетях, где объекты GitHub IP-блокированы).

Подлинность: подписанный release.json (Ed25519, core.update_verify). Без
валидной подписи и подтверждённого sha256 обновление не применяется
(fail-closed) - зеркало считается недоверенным кэшем.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

_REPO = "TheFirstNoob/Zapret-2-GUI"
_UA = {"User-Agent": "Zapret2GUI"}

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
    "lists/ipset-include-user.txt",
    "lists/ipset-exclude-user.txt",
    "test_session.log",
    "test_session.old.log",
    "debug_winws2.log",
)

USER_PRESET_IGNORE = ("custom",)  # генерируется тестером - не трогаем


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
    """Файл, который обновление никогда не трогает."""
    rel = rel.replace("/", "\\").lstrip("\\")
    p = Path(rel)
    if rel in USER_FILES:
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
            _download(base + MANIFEST_NAME, m_dest, timeout=30)
            _download(base + MANIFEST_SIG_NAME, s_dest, timeout=30)
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
    if min_v and version_key(current_version) < version_key(min_v):
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


def _download(url: str, dest: Path, timeout: int = 300) -> None:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r, \
            open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
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
    backup_dir.mkdir(exist_ok=True)
    name = f"backup_{old_version.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M%S}.zip"
    backup_path = backup_dir / name
    try:
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
    except OSError:
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
    except OSError:
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
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename.replace("/", "\\")
            # защита от path traversal внутри чужого zip
            if rel.startswith(("/", "\\")) or ".." in rel:
                skipped += 1
                continue
            is_user = (
                rel in USER_FILES
                or (Path(rel).parts[:1] == ("lists",)
                    and Path(rel).name.endswith("-user.txt"))
                or (Path(rel).parts[:1] == ("presets",)
                    and Path(rel).name.endswith(".txt")
                    and Path(rel).stem not in RELEASE_PRESETS
                    and Path(rel).stem != "custom")
            )
            if not is_user:
                skipped += 1
                continue
            target = root_dir / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                imported += 1
            except OSError:
                skipped += 1
    return imported, skipped


def apply_portable(zip_path: Path, root_dir: Path,
                   progress_cb=None) -> dict:
    """Обновить portable/lite-папку из скачанного zip, СОХРАНЯЯ юзер-файлы.

    Сначала архив распаковывается во временную папку, и файлы, известные
    манифесту, сверяются по sha256 ДО записи в установку: повреждённый/
    подложенный файл ничего не успевает заменить. Юзер-файлы (конфиг,
    *-user.txt, юзерские пресеты, логи) не трогаются.
    Возвращает {updated, skipped_user, backup}."""
    def cb(x):
        if progress_cb:
            try:
                progress_cb(x)
            except Exception:
                pass

    backup = _backup_user_files(root_dir, "old")
    cb("Резервная копия настроек создана")

    updated = 0
    skipped_user = 0
    skipped_nonapp = 0
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
            manifest_files = json.loads(manifest_raw.decode("utf-8")).get(
                "files") or {}
        except Exception:
            raise RuntimeError("манифест файлов обновления повреждён")

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
                    # portable-архив: всё вне app/ (python/, install.cmd,
                    # bat-обёртки) - каркас portable, обновляется только
                    # полной распаковкой; в app/ это копировать нельзя
                    # (раньше рантайм дублировался в app/python - аудит 2026-10)
                    skipped_nonapp += 1
                    continue
                if not rel or rel == "update_manifest.json":
                    continue
                parts = Path(rel).parts
                if (rel.startswith(("/", "\\")) or ".." in parts
                        or ":" in parts[0]):
                    raise RuntimeError(f"небезопасный путь в архиве: {rel}")
                if is_user_file(rel):
                    skipped_user += 1
                    continue
                target_tmp = (tmp_dir / rel)
                try:
                    target_tmp.resolve().relative_to(tmp_dir.resolve())
                except ValueError:
                    raise RuntimeError(f"небезопасный путь в архиве: {rel}")
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

            # Копирование с ОТКАТОМ (ревью 18.10): занятый файл (антивирус,
            # запущенный exe) раньше оставлял смешанную установку. Сохраняем
            # оригиналы во временный backup и при сбое возвращаем их.
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
                    if target.exists():
                        bak = rollback_dir / rel
                        bak.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(target, bak)
                    shutil.copyfile(tmp_dir / rel, target)
                    replaced.append(rel)
                    updated += 1
                    cb(f"обновлено: {rel}")
            except Exception as e:  # noqa: BLE001
                for rel in reversed(replaced):
                    bak = rollback_dir / rel
                    if bak.exists():
                        try:
                            shutil.copyfile(bak, root_dir / rel)
                        except OSError:
                            pass
                raise RuntimeError(
                    f"обновление не применено (откат выполнен): {e}") from e
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    return {"updated": updated, "skipped_user": skipped_user,
            "skipped_nonapp": skipped_nonapp,
            "backup": str(backup) if backup else None}


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
        exe_member = next(n for n in zf.namelist() if n.endswith(exe_name))
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


def prepare_app_restart_bat(root_dir: Path,
                            pid: int) -> Optional[Path]:
    """Перезапуск приложения для portable/dev (не frozen): тот же
    интерпретатор + тот же скрипт после паузы. Frozen обновляется через
    `_update_self.bat` (prepare_exe_update) - этот батник не для него.

    Пути, лежащие внутри root_dir, пишутся через %~dp0 - установка в
    папку с кириллицей не ломает cmd (ASCII-файл). Возвращает путь."""
    import sys as _sys

    def _cmd(path: Path) -> str:
        path = Path(path)
        try:
            return f"%~dp0{path.resolve().relative_to(root_dir.resolve())}"
        except ValueError:
            return str(path)

    exe_cmd = _cmd(Path(_sys.executable))
    script_cmd = _cmd(Path(_sys.argv[0]).resolve())
    lines = [
        "@echo off",
        "rem Self-restart: kill this app instance, start it again.",
        "ping -n 3 127.0.0.1 >nul",
        f"taskkill /F /PID {int(pid)} >nul 2>&1",
        "ping -n 3 127.0.0.1 >nul",
        f'start "" "{exe_cmd}" "{script_cmd}"',
        'del "%~f0"',
    ]
    bat_path = root_dir / "_restart_app.bat"
    with open(bat_path, "w", encoding="ascii", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return bat_path


def write_manifest(base_dir: Path, version: str) -> Path:
    """update_manifest.json: версия + SHA256 всех SYSTEM-файлов дистрибутива
    (юзер-файлы в манифест не попадают - updater их никогда не трогает)."""
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
    manifest = base_dir / "update_manifest.json"
    manifest.write_text(json.dumps(
        {"version": version, "files": files}, indent=2), encoding="utf-8")
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