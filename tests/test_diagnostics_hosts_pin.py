"""DNS-подмена не должна ругаться на managed hosts-пин Discord."""
from core import diagnostics


def test_hosts_pin_for_reads_active_entry(tmp_path, monkeypatch):
    hosts = tmp_path / "hosts"
    hosts.write_text(
        "# comment\n23.227.38.74 discord.com\n127.0.0.1 localhost\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(diagnostics, "_HOSTS_PATH", hosts)
    assert diagnostics._hosts_pin_for("discord.com") == "23.227.38.74"
    assert diagnostics._hosts_pin_for("DISCORD.COM.") == "23.227.38.74"
    assert diagnostics._hosts_pin_for("example.com") is None


def test_commented_hosts_entry_is_not_a_pin(tmp_path, monkeypatch):
    hosts = tmp_path / "hosts"
    hosts.write_text("# 23.227.38.74 discord.com\n", encoding="utf-8")
    monkeypatch.setattr(diagnostics, "_HOSTS_PATH", hosts)
    assert diagnostics._hosts_pin_for("discord.com") is None
