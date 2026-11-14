"""T20: отмена батареи - частичные результаты, cancelled-флаг, чистый state.

Сеть/движок не трогаются: тестер и пробные функции замоканы.
"""
from __future__ import annotations

import threading
import types

from core import tester, tester_probes
from core.tester_defs import ProfileTestResult
from core.tester_defs import TestResult as _TestResult
from server import tester_flow
from server.app_state import TesterState as _TesterState


# ── батарея ─────────────────────────────────────────────────────────

def test_domain_tests_cancel_keeps_partial(monkeypatch):
    ev = threading.Event()

    def fake_curl(domain, test_type, timeout, path="/", h3_state=None):
        if domain == "first.example":
            ev.set()   # отмена пришла во время первой пробы
        return _TestResult(domain, test_type, "OK", 200, 1.0)

    monkeypatch.setattr(tester_probes, "curl_test", fake_curl)
    res = tester_probes.run_domain_tests(
        ["first.example", "second.example", "third.example"],
        concurrency=1, stop_event=ev)
    assert [r.domain for r in res] == ["first.example"]


def test_domain_tests_without_cancel_returns_all(monkeypatch):
    monkeypatch.setattr(
        tester_probes, "curl_test",
        lambda d, t, timeout, path="/", h3_state=None: _TestResult(d, t, "OK", 200, 1.0))
    res = tester_probes.run_domain_tests(["a", "b", "c"], concurrency=2)
    assert sorted(r.domain for r in res) == ["a", "b", "c"]


def test_domain_tests_h3_budget_per_battery(monkeypatch):
    """H3-бюджет живёт одну батарею: следующий вызов снова пробует H3."""
    states = []
    real_state = tester_probes.H3ProbeState

    class Tracking(real_state):
        def __init__(self):
            super().__init__()
            states.append(self)

    monkeypatch.setattr(tester_probes, "H3ProbeState", Tracking)
    monkeypatch.setattr(
        tester_probes, "curl_test",
        lambda d, t, timeout, path="/", h3_state=None: _TestResult(d, t, "OK", 200, 1.0))
    tester_probes.run_domain_tests(["a"], concurrency=1)
    tester_probes.run_domain_tests(["a"], concurrency=1)
    assert len(states) == 2 and states[0] is not states[1]


# ── test_profile ────────────────────────────────────────────────────

def _cancelled_tester(tmp_path, battery_results, set_event):
    t = tester.Zapret2Tester(tmp_path)
    t.shutdown_event = threading.Event()
    t._foreign_engine_error = lambda: ""
    t._ensure_winws2_dead = lambda: None
    t._setup_profile = lambda *a, **k: ("default", 3, "203.0.113.1", 6.0)

    def fake_battery(*a, **k):
        if set_event:
            t.shutdown_event.set()
        return list(battery_results)

    t._run_domain_tests = fake_battery
    return t


def test_test_profile_cancel_preserves_partial(monkeypatch, tmp_path):
    battery = [_TestResult("discord.com", "https", "OK", 200, 5.0)]
    t = _cancelled_tester(tmp_path, battery, set_event=True)
    res = t.test_profile("default", lambda pct, msg: None)
    assert res.cancelled is True
    assert [r.domain for r in res.results] == ["discord.com"]
    assert res.net_ok_count == 1


def test_test_profile_cancel_before_any_result_is_cancelled(monkeypatch, tmp_path):
    t = _cancelled_tester(tmp_path, [], set_event=True)
    res = t.test_profile("default", lambda pct, msg: None)
    assert res.cancelled is True and res.results == []


def test_baseline_cancel_preserves_partial(monkeypatch, tmp_path):
    t = _cancelled_tester(
        tmp_path, [_TestResult("github.com", "https", "OK", 200, 5.0)],
        set_event=True)
    res = t._test_baseline("__naked__", lambda pct, msg: None)
    assert res.cancelled is True
    assert [r.domain for r in res.results] == ["github.com"]


# ── финальная сериализация/ранжирование (tester_flow) ───────────────

def _res(profile="default", cancelled=False, results=None):
    return ProfileTestResult(
        profile_name=profile, results=list(results or []),
        ok_count=0, fail_count=0, cancelled=cancelled)


def test_is_start_failure_distinguishes_cancel():
    assert tester_flow._is_start_failure(None) is True
    assert tester_flow._is_start_failure(_res()) is True
    # отменённый (даже пустой) - НЕ «не запустилась»
    assert tester_flow._is_start_failure(_res(cancelled=True)) is False
    ok = _res(results=[_TestResult("a.example", "https", "OK", 200, 1.0)])
    assert tester_flow._is_start_failure(ok) is False


