from __future__ import annotations

from core import games


def _payload(ports: str, repeats=1, cutoff=4, cidrs=None) -> dict:
    return {"games": [{
        "id": "custom", "name": "Custom", "enabled": True,
        "domains": [], "udp": [{
            "ports": ports, "on": True, "repeats": repeats,
            "cutoff": cutoff, "cidrs": cidrs or [],
        }],
    }]}


def test_udp_ports_cannot_inject_arguments() -> None:
    data = _payload("443\n--new")
    assert games.validate_games(data)[0] is False
    assert games.enabled_udp_rules(data) == []


def test_udp_ports_are_normalized() -> None:
    data = _payload("0443, 500-500, 500-500")
    rules = games.enabled_udp_rules(data)
    assert len(rules) == 1
    assert rules[0]["ports"] == "443,500"


def test_udp_repeats_and_cutoff_are_bounded() -> None:
    data = _payload("443", repeats=999, cutoff=-5)
    assert games.validate_games(data)[0] is False
    assert games.enabled_udp_rules(data)[0]["repeats"] == games.DEFAULT_REPEATS
    assert games.enabled_udp_rules(data)[0]["cutoff"] == games.DEFAULT_CUTOFF


def test_valid_udp_rule_survives_roundtrip() -> None:
    data = _payload("443,5000-5010", repeats=6, cutoff=2,
                    cidrs=["10.0.0.0/24"])
    assert games.validate_games(data) == (True, "")
    rule = games.enabled_udp_rules(data)[0]
    assert rule["ports"] == "443,5000-5010"
    assert rule["repeats"] == 6
    assert rule["cutoff"] == 2
    assert rule["cidrs"] == ["10.0.0.0/24"]
