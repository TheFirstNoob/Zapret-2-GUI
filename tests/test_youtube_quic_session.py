"""QUIC-сессия и discovery: PUT /json/new и повтор поиска хостов."""
import urllib.request

from core import youtube_probe as yp


def test_discover_retries_once(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_run(*a, **kw):
        calls["n"] += 1
        return {"media_hosts": [] if calls["n"] == 1 else ["rr1---sn-x.googlevideo.com"]}

    monkeypatch.setattr(yp, "find_browser", lambda explicit="": "browser.exe")
    monkeypatch.setattr(yp, "_run_pass", fake_run)
    hosts = yp.discover_media_hosts("-Td4It4H_Uc")
    assert hosts == ["rr1---sn-x.googlevideo.com"]
    assert calls["n"] == 2


def test_open_quic_session_uses_put(monkeypatch, tmp_path) -> None:
    seen = {}

    class _Proc:
        pid = 42

    monkeypatch.setattr(yp, "find_browser", lambda explicit="": "browser.exe")
    monkeypatch.setattr(yp, "_launch", lambda b, p, h: (_Proc(), 8123))
    monkeypatch.setattr(yp, "_devtools_ws", lambda port, wait_s=30.0: "ws://x")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=10):
        seen["method"] = req.get_method()
        seen["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    res = yp.open_quic_session("-Td4It4H_Uc", tmp_path / "prof", hosts=["h"])
    assert seen["method"] == "PUT"
    assert "/json/new?" in seen["url"]
    assert res["port"] == 8123
