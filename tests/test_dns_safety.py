from __future__ import annotations

from pathlib import Path

import pytest

import json

from core import dns_manager
from core.config import AppConfig


def test_reset_without_backup_is_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(dns_manager, "current_status", lambda: {
        "ok": True, "adapter": "test", "interface_index": 1,
        "servers": ["1.1.1.1"], "dhcp": False,
    })
    assert dns_manager.has_backup(tmp_path) is False
    with pytest.raises(dns_manager.DnsError):
        dns_manager.reset(tmp_path)


def test_reset_rejects_backup_from_another_adapter(tmp_path: Path,
                                                    monkeypatch) -> None:
    dns_manager._write_backup(tmp_path, {
        "adapter": "old", "interface_index": 1, "dhcp": True, "servers": [],
    })
    monkeypatch.setattr(dns_manager, "current_status", lambda: {
        "ok": True, "adapter": "new", "interface_index": 2,
        "servers": ["1.1.1.1"], "dhcp": False,
    })
    with pytest.raises(dns_manager.DnsError):
        dns_manager.reset(tmp_path)


def test_dhcp_detection_uses_registry_static_dns() -> None:
    # Статический NameServer, а DhcpNameServer может быть заполнен DHCP.
    assert "$reg.NameServer" in dns_manager._PS_QUERY
    assert "$reg.DhcpNameServer" in dns_manager._PS_QUERY
    assert "DNSServerSearchOrder" in dns_manager._PS_QUERY  # только fallback


# ── T21 (аудит 2026-11-14): восстановление ВСЕХ DNS, быстрый запрос ────────

def _state(idx: int = 1, v4=None, v6=None, dhcp: bool = False) -> dict:
    return {"ok": True, "adapter": "test", "description": "test nic",
            "interface_index": idx,
            "v4": list(v4 or []), "v6": list(v6 or []),
            "servers": list(v4 or []) + list(v6 or []), "dhcp": dhcp}


def test_status_from_data_parses_families() -> None:
    status = dns_manager._status_from_data({
        "adapter": "Wi-Fi", "description": "Intel", "interface_index": "15",
        "v4": ["1.1.1.1", "8.8.8.8"], "v6": ["2001:db8::1"], "dhcp": False})
    assert status["ok"] is True
    assert status["v4"] == ["1.1.1.1", "8.8.8.8"]
    assert status["v6"] == ["2001:db8::1"]
    assert status["servers"] == ["1.1.1.1", "8.8.8.8", "2001:db8::1"]
    assert status["interface_index"] == 15
    assert status["dhcp"] is False


def test_status_from_data_survives_garbage() -> None:
    # Мусор из усечённого/чужого PowerShell-ответа не должен ронять API.
    status = dns_manager._status_from_data({
        "interface_index": "not-a-number", "v4": "1.1.1.1",
        "v6": None, "dhcp": "no"})
    assert status["ok"] is True
    assert status["interface_index"] == 0
    assert status["v4"] == [] and status["v6"] == []
    assert status["dhcp"] is True  # значения нет -> безопасный дефолт


def test_ps_json_ignores_warning_lines() -> None:
    out = ('WARNING: какое-то предупреждение\n'
           '{"ok": true, "v4": ["1.1.1.1"]}\n'
           'WARNING: предупреждение после JSON\n')
    assert dns_manager._parse_ps_json(out)["v4"] == ["1.1.1.1"]


def test_ps_json_without_object_raises() -> None:
    with pytest.raises(dns_manager.DnsError):
        dns_manager._parse_ps_json("не json вообще")


def test_current_status_falls_back_to_legacy_query(monkeypatch) -> None:
    calls: list[str] = []

    def fake_ps(script: str, timeout: float = 20.0, **kwargs) -> dict:
        calls.append(script)
        if script == dns_manager._PS_QUERY:
            raise dns_manager.DnsError("fast path unavailable")
        return {"ok": True, "adapter": "a", "interface_index": 3,
                "v4": ["9.9.9.9"], "v6": [], "dhcp": True}

    monkeypatch.setattr(dns_manager, "_ps_run", fake_ps)
    status = dns_manager.current_status()
    assert status["v4"] == ["9.9.9.9"]
    assert calls == [dns_manager._PS_QUERY, dns_manager._PS_QUERY_LEGACY]


