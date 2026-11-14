"""Tests for core.strategy_builder: family-aware segments and --name parsing."""
from pathlib import Path

from core import strategy_builder as sb


def _preset(header: str, segs: list[tuple[str, str]]) -> str:
    parts = [header, "--new"]
    for name, body in segs:
        parts.append(f"--comment={name}")
        parts.append(body)
        parts.append("--new")
    return "\n".join(parts) + "\n"


def _make_root(tmp_path: Path) -> Path:
    (tmp_path / "lists").mkdir()
    lists = {"discord": "discord.com", "google": "google.com",
             "general": "example.com"}
    for fam, domain in lists.items():
        (tmp_path / "lists" / f"list-{fam}.txt").write_text(
            domain + "\n", encoding="utf-8")
    (tmp_path / "presets").mkdir()
    default = _preset("--wf-tcp-out\n80,443", [
        ("Discord TCP tls", "--lua-desync=default_discord"),
        ("Google TCP tls", "--lua-desync=default_google"),
        ("General TCP", "--lua-desync=default_general"),
        ("Discord Voice", "--filter-udp=19294-19344"),
        ("QUIC Google", "--filter-udp=443"),
    ])
    alt = _preset("--wf-tcp-out\n80,443", [
        ("Discord TCP", "--lua-desync=alt_discord"),
        ("Google TCP", "--lua-desync=alt_google"),
        ("General TCP", "--lua-desync=alt_general"),
    ])
    named = "--wf-tcp-out\n80,443\n--new\n--name\nweird_discord_tcp\n--lua-desync=x\n"
    (tmp_path / "presets" / "default.txt").write_text(default, encoding="utf-8")
    (tmp_path / "presets" / "alt.txt").write_text(alt, encoding="utf-8")
    (tmp_path / "presets" / "named.txt").write_text(named, encoding="utf-8")
    return tmp_path


def test_segment_family_variants():
    assert sb.segment_family("Discord TCP tls") == "discord"
    assert sb.segment_family("Discord TCP") == "discord"
    assert sb.segment_family("weird_discord_tcp") == "discord"
    assert sb.segment_family("Google TCP") == "google"
    assert sb.segment_family("General TCP") == "general"
    assert sb.segment_family("Discord Voice") is None
    assert sb.segment_family("QUIC Google") is None


def test_parse_preset_reads_name(tmp_path: Path):
    root = _make_root(tmp_path)
    _, segs = sb.parse_preset(root / "presets" / "named.txt")
    assert "weird_discord_tcp" in segs


def test_build_custom_picks_segment_by_family(tmp_path: Path):
    root = _make_root(tmp_path)
    results = {
        "default": [
            {"domain": "discord.com", "status": "FAIL", "test_type": "https"},
            {"domain": "google.com", "status": "FAIL", "test_type": "https"},
            {"domain": "example.com", "status": "FAIL", "test_type": "https"},
        ],
        "alt": [
            {"domain": "discord.com", "status": "OK", "test_type": "https"},
            {"domain": "google.com", "status": "OK", "test_type": "https"},
            {"domain": "example.com", "status": "OK", "test_type": "https"},
        ],
    }
    res = sb.build_custom(root, results)
    assert res["error"] is None
    text = (root / "presets" / "custom.txt").read_text(encoding="utf-8")
    assert "alt_discord" in text and "alt_google" in text and "alt_general" in text
    assert "default_discord" not in text
    assert "(из alt)" in text
