from __future__ import annotations

from pathlib import Path

import pytest

from core import dns_manager


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
