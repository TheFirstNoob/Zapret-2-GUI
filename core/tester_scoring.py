"""tester_scoring.py - скор/сборка результатов прогонов тестера (аудит #5).

Вынесено из Zapret2Tester: net_stats (чистые счётчики) и build_result
(сборка ProfileTestResult; side-effect-хуки - колбэками).
"""
from __future__ import annotations

from core.status import FAIL_STATUSES
from core.tester_defs import (CONTROL_DOMAINS, QUIC_QUIRK_DOMAINS,
                              ProfileTestResult, TestResult, is_control)


def net_stats(results: list[TestResult]) -> tuple[int, int, int, float, int, int]:
    """Сетевые счётчики (curl/TLS) отдельно от пингов: (net_ok, net_fail,
    net_total, network_rate, ping_ok, ping_total). network_rate - скор
    стратегии: пинги меряют голую связность и завышают скор (все 8 пресетов
    «20/30 (67%)» при реальной связности 4/13)."""
    net = [r for r in results
           if r.test_type != "ping" and r.domain not in CONTROL_DOMAINS
           and r.domain not in QUIC_QUIRK_DOMAINS
           and not is_control(r.domain)]
    pings = [r for r in results if r.test_type == "ping"]
    net_ok = sum(1 for r in net if r.status == "OK")
    net_total = len(net)
    net_fail = net_total - net_ok
    ping_ok = sum(1 for r in pings if r.status == "OK")
    rate = (net_ok / net_total * 100) if net_total else 0.0
    return net_ok, net_fail, net_total, rate, ping_ok, len(pings)


def build_result(profile_name, all_results, provider_hop, provider_ip, tier,
                 _logged_progress, kill_fn, logger=None) -> ProfileTestResult:
    """Сборка ProfileTestResult: гасим winws2 (kill_fn), считаем счётчики,
    логируем в test_session (logger) и финальный прогресс."""
    _logged_progress(97, "Остановка...")
    kill_fn()
    ok_count = sum(1 for r in all_results if r.status == "OK")
    fail_count = sum(1 for r in all_results if r.status in FAIL_STATUSES)
    total_time = sum(r.time_ms for r in all_results)
    total = ok_count + fail_count
    success_rate = (ok_count / total * 100) if total else 0
    net_ok, net_fail, net_total, network_rate, ping_ok, ping_total = net_stats(all_results)
    if logger:
        logger.result(profile_name, ok_count, fail_count, success_rate, provider_hop, provider_ip or "")
    _logged_progress(
        100,
        f"Профиль завершён: сеть {net_ok}/{net_total} ({network_rate:.0f}%), "
        f"всего проверок {total}")
    return ProfileTestResult(
        profile_name=profile_name, results=all_results,
        ok_count=ok_count, fail_count=fail_count, total_time=total_time,
        success_rate=success_rate, tier=tier,
        net_ok_count=net_ok, net_fail_count=net_fail, net_total=net_total,
        network_rate=network_rate, ping_ok_count=ping_ok, ping_total=ping_total,
        provider_hop=provider_hop, provider_ip=provider_ip,
    )
