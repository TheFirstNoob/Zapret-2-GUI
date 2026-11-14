"""Tests for update availability (published manifest vs draft VERSION)."""
from core import updates


def test_draft_version_does_not_advertise_update(monkeypatch):
    monkeypatch.setattr(updates, "VERSION", "Pre-Release 0.10")
    monkeypatch.setattr(updates, "_fetch_published_version", lambda: "0.10")
    info = updates.check_for_updates()
    assert info["available"] is False
    assert info["tag"] == "Pre-Release-0.10"


def test_published_release_advertises_update(monkeypatch):
    monkeypatch.setattr(updates, "VERSION", "Pre-Release 0.10")
    monkeypatch.setattr(updates, "_fetch_published_version", lambda: "0.11")
    info = updates.check_for_updates()
    assert info["available"] is True
    assert info["tag"] == "Pre-Release-0.11"


def test_fallback_to_version_file_without_manifest(monkeypatch):
    monkeypatch.setattr(updates, "VERSION", "Pre-Release 0.10")
    monkeypatch.setattr(updates, "_fetch_published_version", lambda: None)
    monkeypatch.setattr(updates, "_fetch_latest_raw", lambda: "Pre-Release 0.11")
    monkeypatch.setattr(updates, "_fetch_latest_mirror", lambda: None)
    info = updates.check_for_updates()
    assert info["available"] is True
