"""Генератор TLS ClientHello блобов для фейков zapret2.

Блоб фейка — это просто валидный TLS ClientHello с «белым» SNI: DPI видит
его и пропускает соединение, а сервер такой пакет отбрасывает как мусор
(тот же seq приходит дважды, побеждает настоящий ClientHello).

Использование:
    python tools/make_blob.py chat.wb.ru                 # -> blobs/tls_clienthello_chat_wb_ru.bin
    python tools/make_blob.ru example.com out.bin

Синтетический ClientHello структурно валиден (TLS 1.3 + 1.2, x25519
key_share, SNI) — DPI не отличит его от браузерного по структуре, а от
«палевных» фейков его отличает только отпечаток. Реальные захваченные
ClientHello (как google_tls) всегда чуть лучше — но синтетика работает
и её можно делать на любой домен за секунду.
"""
from __future__ import annotations

import os
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _u16(n: int) -> bytes:
    return struct.pack(">H", n)


def _u24(n: int) -> bytes:
    return struct.pack(">I", n)[1:]


def _ext(etype: int, payload: bytes) -> bytes:
    return _u16(etype) + _u16(len(payload)) + payload


def _sni(hostname: str) -> bytes:
    # RFC 6066 ServerNameList: list_len + [name_type=0 + host_len + name]
    name = hostname.encode()
    entry = bytes([0]) + _u16(len(name)) + name
    return _ext(0x0000, _u16(len(entry)) + entry)


def build_client_hello(hostname: str) -> bytes:
    rnd = os.urandom(32)
    session = bytes([32]) + os.urandom(32)

    # Современный набор (TLS1.3 + сильные 1.2), как у браузеров.
    ciphers = bytes.fromhex(
        "1301" "1302" "1303" "c02b" "c02f" "c02c" "c030" "cca9" "cca8"
        "c013" "c014" "009c" "009d" "002f" "0035")
    suites = _u16(len(ciphers)) + ciphers
    compression = bytes([1, 0])

    exts = b""
    exts += _sni(hostname)
    exts += _ext(0x0017, b"")                                    # extended_master_secret
    exts += _ext(0x0016, b"")                                    # encrypt_then_mac
    exts += _ext(0x0023, b"")                                    # session_ticket
    # supported_groups: x25519, secp256r1, secp384r1
    exts += _ext(0x000A, _u16(6) + bytes.fromhex("001d0017001e"))
    exts += _ext(0x000B, bytes([1, 0]))                          # ec_point_formats
    # signature_algorithms
    sigalgs = bytes.fromhex("0403" "0503" "0603" "0804" "0805" "0806" "0401" "0501" "0601" "0201")
    exts += _ext(0x000D, _u16(len(sigalgs)) + sigalgs)
    # supported_versions: TLS 1.3 + 1.2
    exts += _ext(0x002B, bytes([2, 3, 4, 3, 3]))
    # key_share: x25519 (32 случайных байта — сервер отбросит приветствие,
    # завершить handshake с этим ключом всё равно невозможно)
    exts += _ext(0x0033, _u16(36) + bytes.fromhex("001d") + _u16(32) + os.urandom(32))

    body = (b"\x03\x03" + rnd + session + suites + compression
            + _u16(len(exts)) + exts)
    handshake = b"\x01" + _u24(len(body)) + body
    # TLS record: version 0301 (как у браузеров в ClientHello)
    return b"\x16\x03\x01" + _u16(len(handshake)) + handshake


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    hostname = sys.argv[1].strip().lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", hostname):
        print(f"не похоже на домен: {hostname}")
        sys.exit(1)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else \
        ROOT / "blobs" / f"tls_clienthello_{hostname.replace('.', '_')}.bin"
    blob = build_client_hello(hostname)
    out.write_bytes(blob)
    print(f"OK: {out}  ({len(blob)} байт, SNI={hostname})")


if __name__ == "__main__":
    main()
