"""P0 2026-11-15: service_run.conf — один токен на строку, не cmdline."""
from pathlib import Path

from core.launcher import read_run_conf, write_run_conf


def test_run_conf_roundtrip_quoted_paths(tmp_path):
    args = [
        "--wf-tcp-out", "80,443",
        "--lua-init=@C:\\Program Files\\Zapret\\lua\\zapret-lib.lua",
        "--blob", "google_tls:@C:\\Program Files\\Zapret\\blobs\\tls.bin",
        "--lua-desync=multisplit:pos=1,midsld:seqovl=681",
    ]
    conf = write_run_conf(tmp_path, args, name="service_run.conf")
    assert read_run_conf(conf) == args


def test_run_conf_ignores_blank_lines(tmp_path):
    conf = Path(tmp_path) / "x.conf"
    conf.write_text("--a\n\n--b value\n", encoding="utf-8")
    assert read_run_conf(conf) == ["--a", "--b value"]
