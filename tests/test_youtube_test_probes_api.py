"""Тестовые API пробников YouTube: узлы кэшей и QUIC-сессия."""
import time

from server import api_youtube_nodes as nodes_api
from server import api_youtube_quic as quic_api


class _Ctx:
    pass


def test_nodes_scan_rejects_bad_target(monkeypatch) -> None:
    out = nodes_api.youtube_nodes_scan(_Ctx(), {"target": "https://youtube.com"})
    assert out["status"] == "error"


def test_nodes_scan_ok(monkeypatch) -> None:
    monkeypatch.setattr(nodes_api.youtube_nodes, "scan_pool",
                        lambda pool, **kw: {"pool": pool, "nodes": [], "alive": 0,
                                            "dead": 0, "mode": "all_dead",
                                            "note": "нет", "hosts_suggest": []})
    out = nodes_api.youtube_nodes_scan(_Ctx(), {"target": "rr2---sn-abc-x.googlevideo.com"})
    assert out["status"] == "ok"
    assert out["result"]["pool"] == "sn-abc-x"


def test_quic_start_rejects_bad_url(monkeypatch) -> None:
    out = quic_api.youtube_quic_start(_Ctx(), {"url": "nope"})
    assert out["status"] == "error"


def test_quic_start_and_close(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(quic_api, "get_root_dir", lambda: tmp_path)
    monkeypatch.setattr(quic_api.youtube_probe, "discover_media_hosts",
                        lambda vid, **kw: ["rr1---sn-abc-x.googlevideo.com"])
    monkeypatch.setattr(quic_api.youtube_probe, "open_quic_session",
                        lambda vid, prof, **kw: {"pid": 1, "port": 1,
                                                 "url": "u", "hosts": kw.get("hosts", []),
                                                 "profile": str(prof)})
    monkeypatch.setattr(quic_api.youtube_probe, "sample_session",
                        lambda port, seconds=12.0: {"protocols": {"h3": 3},
                                                    "remote_ips": ["1.2.3.4"],
                                                    "media_bytes": 1000, "error": ""})
    monkeypatch.setattr(quic_api.youtube_probe, "close_quic_session", lambda prof: None)
    out = quic_api.youtube_quic_start(_Ctx(), {"url": "https://youtu.be/-Td4It4H_Uc"})
    assert out["status"] == "ok"
    for _ in range(50):
        st = quic_api.youtube_quic_status(_Ctx())
        if st["state"] in ("done", "error"):
            break
        time.sleep(0.05)
    st = quic_api.youtube_quic_status(_Ctx())
    assert st["state"] == "done"
    assert st["result"]["hosts"]
    assert st["result"]["media_check"]["protocols"]["h3"] == 3
    assert st["result"]["h3_share"] == 1.0
    assert quic_api.youtube_quic_close(_Ctx())["status"] == "ok"
