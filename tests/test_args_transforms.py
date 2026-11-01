from __future__ import annotations

from pathlib import Path

from core.args_transforms import ArgsCtx, transform_gamefilter_segments


def _ctx(mode: str = "udp") -> ArgsCtx:
    p = Path(".")
    return ArgsCtx(
        root_dir=p, lua_dir=p, blobs_dir=p, lists_dir=p, windivert_dir=p,
        game_filter_mode=mode, voice_mode="off", debug=False, fake_blob="",
        autohostlist=False, ipset_catchall=False, discord_alt=False,
        auto_path="", ipset_inc_path="", ipset_excl_path="",
    )


def test_gamefilter_merges_existing_wf_udp_out() -> None:
    tokens = ["--wf-udp-out", "443,19294-19344,50000-50100,1024-65535"]
    out = transform_gamefilter_segments(tokens, _ctx("udp"))
    flags = [i for i, t in enumerate(out) if t == "--wf-udp-out"]
    assert len(flags) == 1
    value = out[flags[0] + 1]
    assert value == "443,19294-19344,50000-50100,1024-65535"
