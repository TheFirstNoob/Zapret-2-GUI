"""Подпись релиза: release.json + release.json.sig (Ed25519).

Запуск после сборки дистрибутивов, перед публикацией релиза:
    python tools/security/sign_release.py --version 0.9 --tag Pre-Release-0.9 \
        --key C:\\offline\\zapret2_update_signing_key.txt

Пишет release.json и release.json.sig в корень репозитория: их прикрепляют к
GitHub-релизу и коммитят (jsDelivr-зеркало). Приложение ставит обновление
только с валидной подписью (fail-closed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core import update_verify as uv  # noqa: E402
from core.updater import (MANIFEST_NAME, MANIFEST_SCHEMA,  # noqa: E402
                          MANIFEST_SIG_NAME)

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = {
    "exe": "Zapret2GUI.zip",
    "portable": "Zapret2GUI-portable.zip",
    "lite": "Zapret2GUI-lite.zip",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_version(text: str) -> str:
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", text or "")
    return m.group(1) if m else ""


def _zip_version(zf: zipfile.ZipFile) -> str:
    for name in ("VERSION", "app/VERSION"):
        try:
            return zf.read(name).decode("utf-8-sig").strip()
        except KeyError:
            continue
    # portable не кладёт VERSION в архив - версия есть в update_manifest.json
    for name in ("update_manifest.json", "app/update_manifest.json"):
        try:
            data = json.loads(zf.read(name).decode("utf-8-sig"))
            ver = str(data.get("version") or "").strip()
            if ver:
                return ver
        except (KeyError, ValueError):
            continue
    return ""


def _zip_engine_version(zip_path: Path) -> str:
    """Версия bin/winws2.exe из portable/lite архива (extract + --version)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            member = next((n for n in zf.namelist()
                           if n.replace("\\", "/").lower().endswith("bin/winws2.exe")),
                          None)
            if not member:
                return ""
            tmp = Path(tempfile.mkdtemp(prefix="zapret2_sign_"))
            try:
                out = tmp / "winws2.exe"
                # winws2 - Cygwin-бинарь: нужен весь набор bin/ (cygwin1.dll,
                # WinDivert.dll), иначе STATUS_DLL_NOT_FOUND.
                base_dir = member.rsplit("/", 1)[0] if "/" in member else ""
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    if base_dir and not name.startswith(base_dir + "/"):
                        continue
                    flat = name.rsplit("/", 1)[-1]
                    if flat.lower() in ("winws2.exe", "cygwin1.dll",
                                        "windivert.dll", "windivert64.sys"):
                        (tmp / flat).write_bytes(zf.read(name))
                r = subprocess.run([str(out), "--version"], capture_output=True,
                                   text=True, encoding="oem", errors="replace",
                                   timeout=15, cwd=str(tmp),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                m = re.search(r"github version v(\d+\.\d+(?:\.\d+)?)",
                              (r.stdout or "") + (r.stderr or ""))
                return m.group(1) if m else ""
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    except (OSError, zipfile.BadZipFile, subprocess.SubprocessError):
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Подпись релиза")
    ap.add_argument("--version", required=True, help='например "0.9"')
    ap.add_argument("--tag", required=True, help="например Pre-Release-0.9")
    ap.add_argument("--key", required=True, help="файл с приватным ключом")
    ap.add_argument("--zips-dir", default=str(REPO_ROOT / "Windows build"))
    ap.add_argument("--out-dir", default=str(REPO_ROOT))
    args = ap.parse_args()

    key_text = Path(args.key).read_text(encoding="utf-8")
    m_sk = re.search(r"secret_hex:\s*([0-9a-fA-F]{64})", key_text)
    if not m_sk:
        print("Не нашёл secret_hex в файле ключа")
        return 1
    sk = m_sk.group(1).lower()
    pk = uv.public_key_from_secret(sk)
    m_pk = re.search(r"public_hex:\s*([0-9a-fA-F]{64})", key_text)
    if m_pk and m_pk.group(1).lower() != pk:
        print("Ключ не совпадает с public_hex в файле — не тот файл?")
        return 1

    # Fail-closed (аудит 2026-11-14): подписывать неполный набор нельзя -
    # иначе релиз уедет без части артефактов / со старой версией.
    version_norm = _norm_version(args.version)
    if not version_norm or _norm_version(args.tag) != version_norm:
        print(f"Версия и тег не согласованы: version={args.version} tag={args.tag}")
        return 1
    if uv.PUBKEY and pk != uv.PUBKEY:
        print("Публичный ключ файла не совпадает с вшитым PUBKEY - не тот ключ?")
        return 1
    repo_exe = REPO_ROOT / "bin" / "winws2.exe"
    repo_engine = ""
    if not repo_exe.exists():
        print("Ошибка: нет bin/winws2.exe - нечем сверить версию движка в архивах")
        return 1
    if repo_exe.exists():
        try:
            r = subprocess.run([str(repo_exe), "--version"], capture_output=True,
                               text=True, encoding="oem", errors="replace",
                               timeout=15, cwd=str(REPO_ROOT),
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            m_eng = re.search(r"github version v(\d+\.\d+(?:\.\d+)?)",
                              (r.stdout or "") + (r.stderr or ""))
            repo_engine = m_eng.group(1) if m_eng else ""
        except (OSError, subprocess.SubprocessError):
            repo_engine = ""
    if not repo_engine:
        print("Ошибка: не удалось определить версию bin/winws2.exe - "
              "fail-closed (не подписываем без сверки движка)")
        return 1
    zips_dir = Path(args.zips_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    artifacts: dict[str, dict] = {}
    for kind, fname in ARTIFACTS.items():
        p = zips_dir / fname
        if not p.is_file():
            print(f"Ошибка: нет архива {p} (нужны все три: {', '.join(ARTIFACTS.values())})")
            return 1
        art = {"file": fname, "size": p.stat().st_size, "sha256": _sha256(p)}
        if kind in ("portable", "lite"):
            with zipfile.ZipFile(p) as zf:
                inner_v = _norm_version(_zip_version(zf))
            if inner_v != version_norm:
                print(f"Ошибка: VERSION внутри {fname} = {inner_v!r}, "
                      f"а подписываем {version_norm!r}")
                return 1
            eng = _zip_engine_version(p)
            if not eng:
                print(f"Ошибка: не удалось определить версию winws2 в {fname}")
                return 1
            if repo_engine and eng != repo_engine:
                print(f"Ошибка: в {fname} движок v{eng}, а в репо v{repo_engine} - "
                      "соберите артефакты из HEAD")
                return 1
        if kind == "exe":
            # Хеш самого exe внутри архива: апдейтер сверит его после
            # распаковки, до подмены файла.
            with zipfile.ZipFile(p) as zf:
                member = next((n for n in zf.namelist()
                               if n.endswith("Zapret2GUI.exe")), None)
                if not member:
                    print(f"Ошибка: в {fname} нет Zapret2GUI.exe")
                    return 1
                art["exe_sha256"] = hashlib.sha256(zf.read(member)).hexdigest()
        artifacts[kind] = art
    if not artifacts:
        print("Не найдено ни одного архива для подписи")
        return 1

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "version": args.version,
        "tag": args.tag,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifacts": artifacts,
    }
    raw = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    sig = uv.sign(raw, sk)
    if not uv.verify(raw, sig, pk):
        print("Самопроверка подписи не прошла — релиз не выпускать")
        return 1

    (out_dir / MANIFEST_NAME).write_bytes(raw)
    (out_dir / MANIFEST_SIG_NAME).write_text(sig + "\n", encoding="ascii")
    print("Подписано:", out_dir / MANIFEST_NAME, "+", out_dir / MANIFEST_SIG_NAME)
    print("Отпечаток ключа:", uv.pubkey_fingerprint(pk))
    for kind, art in artifacts.items():
        print(f"  {kind}: {art['file']}  {art['sha256']}")
    print()
    print("Дальше: прикрепите к GitHub-релизу 3 zip-архива, release.json и")
    print("release.json.sig (байт-в-байт те же файлы) и закоммитьте")
    print("release.json + release.json.sig в main (для jsDelivr-зеркала).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
