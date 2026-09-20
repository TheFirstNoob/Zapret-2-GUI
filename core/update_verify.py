"""Проверка подписи обновлений: Ed25519 (RFC 8032), чистый Python.

Зачем: хеш и файл обновления берутся из одного источника (GitHub/зеркало),
поэтому подмена релиза неотличима. Подпись офлайн-ключом — независимый корень
доверия: без приватного ключа подделать манифест нельзя даже при угоне аккаунта.

Приватный ключ НИКОГДА не попадает в репозиторий/сборку — он хранится офлайн
(см. tools/security/gen_update_key.py). В рантайме приложения используется
только verify. Зависимостей нет: криптография — эталонная реализация RFC 8032.

Пока ``PUBKEY`` пуст, канал обновлений считается ненастроенным: verify всегда
возвращает False (fail-closed), приложение не ставит непроверенные обновления.
"""
from __future__ import annotations

import base64
import hashlib
import os

# Публичный ключ подписи релизов (32 байта: hex или base64). Вшивается в
# приложение; пусто = канал не настроен (обновления не применяются).
PUBKEY = ""

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = (-121665 * _inv(121666)) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _recover_x(y: int) -> int:
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _SQRT_M1) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = (4 * _inv(5)) % _P
_B = (_recover_x(_BY) % _P, _BY % _P)


def _add(p, q):
    x1, y1 = p
    x2, y2 = q
    t = _D * x1 * x2 * y1 * y2
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + t)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - t)
    return (x3 % _P, y3 % _P)


def _mul(p, e: int):
    if e == 0:
        return (0, 1)
    q = _mul(p, e // 2)
    q = _add(q, q)
    if e & 1:
        q = _add(q, p)
    return q


def _encode_point(p) -> bytes:
    x, y = p
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode_point(raw: bytes):
    if len(raw) != 32:
        raise ValueError("bad point size")
    y = int.from_bytes(raw, "little") & ((1 << 255) - 1)
    if y >= _P:
        raise ValueError("non-canonical point")
    x = _recover_x(y)
    if (x & 1) != (raw[31] >> 7):
        x = _P - x
    p = (x % _P, y)
    if (-p[0] * p[0] + p[1] * p[1] - 1 - _D * p[0] * p[0] * p[1] * p[1]) % _P:
        raise ValueError("point not on curve")
    return p


def _clamp_scalar(h32: bytes) -> int:
    a = int.from_bytes(h32, "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a


def _decode_hex_or_b64(text: str, size: int) -> bytes:
    """32/64-байтное значение: hex (64/128 символов) либо base64."""
    t = (text or "").strip()
    if len(t) == size * 2:
        try:
            return bytes.fromhex(t)
        except ValueError:
            pass
    try:
        raw = base64.b64decode(t, validate=True)
    except Exception:
        return b""
    return raw if len(raw) == size else b""


def public_key_from_secret(secret_hex: str) -> str:
    """Публичный ключ (hex) из 32-байтного приватного (hex)."""
    sk = bytes.fromhex(secret_hex)
    if len(sk) != 32:
        raise ValueError("secret key must be 32 bytes")
    a = _clamp_scalar(hashlib.sha512(sk).digest()[:32])
    return _encode_point(_mul(_B, a)).hex()


def sign(message: bytes, secret_hex: str) -> str:
    """Подпись (hex, 64 байта) для сообщения. Только офлайн-инструменты."""
    sk = bytes.fromhex(secret_hex)
    if len(sk) != 32:
        raise ValueError("secret key must be 32 bytes")
    h = hashlib.sha512(sk).digest()
    a = _clamp_scalar(h[:32])
    pk = _encode_point(_mul(_B, a))
    r = int.from_bytes(hashlib.sha512(h[32:] + message).digest(),
                       "little") % _L
    r_enc = _encode_point(_mul(_B, r))
    k = int.from_bytes(hashlib.sha512(r_enc + pk + message).digest(),
                       "little") % _L
    s = (r + k * a) % _L
    return (r_enc + s.to_bytes(32, "little")).hex()


def verify(message: bytes, signature: str, pubkey: str | None = None) -> bool:
    """Проверить подпись. Любая ошибка = False (fail-closed).

    pubkey=None — использовать вшитый PUBKEY (пустой: проверка не проходит).
    """
    key_hex = PUBKEY if pubkey is None else pubkey
    try:
        pk = _decode_hex_or_b64(key_hex, 32)
        sig = _decode_hex_or_b64(signature, 64)
        if not pk or not sig:
            return False
        a = _decode_point(pk)
        r_enc, s_enc = sig[:32], sig[32:]
        r_point = _decode_point(r_enc)
        s = int.from_bytes(s_enc, "little")
        if s >= _L:
            return False
        k = int.from_bytes(hashlib.sha512(r_enc + pk + message).digest(),
                           "little") % _L
        left = _mul(_B, s)
        right = _add(r_point, _mul(a, k))
        return _encode_point(left) == _encode_point(right)
    except Exception:
        return False


def pubkey_fingerprint(pubkey: str | None = None) -> str:
    """Короткий отпечаток ключа (12 hex) — для показа в интерфейсе."""
    raw = _decode_hex_or_b64(PUBKEY if pubkey is None else pubkey, 32)
    if not raw:
        return ""
    return hashlib.sha256(raw).hexdigest()[:12].upper()


def keygen() -> tuple[str, str]:
    """Офлайн-генерация пары ключей: (secret_hex, public_hex)."""
    sk = os.urandom(32)
    sk_hex = sk.hex()
    return sk_hex, public_key_from_secret(sk_hex)
