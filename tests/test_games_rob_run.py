"""ROB RUN (Kefir) — built-in game from live app-analysis log 2026-11-16."""
from core import games


def _rob_run():
    return next(g for g in games.default_games()["games"] if g["id"] == "rob-run")


def test_rob_run_builtin_valid_and_has_domains():
    g = _rob_run()
    assert g["enabled"] is True
    assert g["process"] == "start_protected_game.exe"
    domains = {d["domain"] for d in g["domains"]}
    assert "kefir.games" in domains
    assert "api.epicgames.dev" in domains
    ok, err = games.validate_games(games.default_games())
    assert ok, err


def test_rob_run_udp_rule_is_active():
    g = _rob_run()
    rules = [r for r in g["udp"] if r.get("on")]
    assert rules
    assert rules[0]["ports"].startswith("443,36")
    assert "193.57.88.0/24" in rules[0]["cidrs"]
    enabled = games.enabled_udp_rules(games.default_games())
    assert any(r["id"] == "rob-run" for r in enabled)