def test_serialize_result_has_cancelled_and_h3_skipped():
    results = [
        _TestResult("a.example", "https", "OK", 200, 1.0),
        _TestResult("www.youtube.com", "https", "H3_NONE", 0, 2.0,
                   "H3 не проверялся (бюджет батареи)"),
    ]
    data = tester_flow.serialize_result(_res(cancelled=True, results=results))
    assert data["cancelled"] is True
    assert data["h3_skipped"] == 1
    assert data["profile"] == "default"
    # старые поля контракта на месте
    for key in ("ok_count", "network_rate", "results", "total_time_ms"):
        assert key in data


def _patch_sweep(monkeypatch):
    """Моки окружения _test_profiles_branch: без STATE/службы/движка."""
    monkeypatch.setattr(tester_flow, "ui_presets", lambda: ["default", "auto"])
    monkeypatch.setattr(
        tester_flow, "get_config_manager",
        lambda: types.SimpleNamespace(
            load=lambda: types.SimpleNamespace(ipset_catchall=False,
                                               last_profile="default")))
    monkeypatch.setattr(
        tester_flow, "get_controller",
        lambda: types.SimpleNamespace(
            status=lambda: types.SimpleNamespace(running=False)))
    monkeypatch.setattr(tester_flow, "scan_winws_exe",
                        lambda: {"running": False})
    monkeypatch.setattr(tester_flow, "svc_was_running", lambda: False)
    monkeypatch.setattr(tester_flow, "run_tester", lambda fn: fn())
    monkeypatch.setattr(tester_flow, "build_recommendation",
                        lambda results, naked, sanity: {"verdict": "partial",
                                                        "message": "x"})
    monkeypatch.setattr(tester_flow, "recheck_contested",
                        lambda tester, best, rec, progress: rec)
    monkeypatch.setattr(tester_flow, "restore_protection_after_naked",
                        lambda z2, z1, st, svc: "")
    monkeypatch.setattr(tester_flow.custom_build, "build_custom_strategy",
                        lambda root, results, tester: {"valid": False})


def test_sweep_cancel_keeps_partial_profile(monkeypatch):
    """Отменённый профиль свипа: не start_failure, не в рейтинге; частичный
    результат - отдельным полем финала."""
    state = _TesterState()
    shutdown = threading.Event()

    class FakeTester:
        def __init__(self):
            self.shutdown_event = shutdown

        def run_naked_baseline(self, progress, result_cb=None):
            return ProfileTestResult(profile_name="__naked__", net_ok_count=1,
                                     net_total=1, network_rate=100.0)

        def test_profile(self, profile, progress_cb, tier="critical",
                         result_cb=None, ipset_catchall=False, discord_alt=False):
            if profile == "default":
                return ProfileTestResult(
                    profile_name=profile,
                    results=[_TestResult("discord.com", "https", "OK", 200, 5.0)],
                    net_ok_count=1, net_total=1, network_rate=100.0)
            shutdown.set()   # отмена на втором профиле
            return ProfileTestResult(
                profile_name=profile, cancelled=True,
                results=[_TestResult("github.com", "https", "OK", 200, 5.0)])

        def collect_sanity_info(self, profile, blocked):
            return {"dry_run": {}, "list_coverage": []}

    _patch_sweep(monkeypatch)

    tester_flow._test_profiles_branch(state, FakeTester(), {
        "profiles": ["default", "auto"], "tier": "critical"})

    final = state.final_result
    assert final is not None
    assert final["cancelled"] is True
    assert final["partial_profile"]["profile"] == "auto"
    assert final["partial_profile"]["cancelled"] is True
    # отмена не выдаётся за «не запустилась» и не «частичный» как start_failure
    assert "start_failures" not in final
    assert final["recommendation"]["verdict"] == "partial"
    assert final["partial"] is True

def test_sweep_cancel_on_exception_is_not_start_failure(monkeypatch):
    """Исключение профиля уже после «Остановить» - отмена, не start_failure."""
    state = _TesterState()
    shutdown = threading.Event()

    class RaisingTester:
        def __init__(self):
            self.shutdown_event = shutdown

        def run_naked_baseline(self, progress, result_cb=None):
            return ProfileTestResult(profile_name="__naked__", network_rate=0.0)

        def test_profile(self, profile, progress_cb, **kwargs):
            shutdown.set()
            raise RuntimeError("boom after cancel")

    _patch_sweep(monkeypatch)

    tester_flow._test_profiles_branch(state, RaisingTester(), {
        "profiles": ["default"], "tier": "critical"})

    # Отменённый прогон: чистое завершение без финала-«не запустилось».
    assert state.final_result is None
    assert "default" in state.completed
    assert state.error is None
