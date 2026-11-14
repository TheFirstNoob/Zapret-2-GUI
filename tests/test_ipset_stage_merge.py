"""Stage-merge ipset: staged gz без изменения релизной базы."""
import gzip
import ipaddress
import subprocess
import sys
from pathlib import Path


def test_stage_merge_does_not_touch_base(tmp_path: Path):
    base = tmp_path / "lists" / "ipset-all.txt.gz"
    base.parent.mkdir()
    with gzip.open(base, "wb") as f:
        f.write(b"1.0.0.0/24\n2.0.0.0/24\n")
    base_before = base.read_bytes()
    cand = tmp_path / "cand.txt"
    cand.write_text("1.0.0.0/24\n3.0.0.0/24\n", encoding="utf-8")
    out = tmp_path / "staged.txt.gz"
    code = subprocess.call([sys.executable,
                            str(Path(__file__).resolve().parents[1] / "tools" / "ipset_stage_merge.py"),
                            "--base", str(base),
                            "--candidates", str(cand), "--out", str(out)])
    assert code == 0
    assert base.read_bytes() == base_before
    nets = {str(n) for n in gzip.open(out, "rt").read().splitlines() if n}
    assert nets == {"1.0.0.0/24", "2.0.0.0/24", "3.0.0.0/24"}
