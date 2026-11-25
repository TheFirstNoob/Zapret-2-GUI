"""QUIC-пробник: сэмплирование протоколов и адресов медиа."""
from core import youtube_probe as yp


def test_sample_session_missing_page(monkeypatch) -> None:
    class _WS:
        pass

    def fake_ws(port, wait_s=10.0):
        return "ws://x"

    monkeypatch.setattr(yp, "_devtools_ws", fake_ws)

    class _Cdp:
        def __init__(self, url):
            pass
        def send(self, *a, **k):
            return 1
        def wait(self, *a, **k):
            return {"targetInfos": []}
        def pump(self, *a, **k):
            return None
        def drain(self):
            return []
        def close(self):
            pass

    monkeypatch.setattr(yp, "CDP", _Cdp)
    out = yp.sample_session(1, seconds=3)
    assert "окно" in out["error"]