def test_backup_v2_keeps_all_addresses(tmp_path: Path) -> None:
    dns_manager._write_backup(tmp_path, _state(
        idx=7, v4=["1.1.1.1", "8.8.8.8", "9.9.9.9"],
        v6=["2001:db8::1", "2001:db8::2"]))
    data = dns_manager._read_backup(tmp_path)
    assert data is not None
    assert data["version"] == 2
    assert data["v4"] == ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
    assert data["v6"] == ["2001:db8::1", "2001:db8::2"]
    # Общий список - для совместимости со старой версией (откат на 0.10).
    assert data["servers"] == ["1.1.1.1", "8.8.8.8", "9.9.9.9",
                               "2001:db8::1", "2001:db8::2"]


def test_reset_restores_all_servers_beyond_two(tmp_path: Path,
                                               monkeypatch) -> None:
    monkeypatch.setattr(dns_manager, "current_status",
                        lambda: _state(idx=7, v4=["1.1.1.1"]))
    dns_manager._write_backup(tmp_path, _state(
        idx=7, v4=["10.0.0.1", "10.0.0.2", "10.0.0.3"],
        v6=["2001:db8::1"]))
    scripts: list[str] = []

    def fake_ps(script: str, timeout: float = 20.0) -> dict:
        scripts.append(script)
        return {"ok": True}

    monkeypatch.setattr(dns_manager, "_ps_run", fake_ps)
    result = dns_manager.reset(tmp_path)
    assert result["ok"] is True
    assert len(scripts) == 2  # отдельный Set-вызов на семейство
    for addr in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        assert addr in scripts[0]
    assert "2001:db8::1" in scripts[1]
    assert dns_manager.has_backup(tmp_path) is False


def test_reset_restores_legacy_v1_backup_all_servers(tmp_path: Path,
                                                     monkeypatch) -> None:
    # Старый backup (общий servers без семейств) должен восстанавливаться
    # целиком - миграция формата без потери 3-го+ адреса.
    monkeypatch.setattr(dns_manager, "current_status",
                        lambda: _state(idx=7, v4=["1.1.1.1"]))
    path = tmp_path / "logs" / "dns_backup.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "adapter": "old", "interface_index": 7, "dhcp": False,
        "servers": ["10.0.0.1", "10.0.0.2", "10.0.0.3"]}), encoding="utf-8")
    scripts: list[str] = []
    monkeypatch.setattr(dns_manager, "_ps_run",
                        lambda script, timeout=20.0: scripts.append(script) or {"ok": True})
    dns_manager.reset(tmp_path)
    assert len(scripts) == 1
    for addr in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        assert addr in scripts[0]


def test_reset_dhcp_backup_uses_reset_script(tmp_path: Path,
                                             monkeypatch) -> None:
    monkeypatch.setattr(dns_manager, "current_status",
                        lambda: _state(idx=7, v4=["1.1.1.1"]))
    dns_manager._write_backup(tmp_path, _state(idx=7, dhcp=True))
    scripts: list[str] = []
    monkeypatch.setattr(dns_manager, "_ps_run",
                        lambda script, timeout=20.0: scripts.append(script) or {"ok": True})
    dns_manager.reset(tmp_path)
    assert len(scripts) == 1
    assert "ResetServerAddresses" in scripts[0]


def test_reset_corrupt_static_backup_keeps_backup(tmp_path: Path,
                                                  monkeypatch) -> None:
    # Пустой статический backup: не выдумываем адреса и НЕ удаляем backup.
    monkeypatch.setattr(dns_manager, "current_status",
                        lambda: _state(idx=7, v4=["1.1.1.1"]))
    dns_manager._write_backup(tmp_path, _state(idx=7, dhcp=False))
    monkeypatch.setattr(dns_manager, "_ps_run",
                        lambda script, timeout=20.0: {"ok": True})
    with pytest.raises(dns_manager.DnsError):
        dns_manager.reset(tmp_path)
    assert dns_manager.has_backup(tmp_path) is True


