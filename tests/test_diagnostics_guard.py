"""T21 (аудит 2026-11-14): per-check guard диагностики.

Одно исключение в проверке не должно убивать весь отчёт. Тесты полностью
офлайн: все тяжёлые/сетевые/службовые чеки подменены фейками.
"""
from __future__ import annotations

from pathlib import Path

from core import diagnostics
from core.config import AppConfig

CFG = AppConfig()


def _ok(check_id: str, name: str) -> diagnostics.Check:
    return diagnostics.Check(check_id, name, "ok", "ok")


def _patch_all_checks(monkeypatch, overrides: dict | None = None) -> None:
    fakes = {
        "_check_path": lambda root: _ok("path", "Путь установки"),
        "_check_launch_spot": lambda root: _ok("launch_spot", "Расположение"),
        "_check_windivert_files": lambda root: _ok("windivert_files", "Файлы"),
        "_check_windivert_service": lambda root: _ok("windivert_service", "Драйвер"),
        "_check_preset": lambda root, cfg: _ok("preset", "Пресет"),
        "_check_debug_log": lambda root, enabled: _ok("debug_log", "Debug-лог"),
        "_check_lan_peers": lambda: _ok("lan_peers", "LAN"),
        "_check_dns_health": lambda: _ok("dns_health", "DNS"),
        "_check_dns_poison": lambda: _ok("dns_poison", "DNS подмена"),
        "_check_dns_spoof_servers": lambda: _ok("dns_spoof", "DNS серверы"),
        "_check_dns_spoof_system": lambda: _ok("dns_spoof_system", "Сист. DNS"),
        "_check_net": lambda: [_ok("net_www.google.com", "Интернет")],
        "_check_block_types": lambda net: [],
        "_check_env": lambda: _ok("env", "Окружение"),
        "_check_tcp_timestamps": lambda: _ok("tcp_ts", "TCP timestamps"),
        "_check_service": lambda: _ok("service", "Служба"),
    }
    fakes.update(overrides or {})
    for name, fn in fakes.items():
        monkeypatch.setattr(diagnostics, name, fn)
    monkeypatch.setattr(diagnostics, "is_admin", lambda: True)
    monkeypatch.setattr(diagnostics, "_pid_of", lambda image: 123)


def test_crashing_check_does_not_abort_report(tmp_path: Path,
                                              monkeypatch) -> None:
    def boom(root, cfg):
        raise OSError("file is locked by AV")

    _patch_all_checks(monkeypatch, {"_check_preset": boom})
    report = diagnostics.run_diagnostics(tmp_path, CFG)

    by_id = {c["id"]: c for c in report["checks"]}
    assert by_id["preset"]["status"] == "skip"
    assert "OSError" in by_id["preset"]["detail"]
    assert "file is locked by AV" in by_id["preset"]["detail"]
    # Отчёт не потерял остальные проверки.
    for check_id in ("version", "admin", "path", "net_www.google.com",
                     "dns_health", "service"):
        assert check_id in by_id
    # И остаётся пригодным для отправки в поддержку.
    text = diagnostics.format_report_text(report)
    assert "проверка не выполнена" in text
    assert report["summary"]["skip"] >= 1


def test_net_group_crash_keeps_report(tmp_path: Path, monkeypatch) -> None:
    def boom():
        raise RuntimeError("probe thread died")

    _patch_all_checks(monkeypatch, {"_check_net": boom})
    report = diagnostics.run_diagnostics(tmp_path, CFG)

    by_id = {c["id"]: c for c in report["checks"]}
    assert by_id["net"]["status"] == "skip"
    assert "probe thread died" in by_id["net"]["detail"]
    # Следующие секции (DNS) всё ещё выполняются.
    assert "dns_poison" in by_id


def test_service_crash_is_warn_not_abort(tmp_path: Path, monkeypatch) -> None:
    def boom():
        raise RuntimeError("SERVICE_QUERY_CONFIG failed")

    _patch_all_checks(monkeypatch, {"_check_service": boom})
    report = diagnostics.run_diagnostics(tmp_path, CFG)

    by_id = {c["id"]: c for c in report["checks"]}
    assert by_id["service"]["status"] == "warn"
    assert "SERVICE_QUERY_CONFIG" in by_id["service"]["detail"]


def test_progress_callback_failure_does_not_abort(tmp_path: Path,
                                                  monkeypatch) -> None:
    _patch_all_checks(monkeypatch)

    def bad_cb(name: str) -> None:
        raise RuntimeError("UI gone")

    report = diagnostics.run_diagnostics(tmp_path, CFG, progress_cb=bad_cb)
    assert report["checks"]
    assert report["summary"]["ok"] >= 1


def test_safe_check_unit() -> None:
    crashed = diagnostics._safe_check("x", "X", lambda: 1 / 0)
    assert crashed.status == "skip"
    assert "ZeroDivisionError" in crashed.detail

    wrong = diagnostics._safe_check("x", "X", lambda: "not a check")
    assert wrong.status == "skip"
    assert "TypeError" in wrong.detail

    ok = diagnostics._safe_check("x", "X", lambda: _ok("x", "X"))
    assert ok.status == "ok"


def test_safe_checks_group_unit() -> None:
    def boom():
        raise ValueError("group failed")

    checks = diagnostics._safe_checks(boom, "group", "Группа")
    assert len(checks) == 1
    assert checks[0].status == "skip"
    assert "group failed" in checks[0].detail


def test_pid_lookup_failure_does_not_abort(tmp_path: Path, monkeypatch) -> None:
    _patch_all_checks(monkeypatch)

    def bad_pid(image: str):
        raise RuntimeError("tasklist exploded")

    monkeypatch.setattr(diagnostics, "_pid_of", bad_pid)
    report = diagnostics.run_diagnostics(tmp_path, CFG)
    by_id = {c["id"]: c for c in report["checks"]}
    assert by_id["winws2"]["status"] == "fail"
    assert "dns_health" in by_id
