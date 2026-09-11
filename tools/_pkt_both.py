"""_pkt_both.py — захват исходящих И входящих пакетов discord-сессии (pktmon).

Показывает: доходит ли ServerHello от discord (входящий TLS), сколько фейков
шлёт winws2, их SNI/TTL. Отличает «ТСПУ режет ClientHello» от «режет ответы».
"""
from __future__ import annotations

import argparse
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path

TCP_KIND_NAMES = {0: "EOL", 1: "NOP", 2: "MSS", 3: "WS", 4: "SACKOK",
                  5: "SACK", 8: "TS", 19: "MD5"}


def run(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="oem",
                       errors="replace", timeout=60,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    out = (r.stdout or "") + (r.stderr or "")
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed ({r.returncode}): {' '.join(cmd)}\n{out.strip()[:300]}")
    return out


def parse_pcapng(data):
    off = 0
    linktype = 1
    while off + 12 <= len(data):
        btype, blen = struct.unpack_from("<II", data, off)
        if btype == 1:
            lt = struct.unpack_from("<H", data, off + 8)[0]
            linktype = lt
        elif btype == 6:
            caplen = struct.unpack_from("<I", data, off + 20)[0]
            pkt = data[off + 28: off + 28 + caplen]
            if linktype is not None:
                yield linktype, pkt
        elif btype == 3:
            origlen = struct.unpack_from("<I", data, off + 8)[0]
            pkt = data[off + 12: off + 12 + origlen]
            if linktype is not None:
                yield linktype, pkt
        off += blen
        if off % 4:
            off += 4 - off % 4


def parse_packet(linktype, pkt):
    if linktype == 1:
        if len(pkt) < 14:
            return None
        eth = struct.unpack_from(">H", pkt, 12)[0]
        ip = pkt[14:]
        if eth == 0x8100:
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
    if proto != 6:
        return None
    tcp = ip[ihl:]
    sport, dport = struct.unpack_from(">HH", tcp, 0)
    seq = struct.unpack_from(">I", tcp, 4)[0]
    ack = struct.unpack_from(">I", tcp, 8)[0]
    off = (tcp[12] >> 4) * 4
    flags = tcp[13]
    payload = tcp[off:]
    options = []
    o = 20
    while o + 1 <= off:
        kind = tcp[o]
        if kind == 0:
            break
        if kind == 1:
            options.append((1, 1, b""))
            o += 1
            continue
        if o + 2 > off:
            break
        olen = tcp[o + 1]
        options.append((kind, olen, tcp[o + 2: o + olen]))
        o += max(olen, 2)
    return {"src": src, "dst": dst, "sport": sport, "dport": dport,
            "seq": seq, "ack": ack, "ttl": ttl, "flags": flags,
            "options": options, "payload": payload}


def sni_hint(payload):
    if len(payload) < 12 or payload[0] != 0x16:
        return ""
    cur, best = "", ""
    for b in payload[1:600]:
        c = chr(b)
        if c.isalnum() or c in ".-_":
            cur += c
        else:
            if "." in cur and len(cur) > 4 and not cur[0].isdigit() and len(cur) > len(best):
                best = cur
            cur = ""
    if "." in cur and len(cur) > 4 and not cur[0].isdigit() and len(cur) > len(best):
        best = cur
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://discord.com/")
    ap.add_argument("--label", default="disc")
    ap.add_argument("--wait", type=float, default=4.0)
    args = ap.parse_args()

    out_dir = Path(tempfile.gettempdir()) / "pkt_both"
    out_dir.mkdir(exist_ok=True)
    etl = out_dir / f"{args.label}.etl"
    pcap = out_dir / f"{args.label}.pcapng"

    run(["pktmon", "filter", "remove"], check=False)
    run(["pktmon", "filter", "add", "ipdisc", "-i", "162.159.0.0/16"])
    run(["pktmon", "start", "--capture", "--pkt-size", "0", "--file-name", str(etl)])

    print(f"== запрос: {args.url} ==")
    try:
        time.sleep(args.wait / 2)
        r = subprocess.run(
            ["curl.exe", "-s", "-o", "NUL", "-m", "10",
             "-H", "User-Agent: Mozilla/5.0", args.url],
            capture_output=True, text=True, encoding="oem", errors="replace",
            timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        print(f"   curl code: {r.stdout.strip() or '(пусто)'}")
        time.sleep(args.wait / 2)
    finally:
        run(["pktmon", "stop"])
        run(["pktmon", "etl2pcap", str(etl), "-o", str(pcap)])

    data = pcap.read_bytes()
    out = []   # (direction, seq, ack, ttl, flags, opts, head, sni)
    for lt, pkt in parse_pcapng(data):
        p = parse_packet(lt, pkt)
        if not p:
            continue
        if not (p["sport"] == 443 or p["dport"] == 443):
            continue
        if not (p["src"].startswith("162.159.") or p["dst"].startswith("162.159.")):
            continue
        # direction: our machine is source when dport=443 (outgoing)
        direction = "OUT" if p["dport"] == 443 else "IN"
        opts = ",".join(TCP_KIND_NAMES.get(k, f"k{k}") for k, _, _ in p["options"])
        head = p["payload"][:16].hex() if p["payload"] else ""
        sni = sni_hint(p["payload"])
        out.append((direction, p["seq"], p["ack"], p["ttl"], hex(p["flags"]), opts, head, sni))

    print(f"\n== пакетов discord-IP :443: {len(out)} ==")
    out_out = [x for x in out if x[0] == "OUT"]
    out_in = [x for x in out if x[0] == "IN"]
    print(f"   исходящих: {len(out_out)}, входящих (от сервера): {len(out_in)}")
    for x in out[:40]:
        print(f"   {x[0]:3} seq={x[1]:>10} ack={x[2]:>10} ttl={x[3]:>3} flags={x[4]:>5} "
              f"opts=[{x[5]:14}] {x[6]} {x[7]}")
    etl.unlink(missing_ok=True)
    pcap.unlink(missing_ok=True)


if __name__ == "__main__":
    main()