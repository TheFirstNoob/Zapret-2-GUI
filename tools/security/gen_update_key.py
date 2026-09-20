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
    ap.add_argument("--check", metavar="ФАЙЛ",
                    help="проверить ключ после восстановления: печатает "
                         "PUBKEY и отпечаток для сверки")
    args = ap.parse_args()

    if args.check:
        path = Path(args.check)
        if not path.is_file():
            print("Нет файла:", path)
            return 1
        import re
        text = path.read_text(encoding="utf-8")
        m = re.search(r"secret_hex:\s*([0-9a-fA-F]{64})", text)
        if not m:
            print("Не нашёл secret_hex в файле")
            return 1
        pk = uv.public_key_from_secret(m.group(1).lower())
        print(f'PUBKEY = "{pk}"')
        print("Отпечаток ключа:", uv.pubkey_fingerprint(pk))
        m2 = re.search(r"public_hex:\s*([0-9a-fA-F]{64})", text)
        if m2 and m2.group(1).lower() != pk:
            print("ВНИМАНИЕ: public_hex в файле не совпадает с секретом!")
            return 1
        if m2:
            print("Файл цел: public_hex совпадает с секретом.")
        return 0

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
        "ХРАНИТЬ: бумажная копия + шифрованная копия в облаке (7z/менеджер\n"
        "паролей). Пароль от архива — ОТДЕЛЬНО от архива. Не коммитить, не\n"
        "пересылать в мессенджерах, не держать в открытом виде на GitHub/в\n"
        "облаке: утечка ключа = чужие подписанные обновления.\n"
        "Проверка восстановленной копии:\n"
        "  python tools/security/gen_update_key.py --check <файл>\n\n"
        f"secret_hex: {sk}\n"
        f"public_hex: {pk}\n",
        encoding="utf-8")
    print("Приватный ключ сохранён:", out)
    print("Сделайте копии: бумага + шифрованный архив (пароль — отдельно от")
    print("архива), затем удалите локальную копию файла.")
    print()
    print("Публичный ключ (вшить в core/update_verify.py):")
    print(f'PUBKEY = "{pk}"')
    print("Отпечаток ключа:", uv.pubkey_fingerprint(pk))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
