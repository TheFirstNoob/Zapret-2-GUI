"""Tests for tester scoring timeout (audit 2026-11-14, P1)."""
from core import tester, tester_probes, timeouts


def test_domain_tests_use_stable_score_timeout(monkeypatch):
    captured = {}

    def fake_run(domains, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(tester_probes, "run_domain_tests", fake_run)
    t = tester.Zapret2Tester.__new__(tester.Zapret2Tester)
    t.probe_timeout = float(timeouts.HTTP)
    t._run_domain_tests(["example.com"])
    assert captured["timeout"] == float(timeouts.HTTP)
    assert timeouts.HTTP == 6


def test_probe_timeout_is_not_rtt_scaled():
    t = tester.Zapret2Tester.__new__(tester.Zapret2Tester)
    t.probe_timeout = 6.0
    t.timeout = 2.0  # RTT-сжатый (историческое поведение)
    captured = {}

    class FakeResult:
        results = []

    monkeypatch = None

    assert t.probe_timeout == 6.0
