"""pkt_discord.py — захват диалога с discord IP:443 через pktmon (фильтр по IP).

Показывает, что реально уходит и приходит: SYN, ClientHello(SNI), фейки,
SYN-ACK, ServerHello. Сравнение «рабочий пресет vs нерабочий» отвечает на
вопрос «что ТСПУ именно режет».
"""
import argparse, socket, struct, subprocess, tempfile, time
from pathlib import Path

def run(cmd, check=False, timeout=60):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="oem",
                       errors="replace", timeout=timeout,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    return r

def parse_pcapng(data):
    off = 0
    linktype = 1
    while off + 12 <= len(data):
        btype, blen = struct.unpack_from("<II", data, off)
        if btype == 1:
            linktype = struct.unpack_from("<H", data, off + 8)[0]
        elif btype == 6:
            caplen = struct.unpack_from("<I", data, off + 20)[0]
            yield linktype, data[off + 28: off + 28 + caplen]
        elif btype == 3:
            origlen = struct.unpack_from("<I", data, off + 8)[0]
            yield linktype, data[off + 12: off + 12 + origlen]
        off += blen
        if off % 4:
            off += 4 - off % 4

def parse_packet(linktype, pkt):
    if linktype == 1:
        if len(pkt) < 14: return None
        eth = struct.unpack_from(">H", pkt, 12)[0]
        ip = pkt[14:]
        if eth == 0x8100: ip = pkt[18:]
    else:
        ip = pkt
    if len(ip) < 20 or ip[0] >> 4 != 4: return None
    ihl = (ip[0] & 0x0F) * 4
    if len(ip) < ihl + 20: return None
    ttl = ip[8]
    proto = ip[9]
    src = socket.inet_ntoa(ip[12:16])
    dst = socket.inet_ntoa(ip[16:20])
    if proto != 6: return None
    tcp = ip[ihl:]
    sport, dport = struct.unpack_from(">HH", tcp, 0)
    seq = struct.unpack_from(">I", tcp, 4)[0]
    off = (tcp[12] >> 4) * 4
    flags = tcp[13]
    payload = tcp[off:] if off <= len(tcp) else b""
    return {"src": src, "dst": dst, "sport": sport, "dport": dport,
            "seq": seq, "ttl": ttl, "flags": flags, "payload": payload}

def sni_hint(payload):
    if len(payload) < 12 or payload[0] != 0x16: return ""
    cur = best = ""
    for b in payload[1:600]:
        c = chr(b)
        if c.isalnum() or c in ".-_":
            cur += c
        else:
            if "." in cur and len(cur) > 4 and not cur[0].isdigit() and len(cur) > len(best):
                best = cur
            cur = ""
    return best

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="162.159.138.232", help="discord IP")
    ap.add_argument("--preset", default="default.txt")
    ap.add_argument("--wait", type=float, default=2.0)
    ap.add_argument("--label", default="run")
    ap.add_argument("--run-preset", action="store_true",
                    help="запускать winws2 с пресетом и останавливать после")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, '.')
    from core.launcher import build_args_from_preset
    root = Path('.')
    winws = None

    try:
        if args.run_preset:
            a = build_args_from_preset(root, root/'lua', root/'blobs', root/'presets'/args.preset)
            winws = subprocess.Popen([str(root/'bin'/'winws2.exe')] + a,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(5)

        out_dir = Path(tempfile.gettempdir()) / "pkt_discord"
        out_dir.mkdir(exist_ok=True)
        etl = out_dir / f"{args.label}.etl"
        pcap = out_dir / f"{args.label}.pcapng"

        run(["pktmon", "filter", "remove"], check=False)
        run(["pktmon", "filter", "add", "disc", "-t", "TCP", "-i", args.ip])
        run(["pktmon", "start", "--capture", "--pkt-size", "0", "--file-name", str(etl)])

        time.sleep(args.wait / 2)
        r = run(["curl.exe", "-4", "-s", "-o", "NUL", "-m", "8",
                 "-H", "User-Agent: Mozilla/5.0",
                 "--resolve", f"discord.com:443:{args.ip}",
                 "https://discord.com/"], timeout=20)
        print(f"   curl -> {r.stdout.strip() or '(нет кода)'}")
        time.sleep(args.wait / 2)
        run(["pktmon", "stop"])
        run(["pktmon", "etl2pcap", str(etl), "-o", str(pcap)])

        data = pcap.read_bytes()
        pkts = []
        for lt, p in parse_pcapng(data):
            pp = parse_packet(lt, p)
            if pp and (pp["src"] == args.ip or pp["dst"] == args.ip):
                pkts.append(pp)

        print(f"\n=== {args.preset} → {len(pkts)} пакетов к {args.ip} ===")
        out_count = sum(1 for p in pkts if p["dst"] == args.ip)
        in_count = len(pkts) - out_count
        print(f"исходящих: {out_count}, входящих: {in_count}")
        syn_synack = 0
        # summarize incoming: ServerHello? (0x16 0x03 0x03 len>0, flags PSH-ACK)
        in_tls = sum(1 for p in pkts if p["src"] == args.ip and p["payload"]
                     and p["payload"][0] == 0x16)
        in_rst = sum(1 for p in pkts if p["src"] == args.ip and p["flags"] & 0x04)
        in_synack = sum(1 for p in pkts if p["src"] == args.ip and p["flags"] & 0x12 == 0x12)
        out_tls = sum(1 for p in pkts if p["dst"] == args.ip and p["payload"]
                      and p["payload"][0] == 0x16)
        out_google = sum(1 for p in pkts if p["dst"] == args.ip and "google.com" in (p["payload"][:600].decode('latin1','replace') if p["payload"] else ""))
        print(f"  входящих TLS-пакетов (ServerHello+): {in_tls}, RST: {in_rst}, SYN-ACK: {in_synack}")
        print(f"  исходящих TLS (ClientHello+): {out_tls}, из них с SNI google.com: {out_google}")
        for p in pkts[:40]:
            f = p["flags"]
            tag = ""
            if f & 0x02 and not (f & 0x10): tag = "SYN"
            elif f & 0x12 == 0x12: tag = "SYN-ACK"
            elif f & 0x04: tag = "RST"
            elif f & 0x10 and not (f & 0x02): tag = "ACK"
            elif f & 0x18: tag = "PSH-ACK"
            dir = "OUT" if p["dst"] == args.ip else "IN "
            sni = sni_hint(p["payload"])
            head = p["payload"][:12].hex() if p["payload"] else ""
            print(f"  {dir} seq={p['seq']:>10} ttl={p['ttl']:>3} {tag:>7} "
                  f"len={len(p['payload']):>4} sni={sni or ''} {head}")
        etl.unlink(missing_ok=True)
        pcap.unlink(missing_ok=True)
    finally:
        if winws:
            winws.terminate()
            try: winws.wait(timeout=5)
            except Exception: winws.kill()
        run(["pktmon", "stop"], check=False)
        run(["pktmon", "filter", "remove"], check=False)

if __name__ == "__main__":
    main()