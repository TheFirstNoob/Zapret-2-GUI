"""pkt_verify.py — полигон проверки параметров десинка на уровне пакетов.

Что делает:
  1. Захватывает исходящий TCP-трафик на :443 через pktmon (встроенный в Windows)
  2. Делает тестовый TLS-запрос к заданному хосту (должен быть покрыт пресетом)
  3. Разбирает pcapng чистым python (без зависимостей)
  4. Печатает для каждого исходящего пакета: TTL, seq, TCP-опции, первые байты payload (SNI)

Зачем: 200/000 не отличает «параметр применился» от «перекрыт другим».
Сравнение «эталон (default) vs с параметром» показывает, какие поля пакета
реально изменились: опция tcp_md5 (kind 19), TTL (ip_autottl), SNI (rndsni), ts.

Использование (от админа, при работающей службе winws2 с нужным пресетом):
    python tools/pkt_verify.py --url https://www.youtube.com/ --label default
    python tools/pkt_verify.py --url https://www.youtube.com/ --label tcpmd5-fake
"""
from __future__ import annotations

import argparse
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path

TCP_KIND_NAMES = {
    0: "EOL", 1: "NOP", 2: "MSS", 3: "WS", 4: "SACKOK", 5: "SACK",
    8: "TS", 19: "MD5", 28: "UTO", 29: "TCP-AO", 34: "FASTOPEN",
}


def run(cmd: list[str], check: bool = True) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="oem",
                       errors="replace", timeout=60,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    out = (r.stdout or "") + (r.stderr or "")
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed ({r.returncode}): {' '.join(cmd)}\n{out.strip()[:300]}")
    return out


# ── pcapng parser ─────────────────────────────────────────────

def parse_pcapng(data: bytes):
    """Yield (linktype, packet_bytes) from a pcapng file (SHB/IDB/EPB/SPB)."""
    off = 0
    linktype = 1  # default Ethernet
    while off + 12 <= len(data):
        btype, blen = struct.unpack_from("<II", data, off)
        if btype == 0x0A0D0D0A:          # SHB
            if len(data) - off < blen:
                break
            linktype = None
            # find IDB later; store byte order
        elif btype == 1:                 # IDB
            if len(data) - off < blen:
                break
            lt = struct.unpack_from("<H", data, off + 8)[0]
            linktype = lt
        elif btype == 6:                 # EPB
            if len(data) - off < blen:
                break
            caplen = struct.unpack_from("<I", data, off + 20)[0]
            pkt = data[off + 28: off + 28 + caplen]
            if linktype is not None:
                yield linktype, pkt
        elif btype == 3:                 # SPB
            if len(data) - off < blen:
                break
            origlen = struct.unpack_from("<I", data, off + 8)[0]
            pkt = data[off + 12: off + 12 + origlen]
            if linktype is not None:
                yield linktype, pkt
        elif btype == 0:                 # OB
            pass
        else:
            # unknown block: try to skip by length
            if blen <= 0 or blen > len(data) - off:
                break
        off += blen
        if off % 4:
            off += 4 - off % 4


def parse_packet(linktype: int, pkt: bytes):
    """Extract IP/TCP fields. Returns dict or None."""
    if linktype == 1:                    # Ethernet
        if len(pkt) < 14:
            return None
        eth = struct.unpack_from(">H", pkt, 12)[0]
        ip = pkt[14:]
        if eth == 0x8100:                # VLAN
            ip = pkt[18:]
    else:
        ip = pkt
    if len(ip) < 20 or ip[0] >> 4 != 4:
        return None
    ihl = (ip[0] & 0x0F) * 4
    if len(ip) < ihl + 20:
        return None
    ttl = ip[8]
    proto = ip[9]
    src = socket.inet_ntoa(ip[12:16])
    dst = socket.inet_ntoa(ip[16:20])
    if proto != 6:                        # TCP only
        return None
    tcp = ip[ihl:]
    sport, dport = struct.unpack_from(">HH", tcp, 0)
    seq = struct.unpack_from(">I", tcp, 4)[0]
    off = (tcp[12] >> 4) * 4
    flags = tcp[13]
    payload = tcp[off:]
    options = []
    o = 20
    while o + 1 <= off:
        kind = tcp[o]
        if kind == 0:
            options.append((0, 0, b""))
            break
        if kind == 1:
            options.append((1, 1, b""))
            o += 1
            continue
        if o + 2 > off:
            break
        olen = tcp[o + 1]
        odata = tcp[o + 2: o + olen]
        options.append((kind, olen, odata))
        o += max(olen, 2)
    return {
        "src": src, "dst": dst, "sport": sport, "dport": dport,
        "seq": seq, "ttl": ttl, "flags": flags, "options": options,
        "payload": payload,
    }


