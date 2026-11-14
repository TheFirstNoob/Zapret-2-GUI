"""Tests for main._copy_data_dir resilience (audit 2026-11-14, P0)."""
from pathlib import Path

import main


def test_copy_data_dir_ok(tmp_path: Path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src).mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")
    assert main._copy_data_dir(src, dst, "bin") == 0
    assert (dst / "a.txt").read_text(encoding="utf-8") == "x"


def test_copy_data_dir_locked_file_marks_failure(tmp_path: Path, monkeypatch):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir(); dst.mkdir()
    (src / "winws2.exe").write_bytes(b"new")
    (dst / "winws2.exe").write_bytes(b"old")
    real_copy = main.shutil.copy2

    def fake_copy(s, d, *a, **k):
        d = Path(d)
        if d.name == "winws2.exe":
            raise OSError(32, "file in use")
        return real_copy(s, d, *a, **k)

    monkeypatch.setattr(main.shutil, "copy2", fake_copy)
    assert main._copy_data_dir(src, dst, "bin") == 1
    assert (dst / "winws2.exe.new").read_bytes() == b"new"
