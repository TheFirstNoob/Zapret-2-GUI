"""P2 2026-11-15: импорт настроек не теряет вложенные USER_FILES,
а backup не падает на mtime < 1980."""
import io
import os
import zipfile
from pathlib import Path

from core import updater


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_import_settings_keeps_nested_user_files(tmp_path):
    data = _zip({
        "zapret2_config.json": b"{}",
        "lists/list-include-user.txt": b"example.com\n",
        "lists/list-games.txt": b"gw.example\n",
        "lists/list-include-all.txt": b"all.example\n",
        "presets/mine.txt": b"",
        "presets/custom.txt": b"",
        "old.exe": b"skip",
    })
    imported, skipped = updater.import_settings_zip(data, tmp_path)
    assert imported == 5, (imported, skipped)
    assert (tmp_path / "lists" / "list-games.txt").exists()
    assert (tmp_path / "lists" / "list-include-all.txt").exists()
    assert (tmp_path / "presets" / "mine.txt").exists()
    assert not (tmp_path / "presets" / "custom.txt").exists()


def test_backup_survives_pre_1980_mtime(tmp_path):
    f = tmp_path / "zapret2_config.json"
    f.write_text("{}", encoding="utf-8")
    os.utime(f, (0, 0))
    # Не должно быть ValueError: ZIP does not support timestamps before 1980
    updater._backup_user_files(tmp_path, "0.11")
