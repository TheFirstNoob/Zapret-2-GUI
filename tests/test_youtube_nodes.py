"""Скан пула googlevideo: разбор имён, сводка и подсказки hosts."""
from core import youtube_nodes as yn


def test_parse_pool() -> None:
    assert yn.parse_pool("rr3---sn-gvnuxaxjvh-axqd.googlevideo.com") == "sn-gvnuxaxjvh-axqd"
    assert yn.parse_pool("https://rr1---sn-aj5goc-5x.googlevideo.com/videoplayback?x=1") == "sn-aj5goc-5x"
    assert yn.parse_pool("sn-gvnuxaxjvh-axqd") == "sn-gvnuxaxjvh-axqd"
    assert yn.parse_pool("https://youtube.com/watch?v=x") is None


def test_pool_hosts() -> None:
    hosts = yn.pool_hosts("sn-abc")
    assert hosts[0] == "rr1---sn-abc.googlevideo.com"
    assert len(hosts) == 8


def test_suggest_hosts_only_dead_to_alive() -> None:
    nodes = [
        yn.NodeResult(1, "rr1", "1.1.1.1", tcp_ok=True, tls_ok=True),
        yn.NodeResult(2, "rr2", "1.1.1.2", tcp_ok=True, tls_ok=False),
        yn.NodeResult(3, "rr3", "1.1.1.3", tcp_ok=True, tls_ok=False),
    ]
    lines = yn.suggest_hosts(nodes)
    assert len(lines) == 2
    assert all(l.startswith("1.1.1.1") for l in lines)
    assert "rr2" in lines[0] and "rr3" in lines[1]


def test_scan_pool_modes(monkeypatch) -> None:
    monkeypatch.setattr(yn, "_resolve_doh", lambda host, timeout=4.0: ["10.0.0.1"])

    def fake_check(index, host, ip, check_http=False):
        n = yn.NodeResult(index, host, ip)
        n.tcp_ok = True
        n.tls_ok = index % 2 == 0
        return n

    monkeypatch.setattr(yn, "check_node", fake_check)
    out = yn.scan_pool("sn-test")
    assert out["mode"] == "partial"
    assert out["alive"] == 4 and out["dead"] == 4
    assert len(out["hosts_suggest"]) == 4


def test_scan_all_dead(monkeypatch) -> None:
    monkeypatch.setattr(yn, "_resolve_doh", lambda host, timeout=4.0: [])
    out = yn.scan_pool("sn-none")
    assert out["mode"] == "all_dead"
    assert out["hosts_suggest"] == []
