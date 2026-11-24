"""YouTube GGC test worker: no real DNS/NRPT."""
from pathlib import Path

from core import discord_fix, youtube_fix


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube_fix, "is_admin", lambda: True)
    monkeypatch.setattr(youtube_fix, "choose_edge", lambda preferred="": "74.125.131.102")
    monkeypatch.setattr(youtube_fix, "_nrpt_add", lambda: None)
    monkeypatch.setattr(youtube_fix, "_nrpt_remove", lambda: None)
    monkeypatch.setattr(youtube_fix, "_nrpt_count", lambda: 1)
    monkeypatch.setattr(youtube_fix, "_start_server", lambda ip: None)
    monkeypatch.setattr(youtube_fix, "_stop_server", lambda: None)
    monkeypatch.setattr(youtube_fix, "_flush_dns", lambda: None)
    monkeypatch.setattr(youtube_fix, "_server_status", lambda: (True, "74.125.131.102"))
    monkeypatch.setattr(discord_fix, "status", lambda root: {"dns_running": False})


def test_zone_match() -> None:
    assert youtube_fix._is_googlevideo("rr2---sn-gvnuxaxjvh-ov1e.googlevideo.com")
    assert youtube_fix._is_googlevideo("GOOGLEVIDEO.COM")
    assert not youtube_fix._is_googlevideo("youtube.com")


def test_enable_status_disable(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    out = youtube_fix.enable(tmp_path)
    assert out["enabled"] is True
    assert out["selected_ip"] == "74.125.131.102"
    assert (tmp_path / "logs" / "youtube_fix_state.json").is_file()
    monkeypatch.setattr(youtube_fix, "choose_edge", lambda preferred="", exclude="": "142.251.155.155" if exclude else "74.125.131.102")
    rot = youtube_fix.rotate(tmp_path)
    assert rot["selected_ip"] == "142.251.155.155"
    off = youtube_fix.disable(tmp_path)
    assert off["enabled"] is False
    assert not (tmp_path / "logs" / "youtube_fix_state.json").exists()


def test_requires_admin(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(youtube_fix, "is_admin", lambda: False)
    try:
        youtube_fix.enable(tmp_path)
    except youtube_fix.YouTubeFixError as e:
        assert "администратор" in str(e)
    else:
        raise AssertionError("enable must fail without admin")
