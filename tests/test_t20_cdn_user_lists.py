"""T20/T14: CDN-стабилизатор не пишет в bundled-списки.

Bundled list-general.txt/list-exclude.txt перезаписываются апдейтером -
правка пользователя терялась молча. Все CDN-действия должны целиться в
user-каналы (lists/*-user.txt), которые updater.is_user_file сохраняет.
"""
from __future__ import annotations

import pytest

from core import list_health, updater
from server import api_cdn

BUNDLED_TARGETS = {"list-general.txt", "list-exclude.txt"}


def _patch_plan(monkeypatch, tmp_path, cov=None):
    """_plan_cdn_action без реальных файлов: чтение списков и coverage - фейк."""
    recorded: list[str] = []

    def fake_read_lines(fname):
        recorded.append(fname)
        return set()

    monkeypatch.setattr(api_cdn, "_read_lines", fake_read_lines)
    monkeypatch.setattr(api_cdn, "get_root_dir", lambda: tmp_path)
    monkeypatch.setattr(
        list_health, "coverage",
        lambda root, domains: {d: dict(cov or {}) for d in domains})
    return recorded


def test_general_targets_user_include_list(monkeypatch, tmp_path):
    _patch_plan(monkeypatch, tmp_path)
    ok, msg, entries = api_cdn._plan_cdn_action(
        "cdn.example", "general", [], set(), ipset_mode=False)
    assert ok and not msg
    assert entries == [("list-include-user.txt", ["cdn.example"])]
    assert updater.is_user_file("lists/" + entries[0][0]) is True


def test_exclude_targets_user_exclude_list(monkeypatch, tmp_path):
    _patch_plan(monkeypatch, tmp_path)
    ok, msg, entries = api_cdn._plan_cdn_action(
        "broken.example", "exclude", [], set(), ipset_mode=False)
    assert ok and not msg
    assert entries == [("list-exclude-user.txt", ["broken.example"])]
    assert updater.is_user_file("lists/" + entries[0][0]) is True


def test_ipset_actions_target_user_lists(monkeypatch, tmp_path):
    _patch_plan(monkeypatch, tmp_path)
    ok, _, entries = api_cdn._plan_cdn_action(
        "cdn.example", "ipset-include", ["203.0.113.5"], set(), ipset_mode=True)
    assert ok and entries[0][0] == "ipset-include-user.txt"
    ok, _, entries = api_cdn._plan_cdn_action(
        "cdn.example", "ipset-exclude", ["203.0.113.5"], set(), ipset_mode=True)
    assert ok and entries[0][0] == "ipset-exclude-user.txt"
    for fname, _ in entries:
        assert updater.is_user_file("lists/" + fname) is True


def test_general_in_ipset_mode_targets_user_ipset(monkeypatch, tmp_path):
    _patch_plan(monkeypatch, tmp_path)
    ok, _, entries = api_cdn._plan_cdn_action(
        "cdn.example", "general", ["203.0.113.5"], set(), ipset_mode=True)
    assert ok and entries == [("ipset-include-user.txt", ["203.0.113.5"])]


@pytest.mark.parametrize("action", ["general", "exclude"])
def test_no_bundled_targets_ever(monkeypatch, tmp_path, action):
    _patch_plan(monkeypatch, tmp_path)
    _, _, entries = api_cdn._plan_cdn_action(
        "cdn.example", action, [], set(), ipset_mode=False)
    for fname, _ in entries:
        assert fname not in BUNDLED_TARGETS, "bundled-список апдейтер перезапишет"
    assert updater.is_user_file("lists/list-general.txt") is False
    assert updater.is_user_file("lists/list-exclude.txt") is False


def test_already_covered_domain_not_duplicated(monkeypatch, tmp_path):
    _patch_plan(monkeypatch, tmp_path, cov={"includes": ["list-include-user.txt"]})
    ok, msg, entries = api_cdn._plan_cdn_action(
        "cdn.example", "general", [], set(), ipset_mode=False)
    assert ok and entries == []
    assert "уже в обходе" in msg


def test_bundled_exclusion_is_stronger_than_general(monkeypatch, tmp_path):
    _patch_plan(monkeypatch, tmp_path, cov={"excludes": ["list-exclude.txt"]})
    ok, msg, entries = api_cdn._plan_cdn_action(
        "cdn.example", "general", [], set(), ipset_mode=False)
    assert not ok and entries == []
    assert "стандартных исключениях" in msg


def test_already_excluded_domain_not_duplicated(monkeypatch, tmp_path):
    _patch_plan(monkeypatch, tmp_path,
                cov={"excludes": ["list-exclude-user.txt"]})
    ok, msg, entries = api_cdn._plan_cdn_action(
        "bad.example", "exclude", [], set(), ipset_mode=False)
    assert ok and entries == []
    assert "уже в исключениях" in msg