"""T22: точечное hardening апдейтера (P3 аудита 2026-11-14).

Фейковые файлы, без сети и службы.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from core import updater as up


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _simple_zip(path: Path, files: dict, *, prefix: str = "app/",
                manifest_extra: dict | None = None) -> Path:
    manifest = {"version": "9.9",
                "files": {rel: _sha(data) for rel, data in files.items()}}
    manifest["files"].update(manifest_extra or {})
    with zipfile.ZipFile(path, "w") as zf:
        for rel, data in files.items():
            zf.writestr(prefix + rel, data)
        zf.writestr(prefix + "update_manifest.json",
                    json.dumps(manifest).encode())
    return path


# ── is_user_file: регистр + runtime-файлы ──────────────────────────────

def test_is_user_file_is_case_insensitive() -> None:
    # NTFS не различает регистр: верхний регистр не должен обходить защиту
    assert up.is_user_file("lists/LIST-INCLUDE-USER.TXT")
    assert up.is_user_file("ZAPRET2_CONFIG.JSON")
    assert up.is_user_file("LISTS/LIST-GAMES.TXT")
    assert up.is_user_file("presets/CUSTOM.TXT")
    # релизные файлы остаются системными в любом регистре
    assert not up.is_user_file("PRESETS/DEFAULT.TXT")
    assert not up.is_user_file("PRESETS/AUTO.TXT")


def test_zapret_auto_is_runtime_user_file() -> None:
    # autohostlist обхода: выученные домены; обновление их не перезаписывает,
    # а в settings-export (USER_FILES) файл не попадает (privacy)
    assert up.is_user_file("lists/zapret-auto.txt")
    assert up.is_user_file("lists/ZAPRET-AUTO.TXT")
    assert "lists/zapret-auto.txt" not in up.USER_FILES
    assert "lists/zapret-auto.txt" in up.RUNTIME_FILES


# ── validate_release: min_version ──────────────────────────────────────

def _manifest(**overrides) -> dict:
    base = {
        "schema": up.MANIFEST_SCHEMA,
        "version": "0.9",
        "tag": "Pre-Release-0.9",
        "artifacts": {
            "portable": {"file": "p.zip", "sha256": "b" * 64},
        },
    }
    base.update(overrides)
    return base


def test_bad_min_version_fails_closed() -> None:
    err = up.validate_release(_manifest(min_version="garbage"),
                              "Pre-Release-0.9", "0.8", "portable")
    assert err and "min_version" in err


def test_valid_min_version_enforced() -> None:
    err = up.validate_release(_manifest(min_version="0.10"),
                              "Pre-Release-0.9", "0.8", "portable")
    assert err and "не ниже 0.10" in err
    assert up.validate_release(_manifest(min_version="0.8"),
                               "Pre-Release-0.9", "0.8", "portable") is None


# ── манифест релиза: отдельный лимит скачивания ────────────────────────

def test_release_manifest_download_has_small_limit(tmp_path: Path,
                                                   monkeypatch) -> None:
    calls: list[int] = []

    def fake_download(url, dest, timeout=300, max_bytes=up.MAX_UPDATE_BYTES):
        calls.append(max_bytes)
        dest.write_bytes(b"{}")
        return None

    monkeypatch.setattr(up, "_download", fake_download)
    up.fetch_release_manifest("Pre-Release-0.9", tmp_path)
    assert calls and all(v == up.MANIFEST_MAX_BYTES for v in calls)


# ── бэкап: backups/ занят файлом - не роняем апдейт ────────────────────

def test_changed_windivert_files_compares_hashes(tmp_path: Path) -> None:
    root = tmp_path / "app"
    (root / "windivert").mkdir(parents=True)
    same = b"same-binary"
    (root / "windivert" / "WinDivert.dll").write_bytes(same)
    zp = _simple_zip(tmp_path / "upd.zip", {
        "windivert/WinDivert.dll": same,
        "windivert/WinDivert64.sys": b"new-driver",
    })
    assert up.changed_windivert_files(zp, root) == ["windivert/WinDivert64.sys"]


def test_apply_skips_identical_files(tmp_path: Path) -> None:
    """Неизменившиеся файлы не трогаем: WinDivert.dll может быть залочен."""
    root = tmp_path / "app"
    (root / "windivert").mkdir(parents=True)
    same = b"same-binary"
    (root / "windivert" / "WinDivert.dll").write_bytes(same)
    zp = _simple_zip(tmp_path / "upd.zip", {
        "windivert/WinDivert.dll": same,
        "core/x.py": b"print(1)",
    })
    res = up.apply_portable(zp, root)
    assert res["skipped_identical"] == 1
    assert res["updated"] == 1
    assert (root / "windivert" / "WinDivert.dll").read_bytes() == same


def test_backup_dir_is_file_does_not_abort_update(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / "backups").write_text("not-a-dir", encoding="utf-8")
    zp = _simple_zip(tmp_path / "upd.zip", {"core/x.py": b"print(1)"})
    res = up.apply_portable(zp, root)
    assert res["backup"] is None
    assert (root / "core" / "x.py").read_bytes() == b"print(1)"


# ── exe-архив без exe: понятная ошибка вместо пустой ───────────────────

def test_prepare_exe_update_reports_missing_exe(tmp_path: Path) -> None:
    zp = tmp_path / "upd.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("readme.txt", b"no exe here")
    with pytest.raises(RuntimeError) as ei:
        up.prepare_exe_update(zp, tmp_path, exe_sha256="0" * 64)
    assert "Zapret2GUI.exe" in str(ei.value)
    assert not (tmp_path / "Zapret2GUI.exe.new").exists()


# ── manifest completeness: архив с лишним файлом в манифесте ───────────

def test_truncated_archive_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    zp = _simple_zip(tmp_path / "upd.zip", {"core/x.py": b"print(1)"},
                     manifest_extra={"core/ghost.py": _sha(b"nope")})
    with pytest.raises(RuntimeError) as ei:
        up.apply_portable(zp, root)
    assert "неполный" in str(ei.value)
    assert not (root / "core" / "x.py").exists()
