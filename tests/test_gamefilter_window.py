"""T23: GameFilter не расширяет окно захвата «чужого» протокола (аудит T9 №3).

До фикса %GameFilter% заменялся в ОБОИХ окнах (--wf-tcp-out и --wf-udp-out)
при любом ненулевом режиме: GameFilter=tcp редиректил в WinDivert весь
высокий диапазон UDP (и наоборот) без профилей - лишняя нагрузка и риск
конфликта с другими WinDivert-программами.

Тесты гоняют production-конвейер build_args_from_preset на реальных
release-пресетах (пути @-файлов не требуют существования, профили строятся
без записи в репозиторий - temp-root).
"""
from __future__ import annotations

from pathlib import Path

from core import preset_parse
from core.launcher import build_args_from_preset

ROOT = Path(__file__).resolve().parents[1]
BASE_TCP = "80,443,2053,2083,2087,2096,8443"
BASE_UDP = "443,19294-19344,50000-50100"
HIGH = preset_parse.HIGH_PORTS


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "lists").mkdir(parents=True)
    (root / "games.json").write_text('{"games": []}', encoding="utf-8")
    return root


def _build(root: Path, mode: str = "off", preset: str = "default.txt", **kw):
    return build_args_from_preset(
        root, ROOT / "lua", ROOT / "blobs", ROOT / "presets" / preset,
        lists_dir=root / "lists", windivert_dir=ROOT / "windivert",
        game_filter_mode=mode, **kw)


def _value(tokens: list[str], flag: str) -> str:
    for i, token in enumerate(tokens):
        if token == flag and i + 1 < len(tokens):
            return tokens[i + 1]
    raise AssertionError(f"{flag} не найден в {tokens[:30]}")


def _ports(value: str) -> list[str]:
    return [p for p in value.split(",") if p]


# ── preset_parse: подстановка только в своё направление ──────────────────

def _parse(tmp_path: Path, mode: str) -> list[str]:
    preset = tmp_path / "preset.txt"
    preset.write_text("--wf-tcp-out\n80,443,%GameFilter%\n"
                      "--wf-udp-out\n443,%GameFilter%\n", encoding="utf-8")
    return preset_parse.parse_preset(
        preset, lists_base=str(tmp_path / "lists"), lua_dir=tmp_path,
        blobs_dir=tmp_path, windivert_dir=tmp_path,
        game_filter_mode=mode, ipset_catchall=False, autohostlist=False,
        auto_path="", ipset_inc_path="", ipset_excl_path="")


def test_parse_tcp_mode_places_high_ports_only_in_tcp_window(tmp_path):
    assert _parse(tmp_path, "tcp") == [
        "--wf-tcp-out", f"80,443,{HIGH}", "--wf-udp-out", "443"]


def test_parse_udp_mode_places_high_ports_only_in_udp_window(tmp_path):
    assert _parse(tmp_path, "udp") == [
        "--wf-tcp-out", "80,443", "--wf-udp-out", f"443,{HIGH}"]


def test_parse_both_mode_places_high_ports_in_both_windows(tmp_path):
    assert _parse(tmp_path, "both") == [
        "--wf-tcp-out", f"80,443,{HIGH}", "--wf-udp-out", f"443,{HIGH}"]


def test_parse_off_mode_strips_placeholder_from_both_windows(tmp_path):
    assert _parse(tmp_path, "off") == [
        "--wf-tcp-out", "80,443", "--wf-udp-out", "443"]


# ── build_args_from_preset на реальном release-пресете ───────────────────

def test_tcp_mode_does_not_extend_udp_window(tmp_path):
    args = _build(_make_root(tmp_path), "tcp")
    assert _ports(_value(args, "--wf-tcp-out")) == [*BASE_TCP.split(","), HIGH]
    assert _ports(_value(args, "--wf-udp-out")) == BASE_UDP.split(",")
    assert "--filter-tcp=" + HIGH in args
    assert "--filter-udp=" + HIGH not in args


def test_udp_mode_does_not_extend_tcp_window(tmp_path):
    args = _build(_make_root(tmp_path), "udp")
    assert _ports(_value(args, "--wf-tcp-out")) == BASE_TCP.split(",")
    assert _ports(_value(args, "--wf-udp-out")) == [*BASE_UDP.split(","), HIGH]
    assert "--filter-udp=" + HIGH in args
    assert "--filter-tcp=" + HIGH not in args


def test_both_mode_extends_both_windows(tmp_path):
    args = _build(_make_root(tmp_path), "both")
    assert _ports(_value(args, "--wf-tcp-out")) == [*BASE_TCP.split(","), HIGH]
    assert _ports(_value(args, "--wf-udp-out")) == [*BASE_UDP.split(","), HIGH]
    assert "--filter-tcp=" + HIGH in args
    assert "--filter-udp=" + HIGH in args


def test_off_mode_keeps_windows_and_segments_clean(tmp_path):
    args = _build(_make_root(tmp_path), "off")
    assert _ports(_value(args, "--wf-tcp-out")) == BASE_TCP.split(",")
    assert _ports(_value(args, "--wf-udp-out")) == BASE_UDP.split(",")
    assert "--filter-tcp=" + HIGH not in args
    assert "--filter-udp=" + HIGH not in args


def test_udp_mode_profile_keeps_payload_all(tmp_path):
    """Профиль GameFilter-UDP обязан ловить unknown-UDP (payload=all)."""
    args = _build(_make_root(tmp_path), "udp")
    desync = [t for t in args if t.startswith("--lua-desync=") and "payload=all" in t]
    assert desync, args


# ── launcher: битый/неизвестный режим не включает GameFilter ─────────────

def test_unknown_mode_does_not_extend_windows(tmp_path):
    args = _build(_make_root(tmp_path), "botth")
    assert _ports(_value(args, "--wf-tcp-out")) == BASE_TCP.split(",")
    assert _ports(_value(args, "--wf-udp-out")) == BASE_UDP.split(",")
    assert "--filter-tcp=" + HIGH not in args


def test_non_string_mode_does_not_crash(tmp_path):
    args = _build(_make_root(tmp_path), 5)  # type: ignore[arg-type]
    assert _ports(_value(args, "--wf-udp-out")) == BASE_UDP.split(",")
    assert "--filter-udp=" + HIGH not in args


def test_non_string_fake_blob_does_not_crash(tmp_path):
    """Второй слой защиты: config-типы уже чинятся, но build_args не падает."""
    args = _build(_make_root(tmp_path), "off", fake_blob=5)  # type: ignore[arg-type]
    assert args
    assert not any("alt_tls" in t for t in args)
