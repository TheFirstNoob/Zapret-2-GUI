"""T20: probe-файлы - runtime/probe, уникальные имена, чистка, не в релиз.

Реальная сеть/движок не трогаются: _run_profile и пробы замоканы.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from core import tester, tester_probes
from core.tester_defs import TestResult as _TestResult

ROOT_DIR = Path(__file__).resolve().parents[1]


def _mk_root(tmp_path, marker=True):
    root = tmp_path / "App Root тест"   # пробелы + кириллица в пути
    (root / "presets").mkdir(parents=True)
    body = ["--new", "--filter-tcp", "443"]
    if marker:
        body.append("--hostlist=@lists/list-general.txt")
        body.append("--hostlist-exclude=@lists/list-exclude.txt")
    (root / "presets" / "default.txt").write_text(
        "\n".join(body) + "\n", encoding="utf-8")
    (root / "lists").mkdir()
    (root / "lists" / "list-general.txt").write_text("x.example\n",
                                                     encoding="utf-8")
    return root


def _mock_verify_engine(monkeypatch, t, run_ok=True):
    """Общие моки движка для _verify_with_desync/_verify_with_ipset."""
    calls = []

    def fake_run_profile(name, *args, **kwargs):
        preset = Path(kwargs["preset_path"]) if kwargs.get("preset_path") else None
        calls.append({"preset": preset,
                      "text": preset.read_text(encoding="utf-8") if preset else "",
                      "ipset_include_file": kwargs.get("ipset_include_file")})
        return run_ok if callable(run_ok) else run_ok

    monkeypatch.setattr(t, "_run_profile", fake_run_profile)
    monkeypatch.setattr(t, "_any_winws2_running", lambda: True)
    monkeypatch.setattr(t, "_ensure_winws2_dead", lambda: None)
    monkeypatch.setattr(t, "_probe_hostlist_error", lambda p: "")
    monkeypatch.setattr(
        t, "_run_domain_tests",
        lambda domains, **kw: [_TestResult(d, "https", "OK", 200, 1.0)
                               for d in domains])
    monkeypatch.setattr(tester_probes, "run_tcp1620_tests",
                        lambda *a, **k: [])
    return calls


# ── каталог/имена/чистка ────────────────────────────────────────────

def test_probe_file_unique_and_inside_app_root(tmp_path):
    root = tmp_path / "App Root тест"
    names = {tester_probes.probe_file(root, "list-probe", ".txt").name
             for _ in range(20)}
    assert len(names) == 20
    p = tester_probes.probe_file(root, "list-probe", ".txt")
    assert p.parent == root / "runtime" / "probe"
    assert p.parent.is_dir()
    assert "lists" not in p.parts and "presets" not in p.parts


def test_cleanup_stale_probe_files(tmp_path):
    root = tmp_path
    (root / "lists").mkdir()
    (root / "presets").mkdir()
    for rel in ("lists/list-probe.txt", "lists/ipset-probe.txt",
                "presets/_probe_cdn.txt"):
        (root / rel).write_text("probe", encoding="utf-8")
    (root / "lists" / "list-general.txt").write_text("keep\n", encoding="utf-8")
    fresh = tester_probes.probe_file(root, "fresh", ".txt")
    fresh.write_text("current", encoding="utf-8")
    old = tester_probes.probe_file(root, "old", ".txt")
    old.write_text("crashed", encoding="utf-8")
    os.utime(old, (0, 0))   # старый файл упавшего прогона

    removed = tester_probes.cleanup_stale_probe_files(root)

    assert old.name in removed
    assert fresh.exists()
    assert not (root / "lists" / "list-probe.txt").exists()
    assert not (root / "lists" / "ipset-probe.txt").exists()
    assert not (root / "presets" / "_probe_cdn.txt").exists()
    assert (root / "lists" / "list-general.txt").exists()


# ── пресет пробы: относительный hostlist ────────────────────────────

def test_probe_preset_uses_relative_hostlist(tmp_path):
    root = _mk_root(tmp_path)
    t = tester.Zapret2Tester(root)
    rel = "runtime\\probe\\list-probe-1-abcd.txt"
    text = t._probe_preset_text(rel)
    assert "--hostlist=" + rel in text
    assert "@lists/list-probe" not in text
    assert str(root) not in text.split("--hostlist=")[-1].splitlines()[0]
    # production-маркер остаётся на месте
    assert "--hostlist=@lists/list-general.txt" in text


def test_probe_preset_chdir_variant(tmp_path):
    root = _mk_root(tmp_path)
    t = tester.Zapret2Tester(root)
    text = t._probe_preset_text("runtime\\probe\\x.txt", with_chdir=True)
    assert text.startswith("--chdir=" + str(root))


def test_probe_preset_without_marker_is_empty(tmp_path):
    root = _mk_root(tmp_path, marker=False)
    t = tester.Zapret2Tester(root)
    assert t._probe_preset_text("runtime\\probe\\x.txt") == ""


def test_relative_to_root(tmp_path):
    root = _mk_root(tmp_path)
    t = tester.Zapret2Tester(root)
    inside = root / "runtime" / "probe" / "a.txt"
    assert t._relative_to_root(inside) == str(Path("runtime") / "probe" / "a.txt")
    outside = tmp_path / "elsewhere" / "a.txt"
    assert t._relative_to_root(outside) is None


# ── _verify_with_desync: рабочие файлы и cleanup ────────────────────

def test_verify_with_desync_uses_runtime_probe_files(monkeypatch, tmp_path):
    root = _mk_root(tmp_path)
    t = tester.Zapret2Tester(root)
    calls = _mock_verify_engine(monkeypatch, t)

    res = t._verify_with_desync(["a.example"], None)

    assert res == {"a.example": "fix"}
    text = calls[-1]["text"]
    m = re.search(r"--hostlist=(runtime[^\r\n]*)", text)
    assert m, text
    assert not Path(m.group(1)).is_absolute()
    assert "list-probe" in m.group(1)
    # пробные файлы удалены после прогона
    assert list((root / "runtime" / "probe").iterdir()) == []
    # живые каталоги не тронуты
    assert sorted(p.name for p in (root / "presets").iterdir()) == ["default.txt"]
    assert sorted(p.name for p in (root / "lists").iterdir()) == ["list-general.txt"]
    # для пресета передан явный preset_path (а не presets/_probe_cdn.txt)
    assert calls[-1]["preset"] is not None
    assert calls[-1]["preset"].parent == root / "runtime" / "probe"


def test_verify_with_desync_chdir_fallback(monkeypatch, tmp_path):
    root = _mk_root(tmp_path)
    t = tester.Zapret2Tester(root)
    texts = []

    def fake_run_profile(name, *a, **kw):
        texts.append(Path(kw["preset_path"]).read_text(encoding="utf-8"))
        return len(texts) > 1   # первая попытка «не стартовала»

    monkeypatch.setattr(t, "_run_profile", fake_run_profile)
    monkeypatch.setattr(t, "_any_winws2_running", lambda: True)
    monkeypatch.setattr(t, "_ensure_winws2_dead", lambda: None)
    monkeypatch.setattr(t, "_probe_hostlist_error", lambda p: "")
    monkeypatch.setattr(
        t, "_run_domain_tests",
        lambda domains, **kw: [_TestResult(d, "https", "OK", 200, 1.0)
                               for d in domains])
    monkeypatch.setattr(tester_probes, "run_tcp1620_tests", lambda *a, **k: [])

    res = t._verify_with_desync(["a.example"], None)

    assert res == {"a.example": "fix"}
    assert len(texts) == 2
    assert "--chdir=" not in texts[0]
    assert "--chdir=" in texts[1]
    assert list((root / "runtime" / "probe").iterdir()) == []


def test_verify_with_desync_hostlist_open_error_retries_then_unknown(monkeypatch, tmp_path):
    root = _mk_root(tmp_path)
    t = tester.Zapret2Tester(root)
    _mock_verify_engine(monkeypatch, t)
    monkeypatch.setattr(t, "_probe_hostlist_error",
                        lambda p: "cannot open " + p.name)   # всегда не открылся

    res = t._verify_with_desync(["a.example"], None)

    # движок «стартовал», но hostlist пробы не открылся -> НЕ hard, а unknown
    assert res == {}
    assert list((root / "runtime" / "probe").iterdir()) == []


def test_verify_with_desync_no_marker_returns_unknown(monkeypatch, tmp_path):
    root = _mk_root(tmp_path, marker=False)
    t = tester.Zapret2Tester(root)
    calls = _mock_verify_engine(monkeypatch, t)
    res = t._verify_with_desync(["a.example"], None)
    assert res == {} and calls == []
    assert list((root / "runtime" / "probe").iterdir()) == []


# ── _verify_with_ipset: рабочий файл в runtime/probe ───────────────

def test_verify_with_ipset_uses_runtime_probe_file(monkeypatch, tmp_path):
    root = _mk_root(tmp_path)
    t = tester.Zapret2Tester(root)
    captured = {}

    def fake_run_profile(name, *a, **kw):
        inc = Path(kw["ipset_include_file"])
        captured["path"] = inc
        captured["content"] = inc.read_text(encoding="utf-8")
        assert inc.exists()
        return True

    monkeypatch.setattr(t, "_run_profile", fake_run_profile)
    monkeypatch.setattr(t, "_any_winws2_running", lambda: True)
    monkeypatch.setattr(t, "_ensure_winws2_dead", lambda: None)
    monkeypatch.setattr(
        t, "_run_domain_tests",
        lambda domains, **kw: [_TestResult(d, "https", "OK", 200, 1.0)
                               for d in domains])
    monkeypatch.setattr(tester_probes, "resolve_ips",
                        lambda d, timeout=2.0: ["203.0.113.5"])
    monkeypatch.setattr(tester_probes, "run_tcp1620_tests", lambda *a, **k: [])

    res = t._verify_with_ipset(["a.example"], None)

    assert res == {"a.example": "fix"}
    assert "203.0.113.5" in captured["content"]
    assert captured["path"].parent == root / "runtime" / "probe"
    assert list((root / "runtime" / "probe").iterdir()) == []


# ── гарантии релизной сборки/диагностики ───────────────────────────

def test_runtime_dir_not_packaged_or_collected():
    import build_lite
    import build_portable
    from core import collector, updater
    # EXE/portable/lite собирают только явные каталоги: runtime/ не входит.
    assert "runtime" not in build_portable.COPY_DIRS
    assert "runtime" not in build_lite.COPY_DIRS
    # spec и build.py перечисляют каталоги/staging вручную - runtime/ нет.
    spec = (ROOT_DIR / "Zapret2GUI.spec").read_text(encoding="utf-8")
    build_py = (ROOT_DIR / "build.py").read_text(encoding="utf-8")
    assert "runtime" not in spec and "runtime" not in build_py
    # collector кладёт в ZIP только presets/ и lists/ (никаких probe-файлов).
    collector_src = (ROOT_DIR / "core" / "collector.py").read_text(
        encoding="utf-8")
    assert "runtime" not in collector_src
    # updater не считает probe-файлы ни user-, ни runtime-файлами.
    assert not any("probe" in p for p in updater.USER_FILES)
    assert not any("probe" in p for p in updater.RUNTIME_FILES)
    assert updater.is_user_file("lists/list-include-user.txt") is True
    assert updater.is_user_file("lists/list-exclude-user.txt") is True
