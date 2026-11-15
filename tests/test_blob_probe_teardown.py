"""F2 2026-11-15: перебор блобов обязан гасить winws2 между итерациями."""
from core import tester as tester_mod


def test_probe_blobs_kills_engine_between_iterations(tmp_path, monkeypatch):
    t = tester_mod.Zapret2Tester(tmp_path)
    calls = []
    monkeypatch.setattr(t, "_ensure_winws2_dead", lambda: calls.append("dead"))
    monkeypatch.setattr(t, "_run_profile", lambda *a, **k: True)
    monkeypatch.setattr(t, "_any_winws2_running", lambda: True)
    monkeypatch.setattr(t, "_run_domain_tests", lambda *a, **k: [])
    monkeypatch.setattr(tester_mod.time, "sleep", lambda *_: None)
    out = t.probe_blobs(lambda *_: None, ["a", "b"])
    assert len(out) == 2
    # initial + после каждой итерации (2) + final = не меньше 4
    assert calls.count("dead") >= 4
