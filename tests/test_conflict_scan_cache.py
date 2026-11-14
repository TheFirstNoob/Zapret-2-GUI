"""T21: короткий TTL-кэш conflict_scan (аудит 2026-11-14).

Сеть/служба не опрашиваются: raw-загрузчики подменены фейками.
"""
from __future__ import annotations

from core import conflict_scan


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _patch_loaders(monkeypatch, clock, images=None, adapters=None,
                   services=None) -> dict:
    calls = {"images": 0, "adapters": 0, "services": 0}

    def _make(name, values):
        def _load():
            calls[name] += 1
            return list(values)
        return _load

    monkeypatch.setattr(conflict_scan, "_load_running_images",
                        _make("images", images or []))
    monkeypatch.setattr(conflict_scan, "_load_adapter_descriptions",
                        _make("adapters", adapters or []))
    monkeypatch.setattr(conflict_scan, "_load_running_services",
                        _make("services", services or []))
    monkeypatch.setattr(conflict_scan, "_now", clock)
    conflict_scan.clear_cache()
    return calls


def test_scans_within_ttl_are_cached(monkeypatch) -> None:
    clock = _Clock()
    # Непустые результаты = успешный опрос (пусто трактуется как сбой и не
    # кэшируется - см. test_error_result_is_not_cached).
    calls = _patch_loaders(monkeypatch, clock,
                           images=["byedpi.exe"],
                           adapters=["Intel(R) Wi-Fi"],
                           services=["OpenVPNService"])
    first = conflict_scan.scan()
    second = conflict_scan.scan()
    assert first.dpi_tools == ["ByeDPI (byedpi.exe)"]
    assert second.dpi_tools == first.dpi_tools
    assert first.vpn_services == ["OpenVPN"]
    assert second.vpn_services == ["OpenVPN"]
    assert calls == {"images": 1, "adapters": 1, "services": 1}


def test_cache_expires_after_ttl(monkeypatch) -> None:
    clock = _Clock()
    calls = _patch_loaders(monkeypatch, clock, images=["winws.exe"])
    conflict_scan.scan()
    clock.advance(conflict_scan._CACHE_TTL_SEC - 0.5)
    conflict_scan.scan()
    assert calls["images"] == 1  # ещё в окне
    clock.advance(1.0)
    conflict_scan.scan()
    assert calls["images"] == 2  # окно истекло


def test_error_result_is_not_cached(monkeypatch) -> None:
    clock = _Clock()
    calls = _patch_loaders(monkeypatch, clock)  # пусто = вероятный сбой опроса
    conflict_scan.scan()
    conflict_scan.scan()
    assert calls == {"images": 2, "adapters": 2, "services": 2}


def test_services_queried_once_per_scan(monkeypatch) -> None:
    clock = _Clock()
    calls = _patch_loaders(
        monkeypatch, clock,
        services=["OpenVPNService", "Tailscale", "ZeroTierOne"])
    rep = conflict_scan.scan()
    assert calls["services"] == 1  # раньше sc query звался 5 раз на скан
    assert rep.vpn_services == ["OpenVPN", "Tailscale", "ZeroTier"]


def test_tun_adapters_and_hard_conflict(monkeypatch) -> None:
    clock = _Clock()
    _patch_loaders(monkeypatch, clock,
                   images=["goodbyedpi.exe"],
                   adapters=["Wintun Userspace Tunnel", "Intel(R) Wi-Fi"])
    rep = conflict_scan.scan()
    assert rep.hard_conflict is True
    assert rep.dpi_tools == ["GoodbyeDPI (goodbyedpi.exe)"]
    assert rep.tun_adapters == ["Wintun Userspace Tunnel"]
    assert rep.warnings is True
    text = conflict_scan.describe(rep)
    assert text and "GoodbyeDPI" in text and "Туннельный адаптер" in text


def test_clear_cache_forces_reload(monkeypatch) -> None:
    clock = _Clock()
    calls = _patch_loaders(monkeypatch, clock, images=["byedpi.exe"])
    conflict_scan.scan()
    conflict_scan.clear_cache()
    conflict_scan.scan()
    assert calls["images"] == 2
