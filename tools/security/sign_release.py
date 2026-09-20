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
import sys
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

    zips_dir = Path(args.zips_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    artifacts: dict[str, dict] = {}
    for kind, fname in ARTIFACTS.items():
        p = zips_dir / fname
        if not p.is_file():
            print(f"Пропуск: нет архива {p}")
            continue
        art = {"file": fname, "size": p.stat().st_size, "sha256": _sha256(p)}
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