def test_apply_profile_keeps_other_family_dns(tmp_path: Path,
                                              monkeypatch) -> None:
    # P1-регресс: оставшийся IPv6 DNS не должен давать ложное
    # "Windows не применил DNS" и откат.
    cfg = AppConfig(dns_main_primary="8.8.8.8", dns_main_secondary="8.8.4.4")
    states = iter([
        _state(idx=7, v4=["9.9.9.9"], dhcp=True),
        _state(idx=7, v4=["8.8.8.8", "8.8.4.4"], v6=["fe80::1"], dhcp=False),
    ])
    monkeypatch.setattr(dns_manager, "current_status", lambda: next(states))
    applied: list[str] = []
    monkeypatch.setattr(dns_manager, "_ps_run",
                        lambda script, timeout=20.0: applied.append(script) or {"ok": True})
    result = dns_manager.apply_profile(tmp_path, cfg, "main")
    assert result["v4"] == ["8.8.8.8", "8.8.4.4"]
    assert len(applied) == 1  # откат не понадобился
    backup = dns_manager._read_backup(tmp_path)
    assert backup is not None and backup["v4"] == ["9.9.9.9"]


def test_apply_profile_rollback_restores_all_servers(tmp_path: Path,
                                                     monkeypatch) -> None:
    cfg = AppConfig(dns_main_primary="8.8.8.8", dns_main_secondary="8.8.4.4")
    states = iter([
        _state(idx=7, v4=["10.0.0.1", "10.0.0.2", "10.0.0.3"], dhcp=False),
        _state(idx=7, v4=["8.8.8.8"], dhcp=False),          # Windows "не применил"
        _state(idx=7, v4=["10.0.0.1", "10.0.0.2", "10.0.0.3"], dhcp=False),
    ])
    monkeypatch.setattr(dns_manager, "current_status", lambda: next(states))
    applied: list[str] = []
    monkeypatch.setattr(dns_manager, "_ps_run",
                        lambda script, timeout=20.0: applied.append(script) or {"ok": True})
    with pytest.raises(dns_manager.DnsError):
        dns_manager.apply_profile(tmp_path, cfg, "main")
    # applied[0] - попытка профиля, applied[1] - откат исходного состояния:
    # в откат обязаны попасть ВСЕ три исходных сервера.
    assert len(applied) == 2
    for addr in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        assert addr in applied[1]


def test_static_families_from_state_and_backup() -> None:
    # v2-состояние: флаги по семействам.
    assert dns_manager._static_families(
        {"static4": True, "static6": False}) == {"v4": True, "v6": False}
    # v2-backup: вложенный static.
    assert dns_manager._static_families(
        {"static": {"v4": False, "v6": True}}) == {"v4": False, "v6": True}
    # Старые данные без флагов - не теряем адреса (считаем статикой).
    assert dns_manager._static_families({"servers": ["1.1.1.1"]}) == {
        "v4": True, "v6": True}


def test_status_from_data_maps_static_flags() -> None:
    status = dns_manager._status_from_data({
        "interface_index": 15, "v4": ["1.1.1.1"], "v6": ["2001:db8::1"],
        "dhcp": False, "static4": True, "static6": False})
    assert status["static4"] is True
    assert status["static6"] is False
    # Fallback-ответ старого запроса: static_dns -> static4.
    legacy = dns_manager._status_from_data({
        "interface_index": 15, "v4": ["1.1.1.1"], "v6": [],
        "dhcp": False, "static_dns": "1.1.1.1"})
    assert legacy["static4"] is True
    assert legacy["static6"] is False


def test_backup_keeps_static_flags(tmp_path: Path) -> None:
    dns_manager._write_backup(tmp_path, {
        "adapter": "test", "interface_index": 7, "dhcp": False,
        "v4": ["10.0.0.1"], "v6": ["2001:db8::1"],
        "static4": True, "static6": False})
    data = dns_manager._read_backup(tmp_path)
    assert data is not None
    assert data["static"] == {"v4": True, "v6": False}


