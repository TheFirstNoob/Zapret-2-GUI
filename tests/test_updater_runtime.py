"""T22: portable-runtime (python/) в обновлении + mixed-install 0.10→0.11.

Только фейковые файлы/архивы: ни сети, ни службы, ни живых установок.
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

from core import updater as up


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_runtime(root: Path, rev: str = "", *, exe: bool = True,
                 packages: bool = True) -> Path:
    """Создать <root>/python; rev="" - рантайм 0.10 (маркера нет)."""
    rt = root / "python"
    site = rt / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    if exe:
        (rt / "pythonw.exe").write_bytes(b"MZ-runtime")
        (rt / "python.exe").write_bytes(b"MZ-runtime")
    if packages:
        for pkg in up.RUNTIME_PACKAGES:
            (site / pkg).mkdir(exist_ok=True)
            (site / pkg / "__init__.py").write_bytes(b"# pkg\n")
    if rev:
        (rt / up.RUNTIME_MARKER_NAME).write_text(json.dumps({
            "rev": rev, "python": "3.13.14",
            "packages": list(up.RUNTIME_PACKAGES)}), encoding="utf-8")
    return rt


def make_app(root: Path, *, version: str = "Pre-Release 0.12",
             required_rev: str = "") -> Path:
    app = root / "app"
    (app / "core").mkdir(parents=True, exist_ok=True)
    (app / "core" / "config.py").write_text(
        f'VERSION = "{version}"\n', encoding="utf-8")
    # признак portable-раскладки для find_runtime_dir (не «чужой» python/)
    (app / "main.pyw").write_bytes(b"# app\n")
    if required_rev:
        (app / up.RUNTIME_REQUIRED_NAME).write_text(
            json.dumps({"rev": required_rev, "python": "3.13.14"}),
            encoding="utf-8")
    return app


def build_portable_zip(root: Path, *, version: str = "Pre-Release 0.12",
                       runtime_rev: str = "rev-new",
                       app_extra: dict | None = None,
                       runtime_extra: dict | None = None,
                       with_runtime: bool = True,
                       manifest_extra: dict | None = None,
                       raw_entries: dict | None = None,
                       corrupt_runtime: str = "") -> Path:
    """Собрать portable-архив (app/** + python/** + update_manifest.json)."""
    files: dict[str, bytes] = {
        "app/core/config.py": f'VERSION = "{version}"\n'.encode(),
        f"app/{up.RUNTIME_REQUIRED_NAME}": json.dumps(
            {"rev": runtime_rev, "python": "3.13.14"}).encode(),
    }
    for rel, data in (app_extra or {}).items():
        files["app/" + rel] = data
    if with_runtime:
        files["python/pythonw.exe"] = b"MZ-runtime"
        files["python/python.exe"] = b"MZ-runtime"
        files[f"python/{up.RUNTIME_MARKER_NAME}"] = json.dumps({
            "rev": runtime_rev, "python": "3.13.14",
            "packages": list(up.RUNTIME_PACKAGES)}).encode()
        for pkg in up.RUNTIME_PACKAGES:
            files[f"python/Lib/site-packages/{pkg}/__init__.py"] = b"# pkg\n"
        for rel, data in (runtime_extra or {}).items():
            files["python/" + rel] = data
    manifest = {
        "version": version,
        "files": {rel[len("app/"):]: _sha(data) for rel, data in files.items()
                  if rel.startswith("app/")},
    }
    if manifest_extra:
        manifest["files"].update(manifest_extra)
    if with_runtime:
        manifest["runtime"] = {
            "rev": runtime_rev, "python": "3.13.14",
            "packages": list(up.RUNTIME_PACKAGES),
            "files": {rel: _sha(data) for rel, data in files.items()
                      if rel.startswith("python/")},
        }
    zp = root / "update_portable.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        for rel, data in files.items():
            zf.writestr(rel, data)
        for rel, data in (raw_entries or {}).items():
            zf.writestr(rel, data)
        zf.writestr("app/update_manifest.json",
                    json.dumps(manifest, indent=2).encode())
    if corrupt_runtime:
        with zipfile.ZipFile(zp, "a") as zf:
            zf.writestr(corrupt_runtime, b"tampered")
    return zp


# ── ревизия рантайма ────────────────────────────────────────────────────

def test_runtime_rev_depends_on_requirements_and_python() -> None:
    base = up.runtime_rev_for(b"pywebview==1\n", "3.13.14")
    assert base == up.runtime_rev_for(b"pywebview==1\r\n", "3.13.14")
    assert len(base) == 16
    assert base != up.runtime_rev_for(b"pywebview==2\n", "3.13.14")
    assert base != up.runtime_rev_for(b"pywebview==1\n", "3.12.1")


def test_find_runtime_dir_portable_layout(tmp_path: Path) -> None:
    app = make_app(tmp_path, required_rev="r")
    rt = make_runtime(tmp_path, "r")
    assert up.find_runtime_dir(app) == rt.resolve()


def test_find_runtime_dir_none_for_plain_tree(tmp_path: Path) -> None:
    app = make_app(tmp_path, required_rev="r")
    assert up.find_runtime_dir(app) is None
    assert up.runtime_status(app)["state"] == "not_portable"
    assert up.runtime_needs_update(app) is False


def test_runtime_status_states(tmp_path: Path) -> None:
    app = make_app(tmp_path, required_rev="rev-2")
    rt = make_runtime(tmp_path, "rev-2")
    assert up.runtime_status(app)["state"] == "ok"
    assert up.runtime_needs_update(app) is False

    # app ещё не знает требуемую ревизию (0.10-установка до апдейта)
    (app / up.RUNTIME_REQUIRED_NAME).unlink()
    assert up.runtime_status(app)["state"] == "required_unknown"

    # требование есть, а маркера у рантайма нет (0.10-рантайм)
    (app / up.RUNTIME_REQUIRED_NAME).write_text(
        json.dumps({"rev": "rev-2"}), encoding="utf-8")
    (rt / up.RUNTIME_MARKER_NAME).unlink()
    assert up.runtime_status(app)["state"] == "runtime_missing"
    assert up.runtime_needs_update(app) is True

    # ревизии расходятся
    (rt / up.RUNTIME_MARKER_NAME).write_text(
        json.dumps({"rev": "rev-1"}), encoding="utf-8")
    assert up.runtime_status(app)["state"] == "stale"

    # ревизия совпала, но пакетов нет
    (rt / up.RUNTIME_MARKER_NAME).write_text(
        json.dumps({"rev": "rev-2"}), encoding="utf-8")
    (rt / "Lib" / "site-packages" / "qh3").rename(rt / "Lib" / "site-packages" / "x")
    status = up.runtime_status(app)
    assert status["state"] == "broken"
    assert "qh3" in status["message"] or "niquests" in status["message"]


# ── apply_portable: staging runtime ─────────────────────────────────────

def test_apply_portable_stages_runtime(tmp_path: Path) -> None:
    root = tmp_path / "portable"
    app = make_app(root, version="Pre-Release 0.11", required_rev="rev-old")
    rt = make_runtime(root, "rev-old")
    (app / "core" / "old.txt").write_text("keep", encoding="utf-8")
    zp = build_portable_zip(root, version="Pre-Release 0.12",
                            runtime_rev="rev-new")
    res = up.apply_portable(zp, app, expected_version="Pre-Release 0.12")

    assert res["runtime_staged"] == str(root / "python.new")
    assert res["runtime_files"] > 0
    assert res["runtime_rev"] == "rev-new"
    # живой python/ не тронут, подготовленный - с новой ревизией
    assert up.read_runtime_rev(rt) == "rev-old"
    staged = Path(res["runtime_staged"])
    assert up.read_runtime_rev(staged) == "rev-new"
    assert (staged / "pythonw.exe").is_file()
    # app/ обновлён, требование доехало
    assert "0.12" in (app / "core" / "config.py").read_text(encoding="utf-8")
    assert up.read_required_runtime_rev(app) == "rev-new"
    # до переключения установка честно считается смешанной
    assert up.runtime_status(app)["state"] == "stale"
    # бэкап юзер-данных создан, python.old не появился
    assert res["backup"] and Path(res["backup"]).is_file()
    assert not (root / "python.old").exists()


def test_apply_portable_skips_runtime_when_rev_matches(tmp_path: Path) -> None:
    root = tmp_path / "portable"
    app = make_app(root, version="Pre-Release 0.11", required_rev="rev-same")
    rt = make_runtime(root, "rev-same")
    zp = build_portable_zip(root, version="Pre-Release 0.12",
                            runtime_rev="rev-same")
    res = up.apply_portable(zp, app, expected_version="Pre-Release 0.12")
    assert res["runtime_staged"] is None
    assert res["runtime_skipped"] == "up_to_date"
    assert res["runtime_files"] == 0
    assert not (root / "python.new").exists()
    assert up.read_runtime_rev(rt) == "rev-same"
    # app-файлы при этом обновлены
    assert "0.12" in (app / "core" / "config.py").read_text(encoding="utf-8")


def test_apply_portable_no_runtime_for_dev_tree(tmp_path: Path) -> None:
    # без python/ рядом (exe/исходники): поведение как раньше, app обновляется
    app = make_app(tmp_path, required_rev="")
    zp = build_portable_zip(tmp_path, version="Pre-Release 0.12",
                            with_runtime=False)
    res = up.apply_portable(zp, app, expected_version="Pre-Release 0.12")
    assert res["runtime_staged"] is None
    assert res["runtime_files"] == 0
    assert "0.12" in (app / "core" / "config.py").read_text(encoding="utf-8")


# ── fail-closed: смешанная установка и битые архивы ────────────────────

def test_apply_fail_closed_when_archive_has_no_runtime(tmp_path: Path) -> None:
    """Обновление app/ без python/ при устаревшем рантайме: откат + требование
    переустановки (не оставляем смешанную копию)."""
    root = tmp_path / "portable"
    app = make_app(root, version="Pre-Release 0.11", required_rev="rev-old")
    rt = make_runtime(root, "rev-old")
    zp = build_portable_zip(root, version="Pre-Release 0.12",
                            runtime_rev="rev-new", with_runtime=False)
    with pytest.raises(RuntimeError) as ei:
        up.apply_portable(zp, app, expected_version="Pre-Release 0.12")
    msg = str(ei.value)
    assert "откат выполнен" in msg
    assert "переустанов" in msg
    # app-файлы откатаны до 0.11, python.new не оставлен
    assert "Pre-Release 0.11" in (app / "core" / "config.py").read_text(
        encoding="utf-8")
    assert "Pre-Release 0.12" not in (app / "core" / "config.py").read_text(
        encoding="utf-8")
    assert not (root / "python.new").exists()
    assert up.read_runtime_rev(rt) == "rev-old"


def test_apply_rolls_back_on_version_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "portable"
    app = make_app(root, required_rev="rev-1")
    rt = make_runtime(root, "rev-1")
    (app / "core" / "config.py").write_text(
        'VERSION = "Pre-Release 0.11"\n', encoding="utf-8")
    zp = build_portable_zip(root, version="Pre-Release 0.12",
                            runtime_rev="rev-1")
    with pytest.raises(RuntimeError) as ei:
        # подписанный манифест релиза говорит 0.13, а в архиве 0.12
        up.apply_portable(zp, app, expected_version="Pre-Release 0.13")
    assert "0.11" in (app / "core" / "config.py").read_text(encoding="utf-8")
    assert not (root / "python.new").exists()
    assert up.read_runtime_rev(rt) == "rev-1"


def test_apply_rejects_truncated_archive(tmp_path: Path) -> None:
    root = tmp_path / "portable"
    app = make_app(root, required_rev="rev-1")
    make_runtime(root, "rev-1")
    zp = build_portable_zip(
        root, runtime_rev="rev-1",
        manifest_extra={"core/ghost.py": "a" * 64})
    with pytest.raises(RuntimeError) as ei:
        up.apply_portable(zp, app, expected_version="Pre-Release 0.12")
    assert "неполный" in str(ei.value)


def test_apply_rejects_ads_path(tmp_path: Path) -> None:
    root = tmp_path / "portable"
    app = make_app(root, required_rev="rev-1")
    make_runtime(root, "rev-1")
    zp = build_portable_zip(root, runtime_rev="rev-1",
                            raw_entries={"app/core/x.py:hidden": b"evil"})
    with pytest.raises(RuntimeError) as ei:
        up.apply_portable(zp, app, expected_version="Pre-Release 0.12")
    assert "небезопасный путь" in str(ei.value)


def test_apply_rejects_corrupt_runtime_file(tmp_path: Path) -> None:
    root = tmp_path / "portable"
    app = make_app(root, required_rev="rev-1")
    rt = make_runtime(root, "rev-1")
    zp = build_portable_zip(
        root, runtime_rev="rev-2",
        corrupt_runtime="python/Lib/site-packages/qh3/__init__.py")
    with pytest.raises(RuntimeError) as ei:
        up.apply_portable(zp, app, expected_version="Pre-Release 0.12")
    assert "повреждён" in str(ei.value)
    assert not (root / "python.new").exists()
    assert up.read_runtime_rev(rt) == "rev-1"


def test_apply_rejects_staged_rev_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "portable"
    app = make_app(root, required_rev="rev-1")
    rt = make_runtime(root, "rev-1")
    # маркер внутри архива врёт: манифест говорит rev-2, файл - rev-evil
    zp = build_portable_zip(
        root, runtime_rev="rev-2",
        runtime_extra={up.RUNTIME_MARKER_NAME: json.dumps(
            {"rev": "rev-evil", "python": "3.13.14"}).encode()})
    with pytest.raises(RuntimeError) as ei:
        up.apply_portable(zp, app, expected_version="Pre-Release 0.12")
    assert "ревизи" in str(ei.value)
    assert not (root / "python.new").exists()
    assert up.read_runtime_rev(rt) == "rev-1"


def test_apply_fail_closed_on_low_disk_space(tmp_path: Path,
                                             monkeypatch) -> None:
    root = tmp_path / "portable"
    app = make_app(root, required_rev="rev-1")
    rt = make_runtime(root, "rev-1")
    zp = build_portable_zip(root, runtime_rev="rev-2")

    class _Usage:
        free = 1024

    monkeypatch.setattr(up.shutil, "disk_usage", lambda _p: _Usage())
    with pytest.raises(RuntimeError) as ei:
        up.apply_portable(zp, app, expected_version="Pre-Release 0.12")
    assert "места" in str(ei.value)
    assert not (root / "python.new").exists()
    assert up.read_runtime_rev(rt) == "rev-1"


def test_apply_keeps_user_file_with_uppercase_name(tmp_path: Path) -> None:
    """NTFS не различает регистр: архив с LIST-INCLUDE-USER.TXT не должен
    перезаписать user-файл (P3 аудита)."""
    root = tmp_path / "portable"
    app = make_app(root, required_rev="")
    (app / "lists").mkdir()
    (app / "lists" / "list-include-user.txt").write_text(
        "user-domain.example\n", encoding="utf-8")
    zp = build_portable_zip(
        root, with_runtime=False,
        raw_entries={"app/lists/LIST-INCLUDE-USER.TXT": b"evil.example\n"})
    up.apply_portable(zp, app, expected_version="Pre-Release 0.12")
    assert (app / "lists" / "list-include-user.txt").read_text(
        encoding="utf-8") == "user-domain.example\n"


# ── батник перезапуска: атомарное переключение runtime ─────────────────

def _portable_with_stage(tmp_path: Path):
    root = tmp_path / "portable"
    app = make_app(root, required_rev="rev-new")
    rt = make_runtime(root, "rev-old")
    staged = root / "python.new"
    staged.mkdir()
    (staged / "pythonw.exe").write_bytes(b"MZ-new")
    (app / "main.pyw").write_bytes(b"# app")
    return app, rt, staged


def test_restart_bat_switches_runtime(tmp_path: Path, monkeypatch) -> None:
    app, rt, staged = _portable_with_stage(tmp_path)
    monkeypatch.setattr(sys, "executable", str(rt / "pythonw.exe"))
    monkeypatch.setattr(sys, "argv", [str(app / "main.pyw")])
    bat = up.prepare_app_restart_bat(
        app, 4242, runtime_staged=staged, runtime_dir=rt)
    text = bat.read_text(encoding="ascii")
    assert "taskkill /F /PID 4242" in text
    assert 'move /y "%~dp0..\\python" "%~dp0..\\python.old"' in text
    assert 'move /y "%~dp0..\\python.new" "%~dp0..\\python"' in text
    assert ":rollback" in text and ":switch_failed" in text
    assert 'move /y "%~dp0..\\python.old" "%~dp0..\\python"' in text
    # порядок: убить процесс -> move -> start
    assert text.index("taskkill") < text.index("move /y")
    assert text.index("move /y") < text.index('start ""')
    assert "\r\r\n" not in text
    # portable-интерпретатор - относительным путём (кириллица в пути не ломает)
    assert 'start "" "%~dp0..\\python\\pythonw.exe" "%~dp0main.pyw"' in text


def test_restart_bat_is_plain_without_runtime(tmp_path: Path,
                                              monkeypatch) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.pyw").write_bytes(b"# app")
    monkeypatch.setattr(sys, "argv", [str(app / "main.pyw")])
    bat = up.prepare_app_restart_bat(app, 4242)
    text = bat.read_text(encoding="ascii")
    assert "taskkill /F /PID 4242" in text
    assert "move /y" not in text
    assert "runtime" not in text.lower()
    assert "\r\r\n" not in text


def test_restart_bat_relative_paths_with_cyrillic_install(
        tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "Моя папка с пробелом"
    app = make_app(base, required_rev="rev-1")
    rt = make_runtime(base, "rev-1")
    (app / "main.pyw").write_bytes(b"# app")
    monkeypatch.setattr(sys, "executable", str(rt / "pythonw.exe"))
    monkeypatch.setattr(sys, "argv", [str(app / "main.pyw")])
    bat = up.prepare_app_restart_bat(app, 77)
    raw = bat.read_bytes()
    raw.decode("ascii")  # установка с кириллицей => батник всё равно ASCII
    text = raw.decode("ascii")
    assert "%~dp0..\\python\\pythonw.exe" in text
    assert str(base) not in text


# ── манифест: секция runtime + сборка/применение roundtrip ─────────────

def test_new_runtime_dir_requires_explicit_existing(tmp_path: Path) -> None:
    app = make_app(tmp_path, required_rev="")
    zp = build_portable_zip(tmp_path, with_runtime=False)
    with pytest.raises(RuntimeError) as ei:
        up.apply_portable(zp, app, runtime_dir=tmp_path / "no-python")
    assert "runtime" in str(ei.value)


def test_write_manifest_runtime_section(tmp_path: Path) -> None:
    app = tmp_path / "app"
    (app / "core").mkdir(parents=True)
    (app / "core" / "config.py").write_bytes(b'VERSION = "Pre-Release 0.12"\n')
    (app / "lists").mkdir()
    (app / "lists" / "list-include-user.txt").write_bytes(b"user\n")
    rt = tmp_path / "python"
    (rt / "Lib" / "site-packages" / "q").mkdir(parents=True)
    (rt / "Lib" / "site-packages" / "q" / "x.py").write_bytes(b"# x\n")
    (rt / "pythonw.exe").write_bytes(b"MZ")
    (rt / "__pycache__").mkdir()
    (rt / "__pycache__" / "junk.pyc").write_bytes(b"junk")
    (rt / up.RUNTIME_MARKER_NAME).write_text(json.dumps(
        {"rev": "rev-9", "python": "3.13.14",
         "packages": list(up.RUNTIME_PACKAGES)}), encoding="utf-8")
    manifest = up.write_manifest(app, "Pre-Release 0.12", runtime_dir=rt)
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    assert doc["version"] == "Pre-Release 0.12"
    assert doc["files"]["core/config.py"]
    assert "lists/list-include-user.txt" not in doc["files"]  # юзер-файл
    runtime = doc["runtime"]
    assert runtime["rev"] == "rev-9"
    assert runtime["python"] == "3.13.14"
    assert runtime["files"]["python/Lib/site-packages/q/x.py"]
    assert runtime["files"]["python/pythonw.exe"]
    assert not any(k.endswith(".pyc") for k in runtime["files"])


def test_build_to_apply_roundtrip(tmp_path: Path) -> None:
    """write_runtime_markers + write_manifest + реальный zip -> apply_portable."""
    import build_portable

    portable = tmp_path / "portable"
    app = portable / "app"
    (app / "core").mkdir(parents=True)
    (app / "core" / "config.py").write_text(
        'VERSION = "Pre-Release 0.12"\n', encoding="utf-8")
    (app / "lists").mkdir()
    (app / "lists" / "list-include-user.txt").write_text(
        "user.example\n", encoding="utf-8")
    req = tmp_path / "requirements.txt"
    req.write_text("niquests==1\n", encoding="utf-8")
    rt = make_runtime(portable)  # без маркера - сборка сейчас его напишет

    rev = build_portable.write_runtime_markers(
        app, rt, req, "3.13.14")
    assert rev == up.runtime_rev_for(req.read_bytes(), "3.13.14")
    assert up.read_runtime_rev(rt) == rev
    assert up.read_required_runtime_rev(app) == rev
    up.write_manifest(app, "Pre-Release 0.12", runtime_dir=rt)

    dist = tmp_path / "dist.zip"
    with zipfile.ZipFile(dist, "w") as zf:
        for base, prefix in ((app, "app/"), (rt, "python/")):
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    zf.write(p, prefix + p.relative_to(base).as_posix())

    # установка 0.10-состояния: старый app + рантайм без маркера
    inst = tmp_path / "install"
    inst_app = make_app(inst, version="Pre-Release 0.11")
    inst_rt = make_runtime(inst)
    res = up.apply_portable(
        dist, inst_app, expected_version="Pre-Release 0.12")
    assert res["runtime_staged"]
    assert up.read_runtime_rev(inst_rt) == ""        # живой python/ не тронут
    assert up.read_runtime_rev(Path(res["runtime_staged"])) == rev
    assert up.runtime_status(inst_app)["state"] == "runtime_missing"
    assert "0.12" in (inst_app / "core" / "config.py").read_text(
        encoding="utf-8")


# ── 0.10 → 0.11: старый апдейтер не умеет python/ ─────────────────────

_USER_FILES_010 = (
    "zapret2_config.json", "games.json", "lists/list-include-user.txt",
    "lists/list-exclude-user.txt", "lists/list-games.txt",
    "lists/ipset-include-user.txt", "lists/ipset-exclude-user.txt",
    "test_session.log", "test_session.old.log", "debug_winws2.log",
)


def _apply_like_010(zip_path: Path, root_dir: Path) -> list:
    """Упрощённая копия apply_portable из 0.10 (тег 3fd25f0).

    Ключевое отличие от HEAD: всё вне app/ пропускается (skipped_nonapp),
    rollback и post-check отсутствуют. Нужен, чтобы доказать: app/ доедет,
    python/ - нет, и новый код обязан это заметить.
    """
    copied: list[str] = []

    def is_user_010(rel: str) -> bool:
        rel = rel.replace("/", "\\").lstrip("\\")
        p = Path(rel)
        return (rel in _USER_FILES_010
                or (p.parts[:1] == ("lists",) and p.name.endswith("-user.txt"))
                or p.parts[:2] == ("lists", "games")
                or (p.parts[:1] == ("presets",) and p.name.endswith(".txt")
                    and p.stem not in up.RELEASE_PRESETS))

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        prefix = "app/" if any(n.startswith("app/") for n in names) else ""
        manifest = json.loads(zf.read(
            prefix + "update_manifest.json").decode("utf-8")).get("files") or {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename
            if prefix and rel.startswith(prefix):
                rel = rel[len(prefix):]
            elif prefix:
                continue  # python/ и прочее вне app/ - старый код пропускает
            if not rel or rel == "update_manifest.json":
                continue
            if is_user_010(rel):
                continue
            data = zf.read(info)
            expected = manifest.get(rel)
            if expected and _sha(data) != expected:
                raise RuntimeError(rel)
            target = root_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            copied.append(rel)
    return copied


def test_old_010_updater_delivers_app_but_not_runtime(tmp_path: Path) -> None:
    src = tmp_path / "new"
    make_app(src, version="Pre-Release 0.11", required_rev="rev-new")
    make_runtime(src, "rev-new")
    zp = build_portable_zip(src, version="Pre-Release 0.11",
                            runtime_rev="rev-new")

    inst = tmp_path / "install"
    inst_app = make_app(inst, version="Pre-Release 0.10")
    inst_rt = make_runtime(inst)  # маркера нет = 0.10-рантайм

    copied = _apply_like_010(zp, inst_app)
    assert "core/config.py" in copied
    assert "runtime.json" in copied  # требование доехало обычным app-файлом
    assert "0.11" in (inst_app / "core" / "config.py").read_text(encoding="utf-8")
    # python/ старый апдейтер не трогает и в app/ не копирует
    assert up.read_runtime_rev(inst_rt) == ""
    assert not (inst_app / "python").exists()
    # ... и новый код обязан увидеть смешанную установку
    status = up.runtime_status(inst_app)
    assert status["portable"] is True
    assert status["state"] == "runtime_missing"
    assert up.runtime_needs_update(inst_app) is True


# ── release-гейт: portable-архив обязан нести runtime-секцию ───────────

def _release_publish():
    from tools import release_publish as rp
    return rp


def test_publish_gate_accepts_portable_with_runtime(tmp_path: Path) -> None:
    root = tmp_path / "src"
    make_app(root, version="Pre-Release 0.12", required_rev="rev-1")
    make_runtime(root, "rev-1")
    zp = build_portable_zip(root, version="Pre-Release 0.12",
                            runtime_rev="rev-1")
    assert _release_publish()._portable_runtime_problems(zp) == []


def test_publish_gate_flags_missing_runtime_section(tmp_path: Path) -> None:
    root = tmp_path / "src"
    make_app(root, version="Pre-Release 0.12")
    zp = build_portable_zip(root, version="Pre-Release 0.12",
                            with_runtime=False)
    problems = _release_publish()._portable_runtime_problems(zp)
    assert problems and "runtime.rev" in problems[0]


def test_publish_gate_flags_missing_runtime_file(tmp_path: Path) -> None:
    zp = tmp_path / "portable.zip"
    manifest = {
        "version": "0.12",
        "files": {"core/config.py": "a" * 64},
        "runtime": {"rev": "rev-1", "files": {
            "python/Lib/site-packages/q/x.py": "b" * 64}},
    }
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("app/update_manifest.json", json.dumps(manifest))
        zf.writestr("python/ZAPRET2_RUNTIME.json", b"{}")
    problems = _release_publish()._portable_runtime_problems(zp)
    assert problems and "runtime-файлов нет" in problems[0]


def test_publish_gate_flags_broken_zip(tmp_path: Path) -> None:
    zp = tmp_path / "portable.zip"
    zp.write_bytes(b"not a zip at all")
    problems = _release_publish()._portable_runtime_problems(zp)
    assert problems and "zip" in problems[0]


def test_find_runtime_dir_ignores_foreign_python_dir(tmp_path: Path) -> None:
    """Папка, просто названная app (dev/exe), не должна принять чужой python/."""
    app = tmp_path / "app"
    (app / "core").mkdir(parents=True)  # нет main.pyw = не portable-раскладка
    foreign = make_runtime(tmp_path, "rev-1")
    assert up.find_runtime_dir(app) is None
    assert foreign.is_dir()  # чужой каталог существует и не тронут


# ── worker: сквозная проводка runtime-обновления ───────────────────────

def test_worker_wires_runtime_update(tmp_path: Path, monkeypatch) -> None:
    """run_update_worker: подписанный манифест -> apply -> staging python.new
    -> батник с переключением runtime (без службы/сети/реального апдейта)."""
    from server import api_update
    from server.app_state import STATE
    from core import update_verify as uv

    portable = tmp_path / "portable"
    app = make_app(portable, version="Pre-Release 0.11", required_rev="rev-old")
    make_runtime(portable, "rev-old")
    zp = build_portable_zip(tmp_path, version="Pre-Release 0.12",
                            runtime_rev="rev-new")

    sk, pk = uv.keygen()
    tag = "Pre-Release-0.12"
    raw = json.dumps({
        "schema": up.MANIFEST_SCHEMA,
        "version": "0.12",
        "tag": tag,
        "artifacts": {"portable": {"file": "p.zip", "sha256": "b" * 64}},
    }).encode()
    sig = uv.sign(raw, sk)
    monkeypatch.setattr(uv, "PUBKEY", pk)
    monkeypatch.setattr(up, "fetch_release_manifest",
                        lambda _tag, _dest: (raw, sig))
    monkeypatch.setattr(up, "fetch_update",
                        lambda _kind, _tag, _dest,
                        sha256_expected=None: zp)
    monkeypatch.setattr("core.service_manager.status",
                        lambda: "not_installed")
    monkeypatch.setattr("core.service_manager.is_installed", lambda: False)
    monkeypatch.setattr(api_update, "get_root_dir", lambda: app)
    # STATE.updater_state - стабильная ссылка на словарь; подменяем копией и
    # возвращаем исходный объект после теста.
    monkeypatch.setattr(STATE, "updater_state", dict(STATE.updater_state))

    api_update.run_update_worker("portable", tag,
                                 {"tag": tag, "latest": "0.12"})
    state = dict(STATE.updater_state)
    assert state["error"] is None, state["error"]
    res = state["result"] or {}
    assert res.get("signature_verified") is True
    assert res["runtime_update"]["portable"] is True
    assert res["runtime_update"]["staged"] is True
    assert res["runtime_update"]["rev"] == "rev-new"
    # живой python/ не тронут, подготовлен python.new
    assert up.read_runtime_rev(portable / "python") == "rev-old"
    assert up.read_runtime_rev(portable / "python.new") == "rev-new"
    assert up.read_required_runtime_rev(app) == "rev-new"
    # автоперезапуск несёт атомарное переключение runtime
    bat = app / "_restart_app.bat"
    assert bat.is_file()
    text = bat.read_text(encoding="ascii")
    assert 'move /y "%~dp0..\\python.new" "%~dp0..\\python"' in text
    assert ":rollback" in text


def test_worker_plain_restart_when_runtime_up_to_date(tmp_path: Path,
                                                      monkeypatch) -> None:
    """Если ревизия рантайма не менялась - обычный рестарт без move python/."""
    from server import api_update
    from server.app_state import STATE
    from core import update_verify as uv

    portable = tmp_path / "portable"
    app = make_app(portable, version="Pre-Release 0.11",
                   required_rev="rev-same")
    make_runtime(portable, "rev-same")
    zp = build_portable_zip(tmp_path, version="Pre-Release 0.12",
                            runtime_rev="rev-same")

    sk, pk = uv.keygen()
    tag = "Pre-Release-0.12"
    raw = json.dumps({
        "schema": up.MANIFEST_SCHEMA, "version": "0.12", "tag": tag,
        "artifacts": {"portable": {"file": "p.zip", "sha256": "b" * 64}},
    }).encode()
    monkeypatch.setattr(uv, "PUBKEY", pk)
    monkeypatch.setattr(up, "fetch_release_manifest",
                        lambda _tag, _dest: (raw, uv.sign(raw, sk)))
    monkeypatch.setattr(up, "fetch_update",
                        lambda _kind, _tag, _dest,
                        sha256_expected=None: zp)
    monkeypatch.setattr("core.service_manager.status",
                        lambda: "not_installed")
    monkeypatch.setattr("core.service_manager.is_installed", lambda: False)
    monkeypatch.setattr(api_update, "get_root_dir", lambda: app)
    monkeypatch.setattr(STATE, "updater_state", dict(STATE.updater_state))

    api_update.run_update_worker("portable", tag, {"tag": tag, "latest": "0.12"})
    state = dict(STATE.updater_state)
    assert state["error"] is None, state["error"]
    res = state["result"] or {}
    assert res["runtime_update"]["staged"] is False
    assert res["runtime_update"]["skipped"] == "up_to_date"
    bat = app / "_restart_app.bat"
    assert bat.is_file(), res.get("restart_bat")
    text = bat.read_text(encoding="ascii")
    assert "move /y" not in text          # переключать нечего
    assert "taskkill /F /PID" in text
