"""Built-in Valorant bypass requires opt-in."""
from core import games

VALORANT_DOMAINS = {"valorant.com", "playvalorant.com", "riotgames.com", "riotcdn.net"}


def test_valorant_domains_are_not_added_on_first_run(tmp_path):
    include = games.sync_include_list(tmp_path)
    assert include is not None
    domains = set(include.read_text(encoding="utf-8").splitlines())
    assert domains.isdisjoint(VALORANT_DOMAINS)


def test_saved_valorant_opt_in_adds_domains(tmp_path):
    data = games.default_games()
    valorant = next(game for game in data["games"] if game["id"] == "valorant")
    valorant["enabled"] = True
    assert games.save_games(tmp_path, data)

    include = games.sync_include_list(tmp_path)
    assert include is not None
    assert VALORANT_DOMAINS <= set(include.read_text(encoding="utf-8").splitlines())
