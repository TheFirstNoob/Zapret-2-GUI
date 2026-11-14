"""T23: тумблер "fake blob" работает на custom-lua пресетах (аудит T9 №5).

До фикса transform_fake_blob подменял ссылку только в
--lua-desync=fake:blob=<tls_blob>. Пресеты fake-disorder (tls_fake_disorder)
и fakedsplit (fakedsplit:blob=) продолжали использовать родной блоб, поэтому
выбор fake_blob молча не работал (A/B и ожидания пользователя ложные).

После фикса подменяется параметр blob=<TLS-блоб> в ЛЮБОМ --lua-desync=;
seqovl_pattern= (позиция перекрытия, не источник фейка) и QUIC-блобы
не трогаются.
"""
from __future__ import annotations

from pathlib import Path

from core.args_transforms import ArgsCtx, transform_fake_blob
from core.launcher import build_args_from_preset

ROOT = Path(__file__).resolve().parents[1]


def _ctx(tmp_path: Path, fake_blob: str) -> ArgsCtx:
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    (blobs / "tls_clienthello_alt.bin").write_bytes(b"\x00")
    p = tmp_path
    return ArgsCtx(
        root_dir=p, lua_dir=p, blobs_dir=blobs, lists_dir=p, windivert_dir=p,
        game_filter_mode="off", voice_mode="off", debug=False,
        fake_blob=fake_blob, autohostlist=False, ipset_catchall=False,
        discord_alt=False, auto_path="", ipset_inc_path="", ipset_excl_path="",
    )


def _tokens() -> list[str]:
    blob_tls = "@" + str(ROOT / "blobs" / "tls_clienthello_www_google_com.bin")
    blob_quic = "@" + str(ROOT / "blobs" / "quic_initial_www_google_com.bin")
    return [
        "--blob", f"google_tls:{blob_tls}",
        "--blob", f"quic_google:{blob_quic}",
        "--lua-desync=fake:blob=google_tls:tcp_ts=-1000:repeats=8",
        "--lua-desync=tls_fake_disorder:blob=google_tls:fakes=3",
        "--lua-desync=fakedsplit:blob=google_tls:pos=2",
        "--lua-desync=multisplit:pos=1,midsld:seqovl=681:seqovl_pattern=google_tls",
        "--lua-desync=fake:blob=quic_google",
    ]


def _alt_ctx(tmp_path: Path) -> ArgsCtx:
    return _ctx(tmp_path, "alt")


def test_tls_fake_disorder_uses_selected_blob(tmp_path):
    out = transform_fake_blob(_tokens(), _alt_ctx(tmp_path))
    assert "--lua-desync=tls_fake_disorder:blob=alt_tls:fakes=3" in out


def test_fakedsplit_uses_selected_blob(tmp_path):
    out = transform_fake_blob(_tokens(), _alt_ctx(tmp_path))
    assert "--lua-desync=fakedsplit:blob=alt_tls:pos=2" in out


def test_regular_fake_still_uses_selected_blob(tmp_path):
    out = transform_fake_blob(_tokens(), _alt_ctx(tmp_path))
    assert "--lua-desync=fake:blob=alt_tls:tcp_ts=-1000:repeats=8" in out


def test_seqovl_pattern_is_not_touched(tmp_path):
    out = transform_fake_blob(_tokens(), _alt_ctx(tmp_path))
    assert ("--lua-desync=multisplit:pos=1,midsld:seqovl=681:"
            "seqovl_pattern=google_tls") in out


def test_quic_blob_is_not_touched(tmp_path):
    out = transform_fake_blob(_tokens(), _alt_ctx(tmp_path))
    assert "--lua-desync=fake:blob=quic_google" in out


def test_alt_blob_registered_once(tmp_path):
    out = transform_fake_blob(_tokens(), _alt_ctx(tmp_path))
    alt = [i for i, t in enumerate(out) if t == "--blob" and out[i + 1].startswith("alt_tls:@")]
    assert len(alt) == 1


def test_missing_blob_file_is_noop(tmp_path):
    tokens = _tokens()
    out = transform_fake_blob(tokens, _ctx(tmp_path, "does_not_exist"))
    assert out == tokens


# ── интеграция: реальные пресеты с выбранным fake_blob ──────────────────

def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "lists").mkdir(parents=True)
    (root / "games.json").write_text('{"games": []}', encoding="utf-8")
    return root


def _build(root: Path, preset: str, fake_blob: str = "") -> list[str]:
    return build_args_from_preset(
        root, ROOT / "lua", ROOT / "blobs", ROOT / "presets" / preset,
        lists_dir=root / "lists", windivert_dir=ROOT / "windivert",
        fake_blob=fake_blob)


def _count(tokens: list[str], needle: str) -> int:
    return sum(t.count(needle) for t in tokens)


def test_fake_disorder_tumbler_reaches_all_tls_profiles(tmp_path):
    args = _build(_make_root(tmp_path), "fake-disorder.txt", "www_google_com")
    # 1 fake:blob= + 3 tls_fake_disorder:blob= -> все на alt_tls
    assert _count(args, "blob=alt_tls") == 4
    assert "alt_tls:@" in " ".join(args)


def test_fakedsplit_tumbler_reaches_fakedsplit_profile(tmp_path):
    args = _build(_make_root(tmp_path), "fakedsplit.txt", "www_google_com")
    # 4 fake:blob= + 3 fakedsplit:blob= -> все на alt_tls
    assert _count(args, "blob=alt_tls") == 7


def test_default_preset_fake_blob_behaviour_unchanged(tmp_path):
    args = _build(_make_root(tmp_path), "default.txt", "www_google_com")
    assert _count(args, "blob=alt_tls") == 4
    # seqovl_pattern остался родным у всех 4 профилей
    assert _count(args, "seqovl_pattern=google_tls") >= 4


def test_fake_disorder_seqovl_pattern_kept(tmp_path):
    args = _build(_make_root(tmp_path), "fake-disorder.txt", "www_google_com")
    assert _count(args, "seqovl_pattern=google_tls") == 1
