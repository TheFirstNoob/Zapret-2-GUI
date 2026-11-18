"""Hosts-manager Discord/Cloudflare fix: без реальных hosts/NRPT/DNS."""
from pathlib import Path

from core import discord_fix


def _setup(tmp_path, monkeypatch):
    hosts = tmp_path / "hosts"
    hosts.write_text(
        "# user comment\n127.0.0.1 localhost\n"
        "162.159.128.233 discord.com\n"
        "127.0.0.1 example.com\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(discord_fix, "HOSTS_PATH", hosts)
    monkeypatch.setattr(discord_fix, "_probe", lambda ip, timeout=2.0: True)
    monkeypatch.setattr(discord_fix, "_start_server", lambda ip: None)
    monkeypatch.setattr(discord_fix, "_stop_server", lambda: None)
    monkeypatch.setattr(discord_fix, "_nrpt_add", lambda: None)
    monkeypatch.setattr(discord_fix, "_nrpt_remove", lambda: None)
    monkeypatch.setattr(discord_fix, "_nrpt_count", lambda: 1)
    monkeypatch.setattr(discord_fix, "_flush_dns", lambda: None)
    monkeypatch.setattr(discord_fix, "is_admin", lambda: True)
    monkeypatch.setattr(discord_fix, "_task_module", lambda: None)
    return hosts


def test_scan_finds_stale_hosts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    out = discord_fix.scan_hosts(tmp_path)
    assert out["count"] >= 1
    assert any(e["host"] == "discord.com" for e in out["entries"])


def test_enable_writes_managed_block_and_is_reversible(tmp_path, monkeypatch):
    hosts = _setup(tmp_path, monkeypatch)
    out = discord_fix.enable(tmp_path, ip="23.227.38.5")
    assert out["enabled"] is True
    txt = hosts.read_text(encoding="utf-8")
    assert discord_fix.BLOCK_BEGIN in txt
    assert "23.227.38.5 discord.com" in txt
    assert "162.159.128.233 discord.com" not in txt
    assert "127.0.0.1 example.com" in txt
    assert (tmp_path / "logs" / "discord_fix_state.json").is_file()
    assert (tmp_path / "logs" / "discord_fix_hosts_backup.txt").is_file()

    off = discord_fix.disable(tmp_path)
    assert off["enabled"] is False
    txt = hosts.read_text(encoding="utf-8")
    assert discord_fix.BLOCK_BEGIN not in txt
    assert "127.0.0.1 example.com" in txt


def test_enable_requires_admin(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(discord_fix, "is_admin", lambda: False)
    try:
        discord_fix.enable(tmp_path, ip="23.227.38.5")
    except discord_fix.DiscordFixError as e:
        assert "администратор" in str(e)
    else:
        raise AssertionError("enable must fail without admin")




def test_ensure_started_restarts_helper(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    discord_fix.enable(tmp_path, ip="23.227.38.5")
    called = {"start": 0}
    monkeypatch.setattr(discord_fix, "_start_server", lambda ip: called.__setitem__("start", called["start"] + 1))
    monkeypatch.setattr(discord_fix, "_server_status", lambda: (False, ""))
    discord_fix.ensure_started(tmp_path)
    assert called["start"] == 1



def test_ensure_started_rotates_when_saved_ip_dead(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    discord_fix.enable(tmp_path, ip="23.227.38.5")
    state = discord_fix._read_state(tmp_path)
    state["selected_ip"] = "23.227.38.5"
    discord_fix._write_state(tmp_path, state)
    started = {"ip": ""}
    monkeypatch.setattr(discord_fix, "_server_status", lambda: (False, ""))
    monkeypatch.setattr(discord_fix, "_probe", lambda ip, timeout=2.0: False)
    monkeypatch.setattr(discord_fix, "choose_candidate", lambda root: "23.227.38.74")
    monkeypatch.setattr(discord_fix, "_start_server", lambda ip: started.__setitem__("ip", ip))
    discord_fix.ensure_started(tmp_path)
    assert started["ip"] == "23.227.38.74"
    assert discord_fix._read_state(tmp_path)["selected_ip"] == "23.227.38.74"



def test_shutdown_cleanup_keeps_task_nrpt(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    discord_fix.enable(tmp_path, ip="23.227.38.5")
    st = discord_fix._read_state(tmp_path)
    st["enabled"] = True
    st["mode"] = "task"
    discord_fix._write_state(tmp_path, st)
    calls = {"stop": 0, "nrpt": 0}
    monkeypatch.setattr(discord_fix, "_stop_server", lambda: calls.__setitem__("stop", calls["stop"] + 1))
    monkeypatch.setattr(discord_fix, "_nrpt_remove", lambda: calls.__setitem__("nrpt", calls["nrpt"] + 1))
    from core import utils
    monkeypatch.setattr(utils, "app_root", lambda: tmp_path)
    discord_fix._shutdown_cleanup()
    assert calls == {"stop": 0, "nrpt": 0}


def test_rotate_changes_selected_ip(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    discord_fix.enable(tmp_path, ip="23.227.38.5")
    monkeypatch.setattr(discord_fix, "choose_candidate", lambda root: "23.227.38.74")
    out = discord_fix.rotate(tmp_path)
    assert out["selected_ip"] == "23.227.38.74"
    txt = discord_fix.HOSTS_PATH.read_text(encoding="utf-8")
    assert "23.227.38.74 discord.com" in txt
