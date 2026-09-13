"""Updater (0.8): скачивание дистрибутива, бэкап юзер-файлов, честное обновление.

Контракт файлов:
  USER (никогда не трогаются): zapret2_config.json, lists/*-user.txt,
       юзерские пресеты (не из release-набора и не генерируемые), логи.
  SYSTEM (заменяются по манифесту): core/, server/, frontend/, bin/, lua/,
       blobs/, windivert/, presets/ release-набора, базовые lists/*.txt.

Источники скачивания: GitHub release asset -> jsDelivr-зеркало (CDN отдаёт
repo-файлы даже на сетях, где объекты GitHub IP-блокированы).
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
    "lists/list-include-user.txt",
    "lists/list-exclude-user.txt",
    "lists/ipset-include-user.txt",
    "lists/ipset-exclude-user.txt",
    "test_session.log",
    "debug_winws2.log",
)

USER_PRESET_IGNORE = ("custom",)  # генерируется тестером — не трогаем


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_user_file(rel: str) -> bool:
    """Файл, который обновление никогда не трогает."""
    rel = rel.replace("/", "\\").lstrip("\\")
    p = Path(rel)
    if rel in USER_FILES:
        return True
    if p.parts[:1] == ("lists",) and p.name.endswith("-user.txt"):
        return True
    if p.parts[:1] == ("presets",) and p.name.endswith(".txt"):
        stem = p.stem
        if stem not in RELEASE_PRESETS and stem not in USER_PRESET_IGNORE:
            return True  # юзерский пресет (не из release-набора)
    return False


def download_url(kind: str, tag: str) -> tuple[str, str]:
    """(primary, mirror) URL архива для kind: 'exe'|'portable'|'lite'."""
    fname = {
        "exe": "Zapret2GUI.zip",
        "portable": "Zapret2GUI-portable.zip",
        "lite": "Zapret2GUI-lite.zip",
    }[kind]
    gh = f"https://github.com/{_REPO}/releases/download/{tag}/{fname}"
    mirror = (f"https://cdn.jsdelivr.net/gh/{_REPO}@{tag}/"
              f"Windows%20build/{fname}")
    return gh, mirror


def fetch_sha256(kind: str, tag: str, dest_dir: Path) -> Optional[str]:
    """SHA256 из release-ассетов (<archive>.sha256): primary -> jsDelivr.
    None = файл не найден (проверка целостности пропускается)."""
    fname = {
        "exe": "Zapret2GUI.zip.sha256",
        "portable": "Zapret2GUI-portable.zip.sha256",
        "lite": "Zapret2GUI-lite.zip.sha256",
    }[kind]
    gh = f"https://github.com/{_REPO}/releases/download/{tag}/{fname}"
    mirror = (f"https://cdn.jsdelivr.net/gh/{_REPO}@{tag}/"
              f"Windows%20build/{fname}")
    dest = dest_dir / fname
    for url in (gh, mirror):
        try:
            _download(url, dest, timeout=60)
            got = dest.read_text(encoding="ascii", errors="replace").strip()
            dest.unlink(missing_ok=True)
            return got or None
        except Exception:
            continue
    dest.unlink(missing_ok=True)
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
    """Скачать zip обновления: GitHub asset -> jsDelivr-зеркало.
    Проверяет SHA256 (expected — из release-ассетов)."""
    dest = dest_dir / f"update_{kind}.zip"
    primary, mirror = download_url(kind, tag)
    for url in (primary, mirror):
        try:
            _download(url, dest)
            break
        except Exception:
            continue
    else:
        raise RuntimeError("не удалось скачать обновление (GitHub и зеркало)")
    got = _sha256(dest)
    if sha256_expected and got != sha256_expected:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"SHA256 скачанного файла не совпал ({got[:16]}…)")
    return dest


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


def apply_portable(zip_path: Path, root_dir: Path,
                   progress_cb=None) -> dict:
    """Обновить portable/lite-папку из скачанного zip, СОХРАНЯЯ юзер-файлы.

    Распаковываются только SYSTEM-файлы; юзер-файлы (конфиг, *-user.txt,
    юзерские пресеты, логи) не трогаются ни в каком виде.
    Возвращает {updated: N, skipped_user: N, backup: path|None}."""
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
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        # portable-архив кладёт код в app/, lite — в корне архива
        prefix = "app/" if any(n.startswith("app/") for n in names) else ""
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename
            if prefix and rel.startswith(prefix):
                rel = rel[len(prefix):]
            if is_user_file(rel):
                skipped_user += 1
                continue
            target = root_dir / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                updated += 1
                cb(f"обновлено: {rel}")
            except OSError:
                continue
    return {"updated": updated, "skipped_user": skipped_user,
            "backup": str(backup) if backup else None}


def prepare_exe_update(zip_path: Path, root_dir: Path,
                       exe_name: str = "Zapret2GUI.exe") -> Path:
    """exe-версия обновляет СЕБЯ через батник: zip уже скачан — извлечь exe
    рядом, создать updater-bat, который после закрытия текущего процесса
    заменит exe и запустит новый. Возвращает путь к батнику (его запускает
    вызывающий через Popen detached — иначе батник умрёт вместе с нами)."""
    import sys as _sys

    with zipfile.ZipFile(zip_path) as zf:
        exe_member = next(n for n in zf.namelist() if n.endswith(exe_name))
        new_exe = root_dir / f"{exe_name}.new"
        with zf.open(exe_member) as src, open(new_exe, "wb") as out:
            shutil.copyfileobj(src, out)

    cur_exe = Path(_sys.executable)
    script = (
        "@echo off\r\n"
        f"taskkill /F /IM {exe_name} >nul 2>&1\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        f"move /y \"{new_exe}\" \"{cur_exe}\" >nul\r\n"
        f"start \"\" \"{cur_exe}\"\r\n"
        "del \"%~f0\"\r\n"
    )
    bat_path = root_dir / "_update_self.bat"
    bat_path.write_text(script, encoding="ascii")
    return bat_path


def write_manifest(base_dir: Path, version: str) -> Path:
    """update_manifest.json: версия + SHA256 всех SYSTEM-файлов дистрибутива
    (юзер-файлы в манифест не попадают — updater их никогда не трогает)."""
    files: dict[str, str] = {}
    for p in sorted(base_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base_dir).as_posix()
        if is_user_file(rel):
            continue
        if rel.endswith(".log") or rel in ("data_version.txt",):
            continue
        files[rel] = _sha256(p)
    manifest = base_dir / "update_manifest.json"
    manifest.write_text(json.dumps(
        {"version": version, "files": files}, indent=2), encoding="utf-8")
    return manifest


def service_args_stale(stored_binpath: str, new_args: list[str]) -> bool:
    """True, если аргументы установленной службы отличаются от собранных
    из НОВЫХ файлов (после обновления) — службе нужен пересбор."""
    try:
        if not stored_binpath:
            return False
        import re as _re
        s = stored_binpath.replace('\\"', '"')
        tokens = [m.group(1) if m.group(1) is not None else m.group(2)
                  for m in _re.finditer(r'"([^"]*)"|(\S+)', s)]
        old_args = tokens[1:]  # exe-токен пропускаем, сравниваем аргументы
        new_tokens = [str(a) for a in new_args]
        if len(old_args) != len(new_tokens):
            return True
        for old, new in zip(old_args, new_tokens):
            if old.replace("/", "\\").lower() != new.replace("/", "\\").lower():
                return True
        return False
    except Exception:
        return False  # не смогли прочитать — не пугаем пользователя