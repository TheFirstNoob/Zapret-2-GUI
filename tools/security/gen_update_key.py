"""Генерация офлайн-ключей подписи релизов (Ed25519, RFC 8032).

Приватный ключ НИКОГДА не коммитится и не хранится на GitHub — только офлайн
(менеджер паролей + бумажная копия). В репозиторий уходит лишь публичный ключ
из вывода скрипта.

Запуск:
    python tools/security/gen_update_key.py
    python tools/security/gen_update_key.py --out D:\\keys\\zapret2.txt
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core import update_verify as uv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser(description="Ключи подписи релизов")
    ap.add_argument("--out",
                    default=str(Path.home() / "zapret2_update_signing_key.txt"),
                    help="куда сохранить приватный ключ (вне репозитория)")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    if REPO_ROOT == out or REPO_ROOT in out.parents:
        print("Отказ: ключ нельзя хранить внутри репозитория. Укажите путь вне репо.")
        return 1
    if out.exists():
        print(f"Отказ: файл уже существует: {out}")
        return 1
    sk, pk = uv.keygen()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out.write_text(
        "Zapret 2 GUI — приватный ключ подписи релизов (Ed25519).\n"
        f"Создан: {stamp}\n"
        "ХРАНИТЬ ОФЛАЙН: менеджер паролей + бумажная копия. Не коммитить,\n"
        "не пересылать, не держать на GitHub/в облаке: утечка ключа = чужие\n"
        "подписанные обновления.\n\n"
        f"secret_hex: {sk}\n"
        f"public_hex: {pk}\n",
        encoding="utf-8")
    print("Приватный ключ сохранён:", out)
    print("Перенесите файл в офлайн-хранилище и удалите локальную копию.")
    print()
    print("Публичный ключ (вшить в core/update_verify.py):")
    print(f'PUBKEY = "{pk}"')
    print("Отпечаток ключа:", uv.pubkey_fingerprint(pk))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
