"""ProtonDB rating on the game page."""

from types import SimpleNamespace

import requests

from gamingcrypt.steam.protondb import MAX_AGE_S, ProtonDB, label


def response(status, data=None):
    return SimpleNamespace(status_code=status, json=lambda: data)


def test_tier_fetched_once_and_cached(tmp_path):
    calls = []
    clock = [1000.0]
    db = ProtonDB(tmp_path, get=lambda url: calls.append(url) or response(200, {"tier": "platinum"}),
                  now=lambda: clock[0])
    assert db.cached(620) is None
    assert db.tier(620) == "platinum" and db.cached(620) == "platinum"
    assert db.tier(620) == "platinum" and len(calls) == 1  # from the cache
    assert calls[0] == "https://www.protondb.com/api/v1/reports/summaries/620.json"
    clock[0] += MAX_AGE_S + 1
    db.tier(620)
    assert len(calls) == 2  # a week later: asked again


def test_no_reports_and_offline(tmp_path):
    db = ProtonDB(tmp_path, get=lambda url: response(404))
    assert db.tier(1) == "" and db.cached(1) == ""  # remembered: nobody reported it

    def offline(url):
        raise requests.ConnectionError("no network")

    db2 = ProtonDB(tmp_path / "b", get=offline)
    assert db2.tier(2) == "" and db2.cached(2) is None  # not cached: try again next time
    db3 = ProtonDB(tmp_path / "c", get=lambda url: response(500))
    assert db3.tier(3) == "" and db3.cached(3) is None


def test_labels():
    assert label("platinum") == "ProtonDB: ★ Platinum"
    assert label("borked") == "ProtonDB: ✕ Borked"
    assert label("") == "" and label(None) == ""


def test_game_page_shows_the_rating(qtbot):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    service = FakeService()
    service.protondb_cached = lambda appid: None
    service.protondb_tier = lambda appid: {620: "gold"}.get(appid, "")
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.games.update({g.appid: g for g in service.games})
    tab.open_game(620)
    page = tab.currentWidget()
    qtbot.waitUntil(lambda: "ProtonDB: ● Gold" in page.facts.text())
    service.protondb_cached = lambda appid: "platinum"
    tab.open_game(1145360)
    assert "ProtonDB: ★ Platinum" in tab.currentWidget().facts.text()  # cached: right away
