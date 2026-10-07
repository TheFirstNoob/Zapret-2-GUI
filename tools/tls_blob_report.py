"""Разбор и сравнение TLS-фейков (blobs/tls_clienthello_*.bin).

Фейк для zapret - это чужой ClientHello, который отправляется вместо
настоящего. Значит важны ровно те же вещи, что и для JA3: версия, набор
шифров, расширения, кривые, форматы точек, ALPN, GREASE, padding. Поэтому
инструмент печатает именно этот отпечаток и сравнивает файлы между собой.

Запуск:
    python tools/tls_blob_report.py                  # таблица по всем фейкам
    python tools/tls_blob_report.py <путь-к-файлу>  # подробно по одному
    python tools/tls_blob_report.py --json           # для разбора глазами
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CIPHERS = {
    0x1301: "TLS_AES_128_GCM_SHA256", 0x1302: "TLS_AES_256_GCM_SHA384",
    0x1303: "TLS_CHACHA20_POLY1305_SHA256", 0x1304: "TLS_AES_128_CCM_SHA256",
    0x1305: "TLS_AES_128_CCM_8_SHA256",
    0xC02B: "ECDHE_ECDSA_AES_128_GCM_SHA256",
    0xC02F: "ECDHE_RSA_AES_128_GCM_SHA256",
    0xC02C: "ECDHE_ECDSA_AES_256_GCM_SHA384",
    0xC030: "ECDHE_RSA_AES_256_GCM_SHA384",
    0xCCA8: "ECDHE_ECDSA_CHACHA20_POLY1305",
    0xCCA9: "ECDHE_RSA_CHACHA20_POLY1305",
    0xC00A: "ECDHE_ECDSA_3DES_EDE_CBC_SHA",
    0xC009: "ECDHE_ECDSA_AES_128_CBC_SHA",
    0xC013: "ECDHE_RSA_AES_128_CBC_SHA",
    0xC014: "ECDHE_RSA_AES_256_CBC_SHA",
    0x002F: "RSA_AES_128_CBC_SHA", 0x0035: "RSA_AES_256_CBC_SHA",
    0x009C: "RSA_AES_128_GCM_SHA256", 0x009D: "RSA_AES_256_GCM_SHA384",
    0x009E: "DHE_RSA_AES_128_GCM_SHA256",
    0x009F: "DHE_RSA_AES_256_GCM_SHA384",
    0xC008: "ECDHE_ECDSA_3DES_EDE_CBC_SHA",
    0xFF01: "TLS_EMPTY_RENEGOTIATION_INFO_SCSV",
    0x5600: "TLS_FALLBACK_SCSV",
}

EXT = {
    0x0000: "server_name", 0x0001: "max_fragment_length",
    0x0005: "status_request", 0x000A: "supported_groups",
    0x000B: "ec_point_formats", 0x000D: "signature_algorithms",
    0x0010: "alpn", 0x0011: "status_request_v2",
    0x0012: "signed_certificate_timestamp", 0x0013: "client_certificate_type",
    0x0014: "server_certificate_type", 0x0015: "padding",
    0x0016: "encrypt_then_mac", 0x0017: "extended_master_secret",
    0x001B: "compress_certificate", 0x0023: "session_ticket",
    0x002B: "supported_versions", 0x002D: "psk_key_exchange_modes",
    0x0033: "key_share", 0xFE0D: "encrypted_client_hello",
    0x4469: "application_settings_old", 0x44CD: "alps",
}

GROUPS = {0x0017: "secp256r1", 0x0018: "secp384r1", 0x0019: "secp521r1",
          0x001D: "x25519", 0x001E: "x448", 0x0100: "ffdhe2048",
          0x0016: "secp256k1",
          # гибридные группы post-quantum (Chrome 124+): вот откуда +1.2 КБ
          0x11EC: "X25519MLKEM768", 0x11EB: "SecP256r1MLKEM768"}

SIGALGS = {0x0201: "rsa_pkcs1_sha1", 0x0401: "rsa_pkcs1_sha256",
           0x0501: "rsa_pkcs1_sha384", 0x0601: "rsa_pkcs1_sha512",
           0x0403: "ecdsa_secp256r1_sha256", 0x0503: "ecdsa_secp384r1_sha384",
           0x0603: "ecdsa_secp521r1_sha512", 0x0804: "rsa_pss_rsae_sha256",
           0x0805: "rsa_pss_rsae_sha384", 0x0806: "rsa_pss_rsae_sha512",
           0x0807: "ed25519", 0x0808: "ed448", 0x0809: "rsa_pss_pss_sha256"}


def is_grease(v: int) -> bool:
    return (v & 0x0F0F) == 0x0A0A and (v >> 8) == (v & 0xFF)


def parse(raw: bytes) -> dict:
    """ClientHello -> словарь с отпечатком. Бросает ValueError, если не он."""
    if len(raw) < 9 or raw[0] != 0x16 or raw[5] != 0x01:
        raise ValueError("не TLS ClientHello record")
    rec_ver = (raw[1], raw[2])
    if int.from_bytes(raw[3:5], "big") + 5 > len(raw):
        raise ValueError("оборванная record-обёртка")
    p = 9
    legacy = struct.unpack(">H", raw[p:p + 2])[0]
    p += 2 + 32
    sid_len = raw[p]
    sid = raw[p + 1:p + 1 + sid_len]
    p += 1 + sid_len
    cs_len = struct.unpack(">H", raw[p:p + 2])[0]
    ciphers = [struct.unpack(">H", raw[p + 2 + i:p + 4 + i])[0]
               for i in range(0, cs_len, 2)]
    p += 2 + cs_len
    comp_len = raw[p]
    p += 1 + comp_len
    ext_total = struct.unpack(">H", raw[p:p + 2])[0]
    p += 2
    end = p + ext_total
    exts: list[tuple[int, bytes]] = []
    while p + 4 <= end:
        et, el = struct.unpack(">HH", raw[p:p + 4])
        exts.append((et, raw[p + 4:p + 4 + el]))
        p += 4 + el

    def one(et: int) -> bytes:
        for t, b in exts:
            if t == et:
                return b
        return b""

    sni = None
    sni_pos = None
    for idx, (t, b) in enumerate(exts):
        if t == 0x0000 and len(b) > 5:
            sni_pos = idx
            sni = b[5:5 + struct.unpack(">H", b[3:5])[0]].decode("ascii", "replace")
            break
    alpn = []
    b = one(0x0010)
    if len(b) >= 2:
        q = 2
        while q < len(b):
            n = b[q]
            alpn.append(b[q + 1:q + 1 + n].decode("ascii", "replace"))
            q += 1 + n
    groups = []
    b = one(0x000A)
    if len(b) >= 2:
        groups = [struct.unpack(">H", b[2 + i:4 + i])[0]
                  for i in range(0, struct.unpack(">H", b[:2])[0], 2)]
    pf = list(one(0x000B)[1:1 + one(0x000B)[0]]) if one(0x000B) else []
    sigalgs = []
    b = one(0x000D)
    if len(b) >= 2:
        sigalgs = [struct.unpack(">H", b[2 + i:4 + i])[0]
                   for i in range(0, struct.unpack(">H", b[:2])[0], 2)]
    ks_groups, ks_len = [], 0
    b = one(0x0033)
    if len(b) >= 2:
        total = struct.unpack(">H", b[:2])[0]
        ks_len = total
        q = 2
        while q + 4 <= 2 + total:
            g, l = struct.unpack(">HH", b[q:q + 4])
            ks_groups.append(g)
            q += 4 + l
    hybrid = any(g in (0x11EC, 0x11EB) for g in ks_groups)
    vers = []
    b = one(0x002B)
    if len(b) >= 1:
        n = b[0]
        vers = [struct.unpack(">H", b[1 + i:3 + i])[0] for i in range(0, n, 2)]
    grease = [t for t, _ in exts if is_grease(t)]
    ja3 = ",".join([
        str(legacy),
        "-".join(str(c) for c in ciphers),
        "-".join(str(t) for t, _ in exts),
        "-".join(str(g) for g in groups),
        "-".join(str(x) for x in pf),
    ])
    return {
        "size": len(raw),
        "record_version": f"0x{rec_ver[0]:02x}{rec_ver[1]:02x}",
        "hello_version": f"0x{legacy:04x}",
        "supported_versions": [f"0x{v:04x}" for v in vers],
        "session_id_len": sid_len,
        "cipher_count": len(ciphers),
        "ciphers": [CIPHERS.get(c, "GREASE" if is_grease(c) else f"0x{c:04x}")
                    for c in ciphers],
        "cipher_grease": sum(1 for c in ciphers if is_grease(c)),
        "tls13_ciphers": sum(1 for c in ciphers if 0x1300 <= c <= 0x1305),
        "ext_count": len(exts),
        "ext_names": [EXT.get(t, "GREASE" if is_grease(t) else f"0x{t:04x}")
                      for t, _ in exts],
        "ext_grease": len(grease),
        "sni": sni,
        "sni_pos": sni_pos,
        "alpn": alpn,
        "groups": [GROUPS.get(g, f"0x{g:04x}") for g in groups],
        "point_formats": pf,
        "sigalg_count": len(sigalgs),
        "key_share_groups": [GROUPS.get(g, f"0x{g:04x}") for g in ks_groups],
        "key_share_bytes": ks_len,
        "hybrid_pq": hybrid,
        "padding_bytes": len(one(0x0015)),
        "psk_modes": list(one(0x002D)[1:1 + one(0x002D)[0]]) if one(0x002D) else [],
        "compress_cert": len(one(0x001B)) > 0,
        "alps": len(one(0x44CD)) > 0,
        "ja3": ja3,
        "ja3_md5": hashlib.md5(ja3.encode()).hexdigest(),
    }


# Отпечаток make_blob.py: минимальный синтетический набор. Совпадение по
# расширениям - надёжный признак «сгенерировано у нас».
SYNTHETIC_EXT = ["server_name", "extended_master_secret", "encrypt_then_mac",
                 "session_ticket", "supported_groups", "ec_point_formats",
                 "signature_algorithms", "supported_versions", "key_share"]


def classify(d: dict) -> str:
    if d["ext_names"] == SYNTHETIC_EXT:
        return "синтетика"
    return "захват"


def report(paths: list[Path]) -> list[dict]:
    rows = []
    for f in paths:
        raw = f.read_bytes()
        try:
            d = parse(raw)
        except ValueError as e:
            rows.append({"key": f.stem.replace("tls_clienthello_", ""),
                         "file": f.name, "error": str(e), "size": len(raw)})
            continue
        d["key"] = f.stem.replace("tls_clienthello_", "")
        d["file"] = f.name
        d["kind"] = classify(d)
        rows.append(d)
    return rows


def print_table(rows: list[dict]) -> None:
    hdr = (f"{'фейк':<24}{'Б':>5}{'rec':>7}{'ALPN':>5}{'GR':>4}{'pad':>5}"
           f"{'ext':>5}{'s13':>4}{'mlkem':>7}{'SNI':>26}{'вид':>11}{'ja3':>9}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if "error" in r:
            print(f"{r['key']:<24}{r['size']:>5}   ОШИБКА: {r['error']}")
            continue
        print(f"{r['key']:<24}{r['size']:>5}{r['record_version']:>7}"
              f"{len(r['alpn']):>5}{r['ext_grease'] + r['cipher_grease']:>4}"
              f"{r['padding_bytes']:>5}{r['ext_count']:>5}{r['tls13_ciphers']:>4}"
              f"{('да' if r.get('hybrid_pq') else '—'):>7}"
              f"{(r['sni'] or '—')[:25]:>26}{r['kind']:>11}{r['ja3_md5'][:8]:>9}")


def print_detail(r: dict) -> None:
    if "error" in r:
        print(f"{r['file']}: ОШИБКА {r['error']}")
        return
    print(f"── {r['file']}  ({r['size']} Б, {r['kind']})")
    print(f"   record версия {r['record_version']}, hello {r['hello_version']}, "
          f"supported_versions {', '.join(r['supported_versions']) or '—'}")
    print(f"   session_id: {r['session_id_len']} Б")
    print(f"   шифры ({r['cipher_count']}, из них TLS1.3: {r['tls13_ciphers']}, "
          f"GREASE: {r['cipher_grease']}): {', '.join(r['ciphers'])}")
    print(f"   расширения ({r['ext_count']}, GREASE: {r['ext_grease']}): "
          f"{', '.join(r['ext_names'])}")
    print(f"   SNI: {r['sni'] or '—'}"
          + (f"  (расширение #{r['sni_pos']}"
             + ("  ⚠ не первое - fast-path SNI-first у ТСПУ, см. "
                "EXTERNAL_NOTES §2 b4" if r["sni_pos"] else "  ✅ первое")
             + ")"))
    print(f"   ALPN: {', '.join(r['alpn']) or '—'}")
    print(f"   supported_groups: {', '.join(r['groups']) or '—'}; "
          f"point_formats: {r['point_formats']}")
    print(f"   signature_algorithms: {r['sigalg_count']} шт")
    print(f"   key_share: {', '.join(r['key_share_groups']) or '—'} "
          f"({r['key_share_bytes']} Б"
          f"{', гибридный post-quantum' if r.get('hybrid_pq') else ''})")
    print(f"   padding: {r['padding_bytes']} Б; psk_modes: {r['psk_modes']}; "
          f"compress_certificate: {r['compress_cert']}; ALPS: {r['alps']}")
    print(f"   JA3: {r['ja3_md5']}")
    print(f"        {r['ja3']}")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] != "--json":
        for a in args:
            d = parse(Path(a).read_bytes())
            d["kind"] = classify(d)
            print_detail(d | {"key": Path(a).stem, "file": Path(a).name})
        return
    blobs = sorted((ROOT / "blobs").glob("tls_clienthello_*.bin"))
    if not blobs:
        print("фейков нет")
        return
    rows = report(blobs)
    if "--json" in args:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print_table(rows)
    cap = [r for r in rows if r.get("kind") == "захват"]
    syn = [r for r in rows if r.get("kind") == "синтетика"]
    print(f"\nвсего {len(rows)}: захватов {len(cap)}, синтетики {len(syn)}")
    if cap:
        print(f"размеры захватов: "
              f"{', '.join(str(r['size']) for r in sorted(cap, key=lambda x: x['size']))}")
    if syn:
        print(f"размеры синтетики: "
              f"{', '.join(str(r['size']) for r in sorted(syn, key=lambda x: x['size']))}")
    uniq = {}
    for r in rows:
        uniq.setdefault(r.get("ja3_md5"), []).append(r["key"])
    groups = {k: v for k, v in uniq.items() if len(v) > 1}
    if groups:
        print("\nодинаковый отпечаток (JA3) у разных файлов:")
        for k, v in groups.items():
            print(f"   {k[:8]}: {', '.join(sorted(v))}")


if __name__ == "__main__":
    main()