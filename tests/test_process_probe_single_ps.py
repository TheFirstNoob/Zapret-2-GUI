"""T19: ProcessProbe - один PowerShell-вызов на тик + fallback.

Сеть не трогаем: _ps подменяется синтетическим JSON, проверяются счётчики
вызовов и разбор (поля/формат прежние).
"""
from __future__ import annotations

import json

from core import process_probe as pp


def _payload() -> dict:
    return {
        "tcp": [{"ra": "1.2.3.4", "rp": 443, "st": "Established"},
                {"ra": "10.0.0.1", "rp": 80, "st": "SynSent"}],
        "udp": [{"LocalAddress": "0.0.0.0", "LocalPort": 5000}],
        "dns": [{"Entry": "example.com", "Data": "93.184.216.34"}],
    }


def test_net_snapshot_single_ps_call_and_parsing(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(pp, "_ps",
                        lambda script: calls.append(script) or json.dumps(_payload()))
    snap = pp._net_snapshot([10, 11], include_dns=True)
    assert snap is not None
    assert len(calls) == 1  # tcp+udp+dns одним вызовом, а не тремя
    script = calls[0]
    assert "Get-NetTCPConnection" in script
    assert "Get-NetUDPEndpoint" in script
    assert "Get-DnsClientCache" in script
    assert "@(10,11)" in script
    tcp = pp._parse_tcp_items(snap["tcp"])
    # private 10/8 НЕ фильтруется _tcp_snapshot и раньше (только 0.0.0.0/::)
    assert tcp == {"1.2.3.4:443": {"state": "Established", "n": 1},
                   "10.0.0.1:80": {"state": "SynSent", "n": 1}}
    assert pp._parse_udp_items(snap["udp"]) == {"0.0.0.0:5000": 1}
    assert pp._parse_dns_items(snap["dns"]) == {"93.184.216.34": ["example.com"]}


def test_net_snapshot_without_dns_skips_dns_cmdlet(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(pp, "_ps",
                        lambda script: calls.append(script) or json.dumps(
                            {"tcp": [], "udp": [], "dns": []}))
    pp._net_snapshot([1], include_dns=False)
    assert "Get-DnsClientCache" not in calls[0]


def test_net_snapshot_fallback_on_broken_output(monkeypatch) -> None:
    monkeypatch.setattr(pp, "_ps", lambda script: "not a json")
    assert pp._net_snapshot([1]) is None
    monkeypatch.setattr(pp, "_ps", lambda script: "")
    assert pp._net_snapshot([1]) is None


def test_net_snapshot_normalizes_single_object(monkeypatch) -> None:
    payload = {"tcp": {"ra": "8.8.8.8", "rp": 53, "st": "Established"},
               "udp": {}, "dns": []}
    monkeypatch.setattr(pp, "_ps", lambda script: json.dumps(payload))
    snap = pp._net_snapshot([1])
    assert snap["tcp"] == [payload["tcp"]]


def test_rescan_snapshot_single_ps_call(monkeypatch) -> None:
    calls: list = []
    payload = {"pids": [10, 11, "x"], "ports": [5000, 0, "70000", 5000]}
    monkeypatch.setattr(pp, "_ps",
                        lambda script: calls.append(script) or json.dumps(payload))
    snap = pp._rescan_snapshot([10], "WardogsClient")
    assert snap == {"pids": [10, 11], "ports": [5000]}
    assert len(calls) == 1
    assert "Get-Process" in calls[0]
    assert "*WardogsClient*" in calls[0]


def test_rescan_script_validates_mask() -> None:
    assert pp._rescan_script([1], "bad;rm -rf") is None
    assert "@(123)" in pp._rescan_script([1], "123")
    assert "Get-NetUDPEndpoint" in pp._rescan_script([1], "123")


def test_rescan_snapshot_fallback_on_broken_output(monkeypatch) -> None:
    monkeypatch.setattr(pp, "_ps", lambda script: "oops")
    assert pp._rescan_snapshot([1], "game") is None


def test_legacy_separate_snapshots_still_work(monkeypatch) -> None:
    tcp_payload = [{"ra": "8.8.8.8", "rp": 443, "st": "SynSent"}]
    monkeypatch.setattr(pp, "_ps", lambda script: json.dumps(tcp_payload))
    assert pp._tcp_snapshot([1]) == {"8.8.8.8:443": {"state": "SynSent", "n": 1}}
    udp_payload = [{"LocalAddress": "0.0.0.0", "LocalPort": 1234}]
    monkeypatch.setattr(pp, "_ps", lambda script: json.dumps(udp_payload))
    assert pp._udp_snapshot([1]) == {"0.0.0.0:1234": 1}


def _prime_state(probe) -> None:
    """_run_inner рассчитывает на _state, который создаёт start()."""
    probe._state = {"process": "game", "elapsed": 0, "duration": 1,
                    "tcp": {}, "udp": {}, "history": {}, "udp_capture": None,
                    "dns": {}, "verdict": "", "error": "", "phase": "старт"}


def test_tick_uses_combined_snapshot(monkeypatch, tmp_path) -> None:
    probe = pp.ProcessProbe()
    _prime_state(probe)
    monkeypatch.setattr(probe, "_find_pids", lambda spec: [7])
    monkeypatch.setattr(pp, "_run_pktmon", lambda *a, **k: None)
    monkeypatch.setattr(pp.utils, "get_temp_dir", lambda: tmp_path)
    monkeypatch.setattr(pp.time, "sleep", lambda _s: None)
    monkeypatch.setattr(pp, "_rescan_snapshot", lambda pids, spec: {"pids": [], "ports": []})
    calls = {"net": 0, "legacy": 0}

    def net_snapshot(pids, include_dns=False):
        calls["net"] += 1
        return {"tcp": [{"ra": "1.1.1.1", "rp": 443,
                         "st": "Established"}],
                "udp": [], "dns": []}

    def legacy(*a, **k):
        calls["legacy"] += 1
        return {}

    monkeypatch.setattr(pp, "_net_snapshot", net_snapshot)
    monkeypatch.setattr(pp, "_tcp_snapshot", legacy)
    monkeypatch.setattr(pp, "_udp_snapshot", legacy)
    monkeypatch.setattr(pp, "_dns_cache_entries", lambda: {})
    probe._run_inner("game", 0.01, 0)  # ~один тик, без реальных пауз
    state = probe.get_status()
    assert state["phase"] == "завершено"
    assert calls["net"] >= 1
    assert calls["legacy"] == 0
    assert "1.1.1.1:443" in state["tcp"]


def test_tick_falls_back_when_combined_unparsed(monkeypatch, tmp_path) -> None:
    probe = pp.ProcessProbe()
    _prime_state(probe)
    monkeypatch.setattr(probe, "_find_pids", lambda spec: [7])
    monkeypatch.setattr(pp, "_run_pktmon", lambda *a, **k: None)
    monkeypatch.setattr(pp.utils, "get_temp_dir", lambda: tmp_path)
    monkeypatch.setattr(pp.time, "sleep", lambda _s: None)
    monkeypatch.setattr(pp, "_rescan_snapshot", lambda pids, spec: {"pids": [], "ports": []})
    calls = {"tcp": 0}

    def tcp_snapshot(pids):
        calls["tcp"] += 1
        return {"2.2.2.2:80": {"state": "SynSent", "n": 1}}

    monkeypatch.setattr(pp, "_net_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_tcp_snapshot", tcp_snapshot)
    monkeypatch.setattr(pp, "_udp_snapshot", lambda pids: {})
    monkeypatch.setattr(pp, "_dns_cache_entries", lambda: {})
    probe._run_inner("game", 0.01, 0)  # ~один тик, без реальных пауз
    state = probe.get_status()
    assert state["phase"] == "завершено"
    assert calls["tcp"] >= 1
    assert "2.2.2.2:80" in state["tcp"]