def test_reset_skips_dhcp_family(tmp_path: Path, monkeypatch) -> None:
    # Статический IPv4 + IPv6, полученный по DHCP: reset возвращает только
    # статическое семейство, DHCP-адреса не закрепляет статикой.
    monkeypatch.setattr(dns_manager, "current_status",
                        lambda: _state(idx=7, v4=["1.1.1.1"]))
    dns_manager._write_backup(tmp_path, {
        "adapter": "test", "interface_index": 7, "dhcp": False,
        "v4": ["10.0.0.1", "10.0.0.2"], "v6": ["2001:db8::1"],
        "static4": True, "static6": False})
    scripts: list[str] = []
    monkeypatch.setattr(dns_manager, "_ps_run",
                        lambda script, timeout=20.0: scripts.append(script) or {"ok": True})
    dns_manager.reset(tmp_path)
    assert len(scripts) == 1  # только IPv4
    assert "10.0.0.1" in scripts[0] and "10.0.0.2" in scripts[0]
    assert "2001:db8::1" not in scripts[0]


def test_reset_restores_static_v6_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(dns_manager, "current_status",
                        lambda: _state(idx=7, v4=["1.1.1.1"]))
    dns_manager._write_backup(tmp_path, {
        "adapter": "test", "interface_index": 7, "dhcp": False,
        "v4": [], "v6": ["2001:db8::1", "2001:db8::2"],
        "static4": False, "static6": True})
    scripts: list[str] = []
    monkeypatch.setattr(dns_manager, "_ps_run",
                        lambda script, timeout=20.0: scripts.append(script) or {"ok": True})
    dns_manager.reset(tmp_path)
    assert len(scripts) == 1
    assert "2001:db8::1" in scripts[0] and "2001:db8::2" in scripts[0]


def test_current_status_no_adapter_does_not_fallback(monkeypatch) -> None:
    # "Нет активного сетевого адаптера" - штатный ответ, а не повод звать
    # медленный legacy-запрос (машина без сети не должна ждать дважды).
    calls: list[str] = []

    def fake_ps(script: str, timeout: float = 20.0, **kwargs) -> dict:
        calls.append(script)
        return {"ok": False, "error": "Нет активного сетевого адаптера"}

    monkeypatch.setattr(dns_manager, "_ps_run", fake_ps)
    with pytest.raises(dns_manager.DnsError) as exc_info:
        dns_manager.current_status()
    assert "Нет активного сетевого адаптера" in str(exc_info.value)
    assert calls == [dns_manager._PS_QUERY]


def test_backup_unknown_families_restores_saved_addresses(tmp_path: Path,
                                                          monkeypatch) -> None:
    # Реестр недоступен: dhcp=False, но флаги семейств не получены. Бэкап
    # должен остаться восстановимым (поведение прежней версии).
    dns_manager._write_backup(tmp_path, {
        "adapter": "test", "interface_index": 7, "dhcp": False,
        "v4": ["10.0.0.1", "10.0.0.2"], "v6": [],
        "static4": False, "static6": False})
    backup = dns_manager._read_backup(tmp_path)
    assert backup is not None
    assert backup["static"] == {"v4": True, "v6": True}
    monkeypatch.setattr(dns_manager, "current_status",
                        lambda: _state(idx=7, v4=["1.1.1.1"]))
    scripts: list[str] = []
    monkeypatch.setattr(dns_manager, "_ps_run",
                        lambda script, timeout=20.0, **kw: scripts.append(script) or {"ok": True})
    dns_manager.reset(tmp_path)
    assert len(scripts) == 1
    assert "10.0.0.1" in scripts[0] and "10.0.0.2" in scripts[0]


def test_backup_in_path_with_spaces_and_cyrillic(tmp_path: Path) -> None:
    root = tmp_path / "Zapret 2 копия" / "программы"
    root.mkdir(parents=True)
    dns_manager._write_backup(root, _state(
        idx=7, v4=["1.1.1.1", "8.8.8.8", "9.9.9.9"]))
    backup = dns_manager._read_backup(root)
    assert backup is not None
    assert backup["v4"] == ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
    assert dns_manager.has_backup(root) is True
