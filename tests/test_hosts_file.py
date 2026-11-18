"""hosts.txt: валидные IP/имена, без дублей; AI geo-unblock на месте."""
import ipaddress
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _entries():
    seen = {}
    for line in (ROOT / "hosts.txt").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        assert len(parts) >= 2, line
        ipaddress.ip_address(parts[0])
        for host in parts[1:]:
            assert re.fullmatch(r"[A-Za-z0-9_.-]+", host), host
            assert host not in seen, f"дубль {host}: {seen[host]} и {line}"
            seen[host] = line
    return seen


def test_hosts_file_is_valid_and_unique():
    entries = _entries()
    assert "chatgpt.com" in entries
    assert "claude.ai" in entries
    assert "gemini.google.com" in entries
    assert "grok.com" in entries


def test_hosts_ai_entries_use_expected_proxy_ips():
    entries = _entries()
    assert entries["chatgpt.com"].startswith("217.60.179.6")
    assert entries["api.anthropic.com"].startswith("217.60.179.6")
    assert entries["gemini.google.com"].startswith("48.102.233.174")