def sni_hint(payload: bytes) -> str:
    """Try to find an SNI-ish hostname in the payload (TLS ClientHello)."""
    if len(payload) < 12 or payload[0] != 0x16:
        return ""
    cur = ""
    best = ""
    for b in payload[1:600]:
        c = chr(b)
        if c.isalnum() or c in ".-_":
            cur += c
        else:
            if "." in cur and len(cur) > 4 and not cur[0].isdigit():
                if len(cur) > len(best):
                    best = cur
            cur = ""
    if "." in cur and len(cur) > 4 and not cur[0].isdigit():
        if len(cur) > len(best):
            best = cur
    return best


def analyze(linktype: int, pkt: bytes, summary: dict, ports: set):
    p = parse_packet(linktype, pkt)
    if not p or p["dport"] not in ports:
        return
    summary["total"] += 1
    opts = {k for k, _, _ in p["options"]}
    has_md5 = 19 in opts
    has_ts = 8 in opts
    if has_md5:
        summary["md5"] += 1
    if has_ts:
        summary["ts"] += 1
    if p["flags"] & 0x02:      # SYN
        summary["syn"] += 1
    if p["payload"] and p["payload"][0] == 0x16:  # TLS handshake
        summary["tls"] += 1
    summary["ttls"].append(p["ttl"])
    if p["payload"]:
        summary["snls"].add(sni_hint(p["payload"]) or "(no-sni)")
        summary["pkts"].append({
            "seq": p["seq"], "ttl": p["ttl"], "flags": hex(p["flags"]),
            "opts": ",".join(TCP_KIND_NAMES.get(k, f"k{k}") for k, _, _ in p["options"]),
            "head": p["payload"][:24].hex(),
            "sni": sni_hint(p["payload"]) or "",
        })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://www.youtube.com/",
                    help="тестовый URL (хост должен покрываться пресетом)")
    ap.add_argument("--label", default="run", help="метка прогона (для имён файлов)")
    ap.add_argument("--ports", default="443", help="порты захвата, через запятую")
    ap.add_argument("--wait", type=float, default=3.0,
                    help="секунд захвата вокруг запроса")
    args = ap.parse_args()

    ports = [p.strip() for p in args.ports.split(",") if p.strip()]

    out_dir = Path(tempfile.gettempdir()) / "pkt_verify"
    out_dir.mkdir(exist_ok=True)
    etl = out_dir / f"{args.label}.etl"
    pcap = out_dir / f"{args.label}.pcapng"

    print("== 1. очистка фильтров и старт захвата ==")
    run(["pktmon", "filter", "remove"], check=False)
    for i, p in enumerate(ports):
        run(["pktmon", "filter", "add", f"port{p}", "-t", "TCP", "-p", p])
    run(["pktmon", "start", "--capture", "--pkt-size", "0",
         "--file-name", str(etl)])

    print(f"== 2. тестовый запрос: {args.url} ==")
    try:
        time.sleep(args.wait / 2)
        r = subprocess.run(
            ["curl.exe", "-s", "-o", "NUL", "-m", "10",
             "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)", args.url],
            capture_output=True, text=True, encoding="oem", errors="replace",
            timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        print(f"   curl: {r.stdout.strip()[:60] or '(пусто)'}")
        time.sleep(args.wait / 2)
    finally:
        print("== 3. стоп и конвертация ==")
        run(["pktmon", "stop"])
        run(["pktmon", "etl2pcap", str(etl), "-o", str(pcap)])

    print("== 4. разбор ==")
    data = pcap.read_bytes()
    summary = {"total": 0, "md5": 0, "ts": 0, "syn": 0, "tls": 0,
               "ttls": [], "snls": set(), "pkts": []}
    ports_set = {int(p) for p in ports}
    for lt, pkt in parse_pcapng(data):
        analyze(lt, pkt, summary, ports_set)

    print(f"   исходящих TCP-пакетов на :{','.join(ports)}: {summary['total']}")
    print(f"   с TCP-опцией MD5 (kind 19):   {summary['md5']}")
    print(f"   с TCP-опцией TS (kind 8):     {summary['ts']}")
    print(f"   SYN: {summary['syn']}  TLS-handshake пакетов: {summary['tls']}")
    if summary["ttls"]:
        ttl = sum(summary["ttls"]) // len(summary["ttls"])
        print(f"   средний TTL исходящих: {ttl}")
    for sni in sorted(summary["snls"])[:6]:
        print(f"   SNI: {sni}")
    for p in summary["pkts"][:14]:
        print(f"   seq={p['seq']:>10} ttl={p['ttl']:>3} flags={p['flags']:>5} "
              f"opts=[{p['opts']:16}] {p['head']} {p['sni']}")
    etl.unlink(missing_ok=True)
    pcap.unlink(missing_ok=True)


if __name__ == "__main__":
    main()