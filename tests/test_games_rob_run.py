"""ROB RUN (Kefir) — built-in game from live app-analysis log 2026-11-16."""
from core import games


def _rob_run():
    return next(g for g in games.default_games()["games"] if g["id"] == "rob-run")


def test_rob_run_builtin_valid_and_has_domains():
    g = _rob_run()
    assert g["enabled"] is True
    assert g["process"] == "Rob run.exe"
    domains = {d["domain"] for d in g["domains"]}
    assert "rob-run.kefir.games" in domains
    assert "api.epicgames.dev" in domains
    ok, err = games.validate_games(games.default_games())
    assert ok, err


def test_rob_run_udp_rule_is_active():
    g = _rob_run()
    rules = [r for r in g["udp"] if r.get("on")]
    assert rules
    assert rules[0]["ports"] == "36007,36501,36608,51619"
    assert "193.57.88.9/32" in rules[0]["cidrs"]
    # 443 намеренно не дублируем: он уже покрыт основными пресетами,
    # а 78.37.100.206:443 из лога не выглядит выделенным игровым сервером.
    assert "443" not in rules[0]["ports"].split(",")
    assert "78.37.100.206/32" not in rules[0]["cidrs"]
    enabled = games.enabled_udp_rules(games.default_games())
    assert any(r["id"] == "rob-run" for r in enabled)
