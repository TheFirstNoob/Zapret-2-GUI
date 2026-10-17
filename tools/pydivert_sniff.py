r"""pydivert_sniff.py - dev-инструмент: пассивный сниффер трафика процесса.

НЕ входит в сборку GUI (tools/ в анти-листе). Назначение: узнать, КУДА и КАК
ходит игра/приложение - порты, удалённые IP:port, счётчики отправлено/принято,
и ГЛАВНОЕ - ДОМЕНЫ (из DNS-запросов, TLS SNI и DNS-кэша Windows).

Примеры:
  python tools\pydivert_sniff.py --proc Wardogs.exe --seconds 60
  python tools\pydivert_sniff.py --pid 1234 --seconds 30 --json out.json
  python tools\pydivert_sniff.py --all --seconds 15

Отличия от pktmon-захвата в приложении: pydivert работает в SNIFF-режиме
(пакеты НЕ изымаются из стека и не дропаются) и официально поддерживает
совместную работу с winws2 (multi-handle, kernel priority chaining).

Требования: Windows + admin (драйвер WinDivert), pip install pydivert.
Оговорки v1: SNI достаём только из TCP:443 (TLS ClientHello); SNI из QUIC
Initial без расшифровки не парсим; DNS ловим только открытый (53), DoH -
нет; пакеты атрибутируются процессу по его локальным портам.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

PS_BASE = ["powershell", "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-Command"]
NW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ps(script: str) -> str:
    r = subprocess.run(PS_BASE + [script], capture_output=True, text=True,
                       encoding="oem", errors="replace", timeout=25,
                       creationflags=NW)
    return (r.stdout or "").strip()


def _ps_json(script: str) -> list:
    out = _ps(script)
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else [data]


# ── цели: процесс → порты ──────────────────────────────────────────────────

def resolve_pids(args) -> list[int]:
    if args.pid:
        return [int(args.pid)]
    if args.proc:
        name = args.proc[:-4] if args.proc.lower().endswith(".exe") else args.proc
        items = _ps_json(
            f"Get-Process -Name '{name}' -ErrorAction SilentlyContinue | "
            "Select-Object Id | ConvertTo-Json -Compress")
        return [int(i["Id"]) for i in items if i.get("Id") is not None]
    return []


def local_ports(pids: list[int]) -> set[int]:
    ps = ",".join(str(p) for p in pids)
    script = (
        f"$pids = @({ps}); "
        "$u = Get-NetUDPEndpoint -ErrorAction SilentlyContinue | "
        "Where-Object { $pids -contains $_.OwningProcess } | "
        "Select-Object -ExpandProperty LocalPort; "
        "$t = Get-NetTCPConnection -ErrorAction SilentlyContinue | "
        "Where-Object { $pids -contains $_.OwningProcess } | "
        "Select-Object -ExpandProperty LocalPort; "
        "@($u + $t) | Sort-Object -Unique"
    )
    ports: set[int] = set()
    for line in _ps(script).splitlines():
        line = line.strip()
        if line.isdigit() and 0 < int(line) < 65536:
            ports.add(int(line))
    return ports


_IP4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def dns_cache_snapshot() -> dict[str, set[str]]:
    """{ip: {имена}} из Get-DnsClientCache (периодически: TTL короткие)."""
    items = _ps_json(
        "Get-DnsClientCache -ErrorAction SilentlyContinue | "
        "Select-Object Entry,Data | ConvertTo-Json -Compress")
    out: dict[str, set[str]] = {}
    for it in items:
        entry = str(it.get("Entry") or "").strip()
        data = str(it.get("Data") or "").strip()
        if not entry or not data:
            continue
        if _IP4_RE.match(data) or ":" in data:
            out.setdefault(data, set()).add(entry)
    return out


# ── парсеры доменов из пакетов ─────────────────────────────────────────────

def tls_sni(payload: bytes) -> str | None:
    """SNI из TLS ClientHello (TCP:443). None - не ClientHello/нет SNI."""
    if len(payload) < 6 or payload[0] != 0x16 or payload[1] != 0x03:
        return None
    rec_len = (payload[3] << 8) | payload[4]
    hs = payload[5:5 + rec_len]
    if len(hs) < 4 or hs[0] != 0x01:  # handshake type: ClientHello
        return None
    hl = (hs[1] << 16) | (hs[2] << 8) | hs[3]
    body = hs[4:4 + hl]
    pos = 2 + 32  # legacy_version + random
    if pos >= len(body):
        return None
    sid_len = body[pos]
    pos += 1 + sid_len
    if pos + 2 > len(body):
        return None
    cs_len = (body[pos] << 8) | body[pos + 1]
    pos += 2 + cs_len
    if pos >= len(body):
        return None
    comp_len = body[pos]
    pos += 1 + comp_len
    if pos + 2 > len(body):
        return None
    ext_len = (body[pos] << 8) | body[pos + 1]
    pos += 2
    end = min(pos + ext_len, len(body))
    while pos + 4 <= end:
        etype = (body[pos] << 8) | body[pos + 1]
        elen = (body[pos + 2] << 8) | body[pos + 3]
        pos += 4
        if etype == 0:  # server_name
            sn = body[pos:pos + elen]
            if len(sn) >= 2:
                sl = (sn[0] << 8) | sn[1]
                return sn[2:2 + sl].decode("ascii", errors="replace").strip(".")
            return None
        pos += elen
    return None


def _dns_read_name(pkt: bytes, pos: int, depth: int = 0) -> tuple[str | None, int]:
    labels: list[str] = []
    while True:
        if pos >= len(pkt):
            return None, pos
        ln = pkt[pos]
        if ln == 0:
            return (".".join(labels) or None), pos + 1
        if (ln & 0xC0) == 0xC0:
            if pos + 1 >= len(pkt):
                return None, pos
            ptr = ((ln & 0x3F) << 8) | pkt[pos + 1]
            if depth == 0:
                sub, _ = _dns_read_name(pkt, ptr, depth + 1)
                if sub:
                    labels.append(sub)
            return (".".join(labels) or None), pos + 2
        labels.append(pkt[pos + 1:pos + 1 + ln].decode("ascii", errors="replace"))
        pos += 1 + ln
        if len(labels) > 30:
            return None, pos


def dns_parse(payload: bytes) -> dict | None:
    """Разбор DNS-сообщения: {qr, qnames, answers:[(owner,type,value)]}."""
    if len(payload) < 12:
        return None
    qr = (payload[2] >> 7) & 1
    qd = (payload[4] << 8) | payload[5]
    an = (payload[6] << 8) | payload[7]
    pos = 12
    qnames: list[str] = []
    for _ in range(min(qd, 4)):
        name, pos = _dns_read_name(payload, pos)
        if name:
            qnames.append(name)
        pos += 4
    answers: list[tuple[str, str, str]] = []
    for _ in range(min(an, 40)):
        owner, pos = _dns_read_name(payload, pos)
        if pos + 10 > len(payload):
            break
        rtype = (payload[pos] << 8) | payload[pos + 1]
        rdlen = (payload[pos + 8] << 8) | payload[pos + 9]
        rd_off = pos + 10
        if rd_off + rdlen > len(payload):
            break
        if rtype == 1 and rdlen == 4:
            answers.append((owner or (qnames[0] if qnames else "?"), "A",
                            ".".join(str(b) for b in payload[rd_off:rd_off + 4])))
        elif rtype == 28 and rdlen == 16:
            try:
                answers.append((owner or (qnames[0] if qnames else "?"), "AAAA",
                                str(ipaddress.IPv6Address(
                                    payload[rd_off:rd_off + 16]))))
            except ValueError:
                pass
        elif rtype == 5:
            cname, _ = _dns_read_name(payload, rd_off)
            if cname:
                answers.append((owner or (qnames[0] if qnames else "?"),
                                "CNAME", cname))
        pos = rd_off + rdlen
    return {"qr": qr, "qnames": qnames, "answers": answers}


# ── сборка фильтра WinDivert ───────────────────────────────────────────────

def build_filter(ports: set[int], dns: bool) -> str:
    parts: list[str] = []
    if ports:
        caps = sorted(ports)[:150]
        clause = " or ".join(
            f"udp.SrcPort == {p} or udp.DstPort == {p} "
            f"or tcp.SrcPort == {p} or tcp.DstPort == {p}" for p in caps)
        parts.append(f"({clause})")
    else:
        parts.append("(tcp or udp)")
    if dns:
        parts.append("(udp.DstPort == 53 or udp.SrcPort == 53 "
                     "or tcp.DstPort == 53 or tcp.SrcPort == 53)")
    return "(" + " or ".join(parts) + ") and not loopback"


# ── захват ─────────────────────────────────────────────────────────────────

class Report:
    def __init__(self) -> None:
        self.flows: dict[tuple, dict] = {}      # (proto, ip, port) -> counters
        self.ip_names: dict[str, set[str]] = {}  # ip -> имена (dns/sni/cache)
        self.sni_names: set[str] = set()
        self.dns_queries: set[str] = set()
        self.dns_answers = 0
        self.packets = 0
        self.errors: list[str] = []

    def flow(self, proto: str, ip: str, port: int) -> dict:
        key = (proto, ip, port)
        f = self.flows.get(key)
        if f is None:
            f = {"proto": proto, "ip": ip, "port": port,
                 "out_pkts": 0, "in_pkts": 0, "out_bytes": 0, "in_bytes": 0,
                 "first": time.time(), "last": 0.0}
            self.flows[key] = f
        return f

    def add_name(self, ip: str, name: str, sni: bool = False) -> None:
        if not ip or not name:
            return
        names = self.ip_names.setdefault(ip, set())
        names.add(name)
        if sni:
            self.sni_names.add(name)

    def handle(self, pkt, direction_out: bool) -> None:
        self.packets += 1
        proto = "udp" if pkt.udp is not None else "tcp"
        if direction_out:
            rip, rport = pkt.dst_addr, pkt.dst_port
        else:
            rip, rport = pkt.src_addr, pkt.src_port
        f = self.flow(proto, rip, rport)
        n = len(pkt.payload or b"")
        if direction_out:
            f["out_pkts"] += 1
            f["out_bytes"] += n
        else:
            f["in_pkts"] += 1
            f["in_bytes"] += n
        f["last"] = time.time()

        payload = bytes(pkt.payload or b"")
        if proto == "udp" and (rport == 53 or pkt.src_port == 53):
            d = dns_parse(payload)
            if d:
                if d["qr"]:
                    for owner, rtype, value in d["answers"]:
                        if rtype in ("A", "AAAA"):
                            self.add_name(value, owner)
                            self.dns_answers += 1
                else:
                    self.dns_queries.update(d["qnames"])
        elif proto == "tcp" and direction_out and rport == 443 and payload:
            sni = tls_sni(payload)
            if sni:
                self.add_name(rip, sni, sni=True)

    def merge_cache(self) -> None:
        for ip, names in dns_cache_snapshot().items():
            for nm in names:
                self.add_name(ip, nm)

    def to_dict(self) -> dict:
        flows = sorted(self.flows.values(),
                       key=lambda f: (f["out_pkts"] + f["in_pkts"]), reverse=True)
        return {
            "packets": self.packets,
            "flows": flows,
            "ip_names": {ip: sorted(n) for ip, n in sorted(self.ip_names.items())},
            "sni_names": sorted(self.sni_names),
            "dns_queries": sorted(self.dns_queries),
            "dns_answers": self.dns_answers,
            "errors": self.errors,
        }


def run_capture(filter_str: str, seconds: int, rep: Report, quiet: bool) -> None:
    try:
        import pydivert
    except ImportError:
        print("pydivert не установлен: python -m pip install pydivert")
        sys.exit(2)
    stop = threading.Event()
    handle_box: dict = {}

    def worker() -> None:
        try:
            w = pydivert.WinDivert(filter_str, flags=pydivert.Flag.SNIFF)
            handle_box["w"] = w
            w.open()
            out_dir = pydivert.Direction.OUTBOUND
            while not stop.is_set():
                try:
                    pkt = w.recv()
                except Exception:
                    break
                if pkt is None:
                    break
                try:
                    rep.handle(pkt, pkt.direction == out_dir)
                except Exception as e:  # noqa: BLE001
                    if len(rep.errors) < 20:
                        rep.errors.append(f"handle: {e}")
        except Exception as e:  # noqa: BLE001
            rep.errors.append(str(e))
            handle_box["err"] = e
        finally:
            try:
                if "w" in handle_box:
                    handle_box["w"].close()
            except Exception:
                pass

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    t0 = time.time()
    last = 0.0
    try:
        while time.time() - t0 < seconds:
            time.sleep(0.5)
            if "err" in handle_box:
                break
            if not quiet and time.time() - last >= 5:
                last = time.time()
                print(f"  [{int(time.time() - t0)}s] пакетов {rep.packets}, "
                      f"потоков {len(rep.flows)}", flush=True)
    except KeyboardInterrupt:
        print("  (Ctrl+C - останавливаюсь)")
    finally:
        stop.set()
        try:
            if "w" in handle_box:
                handle_box["w"].close()
        except Exception:
            pass
        th.join(timeout=3)
        if "err" in handle_box:
            e = handle_box["err"]
            msg = str(e)
            print(f"ОШИБКА WinDivert: {msg}")
            if "version" in msg.lower():
                print("  похоже на конфликт ВЕРСИЙ драйвера WinDivert с движком "
                      "- сравните bin\\WinDivert*.sys с бандлом pydivert либо "
                      "тестируйте при остановленной службе")
            elif "5" in msg or "access" in msg.lower():
                print("  запустите от администратора")


def print_report(rep: Report, seconds: float) -> None:
    rep.merge_cache()
    d = rep.to_dict()
    print("\n" + "=" * 78)
    print(f"ИТОГ: {seconds:.0f}s, пакетов {d['packets']}, потоков {len(d['flows'])}")
    print("=" * 78)

    name_of = {ip: ",".join(n) for ip, n in d["ip_names"].items()}
    print("\n-- Потоки (OUT - отправлено, IN - принято) --")
    silent = 0
    for f in d["flows"][:40]:
        names = name_of.get(f["ip"], "")
        flag = ""
        if f["out_pkts"] > 0 and f["in_pkts"] == 0:
            flag = "  <<< НЕТ ВХОДЯЩИХ (возможен блок/чёрная дыра)"
            silent += 1
        print(f"  {f['proto']:<3} {f['ip']}:{f['port']:<6} "
              f"out={f['out_pkts']:<5} ({f['out_bytes']}B) "
              f"in={f['in_pkts']:<5} ({f['in_bytes']}B) {names}{flag}")
    if silent:
        print(f"  ... потоков без входящих: {silent}")

    if d["sni_names"]:
        print("\n-- Домены из TLS SNI (TCP:443) --")
        for n in d["sni_names"]:
            ips = [ip for ip, names in d["ip_names"].items() if n in names]
            print(f"  {n}  ->  {', '.join(ips)}")
    if d["dns_queries"]:
        print("\n-- DNS-запросы (qnames) --")
        for n in d["dns_queries"][:60]:
            print(f"  {n}")
    extra = [ip for ip in d["ip_names"] if ip not in
             {f["ip"] for f in d["flows"]}]
    if extra:
        print("\n-- Прочие имена из DNS-кэша --")
        for ip in extra[:20]:
            print(f"  {ip}  <-  {', '.join(d['ip_names'][ip])}")
    if d["errors"]:
        print("\n-- Ошибки --")
        for e in d["errors"][:10]:
            print(f"  {e}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Пассивный сниффер процесса (pydivert/WinDivert, SNIFF)")
    target = ap.add_mutually_exclusive_group()
    target.add_argument("--pid", type=int, help="PID процесса")
    target.add_argument("--proc", help="имя процесса (Wardogs.exe)")
    target.add_argument("--all", action="store_true",
                        help="весь трафик (без привязки к процессу)")
    ap.add_argument("--seconds", type=int, default=30, help="длительность (30)")
    ap.add_argument("--ports", help="доп. порты через запятую")
    ap.add_argument("--no-dns", action="store_true",
                    help="не добавлять DNS (53) в фильтр")
    ap.add_argument("--json", help="сохранить отчёт в JSON-файл")
    ap.add_argument("--quiet", action="store_true", help="без прогресса")
    args = ap.parse_args()

    ports: set[int] = set()
    if args.ports:
        ports.update(int(p) for p in args.ports.split(",") if p.strip().isdigit())
    if not args.all:
        pids = resolve_pids(args)
        if not pids:
            print("Процесс не найден (--proc имя или --pid). "
                  "Запустите без цели с --all.")
            return 1
        ports |= local_ports(pids)
        print(f"Цель: pid={pids}, локальных портов: {len(ports)}")

    filter_str = build_filter(ports, dns=not args.no_dns)
    print(f"WinDivert фильтр: {filter_str[:200]}"
          f"{'...' if len(filter_str) > 200 else ''}")

    rep = Report()
    t0 = time.time()
    run_capture(filter_str, args.seconds, rep, args.quiet)
    secs = time.time() - t0
    print_report(rep, secs)

    if args.json:
        path = Path(args.json)
        path.write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"\nJSON: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
