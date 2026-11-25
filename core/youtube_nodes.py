"""Скан пула кэшей googlevideo (rr1..rr8---sn-POOL) без браузера.

Проверяет каждый узел пула: DNS (через DoH, мимо hosts), TCP 443 + TLS с
реальным SNI, HTTP/80. Нужен, чтобы понять, что именно сломано в сети:
отдельные узлы (тогда помогает hosts: мёртвое имя -> живой IP) или весь пул
(тогда hosts не поможет).

Модуль только читает и возвращает данные. hosts не меняет.
"""
from __future__ import annotations

import re
import socket
import ssl
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

DOH_URL = "https://dns.google/resolve?name={name}&type=A"
POOL_RE = re.compile(r"rr\d+---(sn-[a-z0-9]+(?:-[a-z0-9]+)*)\.googlevideo\.com", re.I)
HOST_RE = re.compile(r"rr(\d+)---(sn-[a-z0-9]+(?:-[a-z0-9]+)*)\.googlevideo\.com", re.I)

NODE_COUNT = 8
TCP_TIMEOUT = 3.0
HTTP_TIMEOUT = 3.0


BARE_POOL_RE = re.compile(r"^sn-[a-z0-9]+(?:-[a-z0-9]+)*$", re.I)


def parse_pool(text: str) -> Optional[str]:
    """Достать имя пула (sn-...) из hostname/URL или из готового имени пула."""
    if not text:
        return None
    s = text.strip().rstrip("/")
    if BARE_POOL_RE.match(s):
        return s.lower()
    m = POOL_RE.search(s)
    return m.group(1).lower() if m else None


def pool_hosts(pool: str, count: int = NODE_COUNT) -> list[str]:
    pool = pool if pool.startswith("sn-") else f"sn-{pool}"
    return [f"rr{i}---{pool}.googlevideo.com" for i in range(1, count + 1)]


def _resolve_doh(host: str, timeout: float = 4.0) -> list[str]:
    try:
        req = urllib.request.Request(DOH_URL.format(name=host), headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            import json
            data = json.loads(r.read().decode("utf-8", "replace"))
        return [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
    except Exception:
        return []


@dataclass
class NodeResult:
    index: int
    host: str
    ip: str = ""
    tcp_ok: bool = False
    tcp_ms: int = 0
    tls_ok: bool = False
    tls_ms: int = 0
    http80_ok: bool = False
    error: str = ""

    @property
    def alive(self) -> bool:
        return self.tls_ok

    def as_dict(self) -> dict:
        return {"index": self.index, "host": self.host, "ip": self.ip,
                "tcp": self.tcp_ok, "tls": self.tls_ok,
                "tcp_ms": self.tcp_ms, "tls_ms": self.tls_ms,
                "http80": self.http80_ok, "alive": self.alive,
                "error": self.error}


def _tcp_tls(host: str, ip: str) -> tuple[bool, int, bool, int, str]:
    tcp_ok = False
    tls_ok = False
    tcp_ms = tls_ms = 0
    err = ""
    s = None
    try:
        t0 = time.time()
        s = socket.create_connection((ip, 443), timeout=TCP_TIMEOUT)
        tcp_ok = True
        s.settimeout(TCP_TIMEOUT)
        tcp_ms = int((time.time() - t0) * 1000)
        t1 = time.time()
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(s, server_hostname=host):
            tls_ok = True
        tls_ms = int((time.time() - t1) * 1000)
    except Exception as e:  # noqa: BLE001
        err = type(e).__name__
    finally:
        try:
            if s is not None:
                s.close()
        except OSError:
            pass
    return tcp_ok, tcp_ms, tls_ok, tls_ms, err


def _http80(ip: str, host: str) -> bool:
    try:
        s = socket.create_connection((ip, 80), timeout=HTTP_TIMEOUT)
        s.settimeout(HTTP_TIMEOUT)
        s.sendall(f"HEAD / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
        data = s.recv(64)
        s.close()
        return data.startswith(b"HTTP/")
    except Exception:  # noqa: BLE001
        return False


def check_node(index: int, host: str, ip: str, check_http: bool = False) -> NodeResult:
    res = NodeResult(index=index, host=host, ip=ip)
    if not ip:
        res.error = "no-dns"
        return res
    res.tcp_ok, res.tcp_ms, res.tls_ok, res.tls_ms, res.error = _tcp_tls(host, ip)
    if check_http:
        res.http80_ok = _http80(ip, host)
    return res


def scan_pool(pool: str, *, check_http: bool = False,
              timeout: float = TCP_TIMEOUT) -> dict:
    """Проверить все узлы пула. Возвращает узлы + сводку + предложение hosts."""
    global TCP_TIMEOUT
    TCP_TIMEOUT = timeout
    hosts = pool_hosts(pool)
    resolved = {h: _resolve_doh(h) for h in hosts}
    nodes: list[NodeResult] = []
    with ThreadPoolExecutor(max_workers=len(hosts)) as ex:
        futs = [ex.submit(check_node, i + 1, h, (resolved.get(h) or [""])[0], check_http)
                for i, h in enumerate(hosts)]
        for f in futs:
            nodes.append(f.result())
    alive = [n for n in nodes if n.alive]
    dead = [n for n in nodes if not n.alive]
    if alive and dead:
        mode = "partial"
        note = "часть узлов жива: можно сопоставить мёртвые имена живым IP"
    elif alive:
        mode = "all_alive"
        note = "все узлы отвечают по TLS"
    elif any(n.tcp_ok for n in nodes):
        mode = "tls_blocked"
        note = "TCP есть, TLS не проходит на всех узлах: per-node hosts не поможет"
    else:
        mode = "all_dead"
        note = "весь пул недоступен по TCP: hosts-пиннинг не поможет, нужен другой маршрут"
    return {
        "pool": pool,
        "nodes": [n.as_dict() for n in nodes],
        "alive": len(alive),
        "dead": len(dead),
        "mode": mode,
        "note": note,
        "hosts_suggest": suggest_hosts(nodes) if mode == "partial" else [],
    }


def suggest_hosts(nodes: list[NodeResult]) -> list[str]:
    """Строки hosts: IP живого узла -> имя мёртвого (как советует сообщество)."""
    alive = [n for n in nodes if n.alive and n.ip]
    if not alive:
        return []
    lines = []
    for i, node in enumerate([n for n in nodes if not n.alive]):
        target = alive[i % len(alive)]
        lines.append(f"{target.ip}\t{node.host}")
    return lines
