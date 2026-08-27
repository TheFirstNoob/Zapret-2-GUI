from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .tester import Zapret2Tester, CDN_PROVIDERS


@dataclass
class AnalyzerEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


def run_full_analysis(
    tester: Zapret2Tester,
    profiles: list[str],
    lock: threading.Lock,
    on_event: Optional[Callable[[AnalyzerEvent], None]] = None,
) -> list[dict]:
    """Тестирует список профилей на smoke tier. Топ-3 валидирует на full tier.
    Без блоб-тестирования — только чистые профили."""

    total = len(profiles)

    def emit(ev: AnalyzerEvent) -> None:
        if on_event:
            on_event(ev)

    def progress(percent: float, msg: str, current: int = 0, profile: str = "") -> None:
        emit(AnalyzerEvent("progress", {
            "percent": min(percent, 99),
            "message": msg,
            "current": current + 1 if current else 1,
            "total": total,
            "profile": profile,
            "blob": "",
        }))

    def intermediate(entry: dict, idx: int) -> None:
        emit(AnalyzerEvent("intermediate", {**entry, "idx": idx}))

    def test_result_cb(profile_name: str):
        def _cb(r):
            is_cdn = r.domain in CDN_PROVIDERS
            emit(AnalyzerEvent("test_result", {
                "profile": profile_name,
                "domain": r.domain,
                "test_type": r.test_type,
                "status": r.status,
                "status_code": r.status_code,
                "time_ms": r.time_ms,
                "error": r.error,
                "cdn_provider": CDN_PROVIDERS.get(r.domain, "") if is_cdn else "",
            }))
        return _cb

    def run_one(profile_name: str, idx: int, tier: str, send_intermediate: bool = True,
                progress_base: float = 0, progress_range: float = 75) -> dict:
        label = profile_name
        progress(progress_base, f"[{idx+1}/{total}] {label} ({tier})...", idx, profile_name)

        def _cb(pct, msg):
            progress(progress_base + pct * progress_range / 100,
                     f"[{idx+1}/{total}] {label}: {msg}", idx, profile_name)

        rcb = test_result_cb(profile_name)
        with lock:
            result = tester.test_profile(
                profile_name, _cb, tier=tier,
                result_cb=rcb, skip_cdn=(tier != "full"),
            )
        entry = {
            "profile": profile_name,
            "blob": "",
            "ok_count": result.ok_count,
            "fail_count": result.fail_count,
            "success_rate": result.success_rate,
            "network_rate": result.network_rate,
            "net_ok_count": result.net_ok_count,
            "net_total": result.net_total,
            "provider_hop": result.provider_hop,
            "provider_ip": result.provider_ip or "",
            "results": [
                {"domain": r.domain, "test_type": r.test_type,
                 "status": r.status, "time_ms": r.time_ms, "error": r.error}
                for r in result.results
            ],
            "error": result.results[0].error if result.results and result.ok_count == 0 and "." not in (result.results[0].domain or "") else "",
        }
        if send_intermediate:
            intermediate(entry, idx)
        return entry

    # Phase 1: Screen all profiles on smoke tier
    all_screened: list[dict] = []
    for i, pname in enumerate(profiles):
        if tester.shutdown_event.is_set():
            break
        entry = run_one(pname, i, "smoke",
                        progress_base=i * 75 / total,
                        progress_range=75 / total)
        all_screened.append(entry)

    all_screened.sort(key=lambda x: x.get("success_rate", 0) or 0, reverse=True)
    top3 = all_screened[:3]

    # Phase 2: Validate top 3 on full tier
    validated: list[dict] = []
    total += min(3, len(top3))
    for vi, entry in enumerate(top3):
        if tester.shutdown_event.is_set():
            break
        v_entry = run_one(entry["profile"], total - len(top3) + vi, "full",
                          send_intermediate=False,
                          progress_base=75 + vi * 25 / max(len(top3), 1),
                          progress_range=25 / max(len(top3), 1))
        validated.append(v_entry)
        intermediate(v_entry, total - len(top3) + vi)

    return validated + all_screened[len(validated):]
