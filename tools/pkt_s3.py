"""pkt_s3.py — захват TLS-диалога к произвольному IP (для amazonaws-полигона).

Считает: SYN, исходящие TLS (реальный hello vs google-фейки по SNI),
входящие (handshake/appdata), RST. Отличает: (а) фейки не уходят,
(б) доля фейков мала, (в) фейки уходят, но ТСПУ всё равно дропает.
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pkt_both import parse_pcapng, parse_packet, sni_hint, run  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="s3.amazonaws.com")
    ap.add_argument("--ip", default="")
    ap.add_argument("--path", default="/")
    ap.add_argument("--wait", type=float, default=5.0)
    args = ap.parse_args()

    ip = args.ip or socket.gethostbyname(args.host)
    print(f"target: {args.host} -> {ip}")

    out_dir = Path(tempfile.gettempdir()) / "pkt_s3"
    out_dir.mkdir(exist_ok=True)
    etl = out_dir / "s3.etl"
    pcap = out_dir / "s3.pcapng"

    run(["pktmon", "filter", "remove"], check=False)
    run(["pktmon", "filter", "add", "tgt", "-i", ip])
    run(["pktmon", "start", "--capture", "--pkt-size", "0", "--file-name", str(etl)])
    try:
        time.sleep(args.wait / 2)
        r = subprocess.run(
            ["curl.exe", "-4", "-s", "-o", "NUL", "-m", "12",
             "-w", "%{http_code}",
             "--resolve", f"{args.host}:443:{ip}",
             f"https://{args.host}{args.path}"],
            capture_output=True, text=True, encoding="oem", errors="replace",
            timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        print(f"curl code: {r.stdout.strip() or '(none)'}")
        time.sleep(args.wait / 2)
    finally:
        run(["pktmon", "stop"])
        run(["pktmon", "etl2pcap", str(etl), "-o", str(pcap)])

    rows = []
    for lt, pkt in parse_pcapng(pcap.read_bytes()):
        p = parse_packet(lt, pkt)
        if not p:
            continue
        rows.append(p)

    syn = [p for p in rows if p["flags"] == 0x02 and p["dport"] == 443]
    synack = [p for p in rows if p["flags"] == 0x12 and p["sport"] == 443]
    rst = [p for p in rows if p["flags"] in (0x04, 0x14)]
    out_tls = [p for p in rows if p["dport"] == 443 and p["payload"][:1] == b"\x16"]
    in_tls = [p for p in rows if p["sport"] == 443 and p["payload"][:1] in (b"\x16", b"\x17")]
    in_rst = [p for p in rows if p["sport"] == 443 and p["flags"] in (0x04, 0x14)]

    fakes = [p for p in out_tls if "google" in sni_hint(p["payload"]).lower()]
    real = [p for p in out_tls if args.host.split(".")[0] in sni_hint(p["payload"]).lower()
            or "s3" in sni_hint(p["payload"]).lower()]

    print(f"\nSYN: {len(syn)}, SYN-ACK: {len(synack)}, RST: {len(rst)} (in-rst: {len(in_rst)})")
    print(f"OUT TLS-пакеты: {len(out_tls)} (фейки google-SNI: {len(fakes)}, реальный s3-SNI: {len(real)})")
    in_hand = [p for p in rows if p["sport"] == 443 and p["payload"][:1] == b"\x16"]
    in_app = [p for p in rows if p["sport"] == 443 and p["payload"][:1] == b"\x17"]
    print(f"IN: handshake(0x16)={len(in_hand)}, appdata(0x17)={len(in_app)}")
    print(f"\n-- исходящие TLS (SNI / ttl / len): --")
    for p in out_tls[:20]:
        print(f"   OUT ttl={p['ttl']:>3} len={len(p['payload']):>5} sni={sni_hint(p['payload'])[:40]}")
    print(f"\n-- входящие (первые 10): --")
    for p in ([p for p in rows if p["sport"] == 443])[:10]:
        print(f"   IN  ttl={p['ttl']:>3} len={len(p['payload']):>5} head={p['payload'][:8].hex()}")
    etl.unlink(missing_ok=True)
    pcap.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
