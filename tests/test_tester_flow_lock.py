"""P1 2026-11-15: early-return blob_probe при запущенном Zapret 1
должен освобождать operation-lock tester (иначе все API получают 409)."""
import threading

from server import tester_flow as tf


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.error = None
        self.running = True


def test_blob_probe_early_return_releases_tester_lock(monkeypatch):
    state = _State()
    monkeypatch.setattr(tf, "get_tester", lambda: object())
    monkeypatch.setattr(tf.STATE, "tester_state", state, raising=False)
    monkeypatch.setattr(tf, "scan_winws_exe", lambda: {"running": True})
    released = []
    monkeypatch.setattr(tf, "end_operation", lambda name: released.append(name))
    tf.run_blob_probe({})
    assert released == ["tester"]
    assert state.running is False
    assert "Zapret 1" in (state.error or "")
